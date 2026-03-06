"""Tests for OpenAPI proxy wrapper."""

import asyncio

from proxmox_mcp.openapi_proxy import create_app


def _get_route_endpoint(app, path: str):
    for route in app.router.routes:
        if getattr(route, "path", None) == path:
            return route.endpoint
    raise AssertionError(f"Route not found: {path}")


def test_create_app_registers_health_and_root_routes():
    app = create_app(
        server_command=["python", "-c", "print('ok')"],
        api_key=None,
        strict_auth=False,
        cors_allow_origins=["*"],
    )
    paths = {getattr(route, "path", "") for route in app.router.routes}

    assert "/" in paths
    assert "/health" in paths


def test_health_endpoint_reports_degraded_when_not_connected():
    app = create_app(
        server_command=["python", "-c", "print('ok')"],
        api_key=None,
        strict_auth=False,
        cors_allow_origins=["*"],
    )
    endpoint = _get_route_endpoint(app, "/health")
    response = asyncio.run(endpoint())

    assert response.status_code == 503
    assert b'"status":"degraded"' in response.body


def test_root_endpoint_returns_service_links():
    app = create_app(
        server_command=["python", "-c", "print('ok')"],
        api_key=None,
        strict_auth=False,
        cors_allow_origins=["*"],
    )
    endpoint = _get_route_endpoint(app, "/")
    payload = asyncio.run(endpoint())

    assert payload["docs"] == "/docs"
    assert payload["openapi"] == "/openapi.json"
    assert payload["health"] == "/health"
