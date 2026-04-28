"""OpenAPI proxy launcher with health, metrics, auth, and rate limiting."""

from __future__ import annotations

import argparse
import logging
import os
import time
from collections import deque
from typing import Any, Optional, cast

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from mcpo.main import lifespan
from mcpo.utils.auth import APIKeyMiddleware, get_verify_api_key
from starlette.middleware.base import BaseHTTPMiddleware

from proxmox_mcp.observability import HttpRequestMetrics
from proxmox_mcp.services.jobs import JobConflictError, JobNotFoundError

LOGGER = logging.getLogger(__name__)


def _parse_cors_allow_origins(value: Optional[str]) -> list[str]:
    if not value:
        return ["*"]
    return [item.strip() for item in value.split(",") if item.strip()]


def _security_warnings(*, api_key: Optional[str], strict_auth: bool, cors_allow_origins: list[str]) -> list[str]:
    warnings: list[str] = []
    if not api_key:
        warnings.append("OpenAPI proxy is running without PROXMOX_API_KEY.")
    if api_key and not strict_auth:
        warnings.append("PROXMOX_API_KEY is configured but PROXMOX_STRICT_AUTH is disabled.")
    if "*" in cors_allow_origins:
        warnings.append("CORS allows all origins; set MCPO_CORS_ALLOW_ORIGINS for production.")
    return warnings


class ProxyMetricsMiddleware(BaseHTTPMiddleware):
    """Capture basic per-route request metrics."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        metrics: HttpRequestMetrics = request.app.state.http_metrics
        start = time.perf_counter()
        response = None
        try:
            response = await call_next(request)
            return response
        finally:
            latency_ms = (time.perf_counter() - start) * 1000.0
            status_code = response.status_code if response is not None else 500
            metrics.observe(request.url.path, request.method, status_code, latency_ms)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple fixed-window in-memory rate limiter per client address."""

    def __init__(self, app: FastAPI, *, requests_per_minute: int) -> None:
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self._buckets: dict[str, deque[float]] = {}

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if self.requests_per_minute <= 0:
            return await call_next(request)

        client_host = request.client.host if request.client else "unknown"
        now = time.time()
        window_start = now - 60.0
        bucket = self._buckets.setdefault(client_host, deque())
        while bucket and bucket[0] < window_start:
            bucket.popleft()

        if len(bucket) >= self.requests_per_minute:
            return JSONResponse(
                status_code=429,
                content={
                    "status": "rate_limited",
                    "message": "Too many requests",
                    "limit_per_minute": self.requests_per_minute,
                },
            )

        bucket.append(now)
        return await call_next(request)


def create_app(
    server_command: list[str],
    *,
    api_key: Optional[str],
    strict_auth: bool,
    cors_allow_origins: list[str],
    job_store: Any | None = None,
    name: str = "MCP OpenAPI Proxy",
    description: str = "Automatically generated API from MCP Tool Schemas",
    version: str = "1.0",
    path_prefix: str = "/",
    root_path: str = "",
    rate_limit_rpm: int = 0,
) -> FastAPI:
    """Create a FastAPI app that mirrors mcpo behavior and adds ops routes."""
    api_dependency = get_verify_api_key(api_key) if api_key else None

    app = FastAPI(
        title=name,
        description=description,
        version=version,
        root_path=root_path,
        lifespan=lifespan,
    )

    app.state.started_at = time.time()
    app.state.http_metrics = HttpRequestMetrics()
    app.state.rate_limit_rpm = rate_limit_rpm
    app.add_middleware(ProxyMetricsMiddleware)
    if rate_limit_rpm > 0:
        app.add_middleware(cast(Any, RateLimitMiddleware), requests_per_minute=rate_limit_rpm)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if api_key and strict_auth:
        app.add_middleware(APIKeyMiddleware, api_key=api_key)

    app.state.path_prefix = path_prefix
    app.state.server_type = "stdio"
    app.state.command = server_command[0]
    app.state.args = server_command[1:]
    app.state.env = os.environ.copy()
    app.state.api_dependency = api_dependency
    app.state.api_key_configured = bool(api_key)
    app.state.strict_auth = strict_auth
    app.state.job_store = job_store
    app.state.security_warnings = _security_warnings(
        api_key=api_key,
        strict_auth=strict_auth,
        cors_allow_origins=cors_allow_origins,
    )

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "name": name,
            "status": "ok",
            "docs": "/docs",
            "openapi": "/openapi.json",
            "health": "/health",
            "metrics": "/metrics",
            "jobs": "/jobs",
        }

    @app.get("/health", include_in_schema=False)
    async def health() -> JSONResponse:
        is_connected = bool(getattr(app.state, "is_connected", False))
        uptime_seconds = round(time.time() - app.state.started_at, 3)
        status_code = 200 if is_connected else 503
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "ok" if is_connected else "degraded",
                "connected_to_mcp": is_connected,
                "uptime_seconds": uptime_seconds,
                "server_type": app.state.server_type,
                "command": app.state.command,
                "args": app.state.args,
                "auth": {
                    "api_key_configured": app.state.api_key_configured,
                    "strict_auth": app.state.strict_auth,
                },
                "rate_limit": {
                    "enabled": app.state.rate_limit_rpm > 0,
                    "requests_per_minute": app.state.rate_limit_rpm,
                },
                "jobs": {
                    "enabled": app.state.job_store is not None,
                },
                "security_warnings": app.state.security_warnings,
            },
        )

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> PlainTextResponse:
        return PlainTextResponse(
            app.state.http_metrics.render_prometheus(),
            media_type="text/plain; version=0.0.4",
        )

    def _require_job_store() -> Any:
        job_store_local = getattr(app.state, "job_store", None)
        if job_store_local is None:
            raise RuntimeError("JobStore is not available in this OpenAPI process")
        return job_store_local

    def _job_error_response(error: Exception) -> JSONResponse:
        LOGGER.warning("Job route error: %s", error, exc_info=True)
        if isinstance(error, JobNotFoundError):
            return JSONResponse(status_code=404, content={"status": "not_found", "message": "Job was not found"})
        if isinstance(error, JobConflictError):
            return JSONResponse(status_code=409, content={"status": "conflict", "message": "Job cannot perform that operation right now"})
        if isinstance(error, RuntimeError):
            return JSONResponse(status_code=503, content={"status": "unavailable", "message": "Job service is unavailable in this process"})
        return JSONResponse(status_code=400, content={"status": "error", "message": "Job request failed"})

    @app.get("/jobs")
    async def list_jobs(
        status: Optional[str] = None,
        tool_name: Optional[str] = None,
        limit: int = 100,
    ) -> JSONResponse:
        try:
            payload = _require_job_store().list_jobs(status=status, tool_name=tool_name, limit=limit)
            return JSONResponse(status_code=200, content=payload)
        except Exception as exc:  # noqa: BLE001
            return _job_error_response(exc)

    @app.get("/jobs/{job_id}")
    async def get_job(job_id: str, refresh: bool = False) -> JSONResponse:
        try:
            job_store_local = _require_job_store()
            payload = job_store_local.poll_job(job_id) if refresh else job_store_local.get_job(job_id)
            return JSONResponse(status_code=200, content=payload)
        except Exception as exc:  # noqa: BLE001
            return _job_error_response(exc)

    @app.post("/jobs/{job_id}/poll")
    async def poll_job(job_id: str) -> JSONResponse:
        try:
            payload = _require_job_store().poll_job(job_id)
            return JSONResponse(status_code=200, content=payload)
        except Exception as exc:  # noqa: BLE001
            return _job_error_response(exc)

    @app.post("/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str) -> JSONResponse:
        try:
            payload = _require_job_store().cancel_job(job_id)
            return JSONResponse(status_code=202, content=payload)
        except Exception as exc:  # noqa: BLE001
            return _job_error_response(exc)

    @app.post("/jobs/{job_id}/retry")
    async def retry_job(job_id: str) -> JSONResponse:
        try:
            payload = _require_job_store().retry_job(job_id)
            return JSONResponse(status_code=202, content=payload)
        except Exception as exc:  # noqa: BLE001
            return _job_error_response(exc)

    return app


def main() -> None:
    """Run OpenAPI proxy as a uvicorn server."""
    parser = argparse.ArgumentParser(description="Run Proxmox MCP OpenAPI proxy")
    parser.add_argument("--host", default=os.getenv("API_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("API_PORT", "8811")))
    parser.add_argument("--api-key", default=os.getenv("PROXMOX_API_KEY"))
    parser.add_argument(
        "--strict-auth",
        action="store_true",
        default=os.getenv("PROXMOX_STRICT_AUTH", "false").lower() == "true",
    )
    parser.add_argument(
        "--cors-allow-origins",
        default=os.getenv("MCPO_CORS_ALLOW_ORIGINS", "*"),
    )
    parser.add_argument(
        "--path-prefix",
        default=os.getenv("MCPO_PATH_PREFIX", "/"),
    )
    parser.add_argument(
        "--root-path",
        default=os.getenv("MCPO_ROOT_PATH", ""),
    )
    parser.add_argument(
        "--rate-limit-rpm",
        type=int,
        default=int(os.getenv("PROXMOX_RATE_LIMIT_RPM", "0")),
        help="Maximum requests per minute per client IP. 0 disables rate limiting.",
    )
    parser.add_argument(
        "server_command",
        nargs=argparse.REMAINDER,
        help="Command after '--' used to launch MCP stdio server",
    )

    args = parser.parse_args()
    server_command = args.server_command
    if server_command and server_command[0] == "--":
        server_command = server_command[1:]

    if not server_command:
        parser.error("Missing MCP server command. Use '-- <command>' to pass it.")

    LOGGER.info(
        "Starting OpenAPI proxy on %s:%s with command: %s",
        args.host,
        args.port,
        " ".join(server_command),
    )

    security_warnings = _security_warnings(
        api_key=args.api_key,
        strict_auth=args.strict_auth,
        cors_allow_origins=_parse_cors_allow_origins(args.cors_allow_origins),
    )
    for warning in security_warnings:
        LOGGER.warning("OpenAPI security warning: %s", warning)

    job_store = None
    config_path = os.getenv("PROXMOX_MCP_CONFIG")
    if config_path:
        try:
            from proxmox_mcp.config.loader import load_config
            from proxmox_mcp.core.proxmox import ProxmoxManager
            from proxmox_mcp.services import JobStore

            config = load_config(config_path)
            proxmox = ProxmoxManager(
                config.proxmox,
                config.auth,
                api_tunnel_config=config.api_tunnel,
                ssh_config=config.ssh,
            ).get_api()
            job_store = JobStore(proxmox, sqlite_path=config.jobs.sqlite_path)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("JobStore initialization skipped in OpenAPI proxy: %s", exc)

    app = create_app(
        server_command=server_command,
        api_key=args.api_key,
        strict_auth=args.strict_auth,
        cors_allow_origins=_parse_cors_allow_origins(args.cors_allow_origins),
        job_store=job_store,
        path_prefix=args.path_prefix,
        root_path=args.root_path,
        rate_limit_rpm=args.rate_limit_rpm,
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
