"""Tests for native MCP Streamable HTTP Bearer authentication."""

import asyncio
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from proxmox_mcp.mcp_http_auth import MCPBearerAuthMiddleware


async def _ok(request):
    return JSONResponse({"status": "ok"})


def _client(api_key: str = "correct-secret") -> TestClient:
    app = Starlette(routes=[Route("/mcp", endpoint=_ok, methods=["POST"])])
    return TestClient(MCPBearerAuthMiddleware(app, api_key=api_key))


@pytest.mark.parametrize("api_key", ["", " ", "leading-space ", "non-ascii-密钥"])
def test_api_key_must_be_visible_ascii_without_whitespace(api_key):
    with pytest.raises(ValueError, match="non-empty ASCII without whitespace"):
        MCPBearerAuthMiddleware(Starlette(), api_key=api_key)


def test_missing_authorization_is_rejected_with_bearer_challenge():
    with _client() as client:
        response = client.post("/mcp")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_wrong_bearer_token_is_rejected_with_constant_time_comparison():
    with patch(
        "proxmox_mcp.mcp_http_auth.hmac.compare_digest",
        return_value=False,
    ) as compare_digest:
        with _client() as client:
            response = client.post(
                "/mcp",
                headers={"Authorization": "Bearer wrong-secret"},
            )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    compare_digest.assert_called_once_with(b"wrong-secret", b"correct-secret")


def test_non_bearer_authorization_is_rejected():
    with _client() as client:
        response = client.post(
            "/mcp",
            headers={"Authorization": "Basic YW55OnNlY3JldA=="},
        )

    assert response.status_code == 401


def test_matching_bearer_token_is_accepted_case_insensitively():
    with _client() as client:
        response = client.post(
            "/mcp",
            headers={"Authorization": "bearer correct-secret"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_matching_bearer_reaches_native_streamable_http_initialize():
    mcp = FastMCP("auth-test", json_response=True, stateless_http=True)
    app = MCPBearerAuthMiddleware(mcp.streamable_http_app(), api_key="secret")
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "1"},
        },
    }

    with TestClient(app, base_url="http://localhost:8000") as client:
        response = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer secret",
                "Accept": "application/json, text/event-stream",
            },
            json=payload,
        )

    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == "auth-test"


def test_successful_streaming_response_events_are_forwarded_unchanged():
    expected_events = [
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/event-stream")],
        },
        {
            "type": "http.response.body",
            "body": b"event: message\ndata: one\n\n",
            "more_body": True,
        },
        {
            "type": "http.response.body",
            "body": b"event: message\ndata: two\n\n",
            "more_body": False,
        },
    ]

    async def streaming_app(scope, receive, send):
        for event in expected_events:
            await send(event)

    middleware = MCPBearerAuthMiddleware(streaming_app, api_key="secret")
    actual_events = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(event):
        actual_events.append(event)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(b"authorization", b"Bearer secret")],
    }
    asyncio.run(middleware(scope, receive, send))

    assert actual_events == expected_events


def test_lifespan_scope_passes_through_to_wrapped_app():
    seen_scopes = []

    async def app(scope, receive, send):
        seen_scopes.append(scope["type"])

    middleware = MCPBearerAuthMiddleware(app, api_key="secret")

    async def receive():
        return {"type": "lifespan.shutdown"}

    async def send(event):
        return None

    asyncio.run(middleware({"type": "lifespan"}, receive, send))

    assert seen_scopes == ["lifespan"]
