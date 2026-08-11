"""Authentication helpers for the native MCP Streamable HTTP transport."""

from __future__ import annotations

import hmac

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class MCPBearerAuthMiddleware:
    """Require one configured Bearer token without buffering HTTP responses."""

    def __init__(self, app: ASGIApp, *, api_key: str) -> None:
        if not api_key or not api_key.isascii() or any(char.isspace() for char in api_key):
            raise ValueError("MCP_API_KEY must be non-empty ASCII without whitespace")
        self.app = app
        self._expected_key = api_key.encode("utf-8")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        authorization = Headers(scope=scope).get("authorization")
        authenticated = False
        if authorization:
            scheme, separator, credentials = authorization.partition(" ")
            if separator and scheme.lower() == "bearer":
                authenticated = hmac.compare_digest(
                    credentials.encode("utf-8"),
                    self._expected_key,
                )

        if not authenticated:
            response = JSONResponse(
                {"detail": "Unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        # Pass the ASGI exchange through directly. In particular, do not wrap
        # ``send`` or collect response body events: Streamable HTTP may return
        # text/event-stream and every chunk must reach the client immediately.
        await self.app(scope, receive, send)
