"""OpenAPI proxy launcher with explicit root and health routes."""

import argparse
import logging
import os
from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from mcpo.main import lifespan
from mcpo.utils.auth import APIKeyMiddleware, get_verify_api_key

LOGGER = logging.getLogger(__name__)


def _parse_cors_allow_origins(value: Optional[str]) -> list[str]:
    if not value:
        return ["*"]
    return [item.strip() for item in value.split(",") if item.strip()]


def create_app(
    server_command: list[str],
    *,
    api_key: Optional[str],
    strict_auth: bool,
    cors_allow_origins: list[str],
    name: str = "MCP OpenAPI Proxy",
    description: str = "Automatically generated API from MCP Tool Schemas",
    version: str = "1.0",
    path_prefix: str = "/",
    root_path: str = "",
) -> FastAPI:
    """Create a FastAPI app that mirrors mcpo behavior and adds health routes."""
    api_dependency = get_verify_api_key(api_key) if api_key else None

    app = FastAPI(
        title=name,
        description=description,
        version=version,
        root_path=root_path,
        lifespan=lifespan,
    )

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

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "name": name,
            "status": "ok",
            "docs": "/docs",
            "openapi": "/openapi.json",
            "health": "/health",
        }

    @app.get("/health", include_in_schema=False)
    async def health() -> JSONResponse:
        is_connected = bool(getattr(app.state, "is_connected", False))
        status_code = 200 if is_connected else 503
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "ok" if is_connected else "degraded",
                "connected_to_mcp": is_connected,
            },
        )

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

    app = create_app(
        server_command=server_command,
        api_key=args.api_key,
        strict_auth=args.strict_auth,
        cors_allow_origins=_parse_cors_allow_origins(args.cors_allow_origins),
        path_prefix=args.path_prefix,
        root_path=args.root_path,
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
