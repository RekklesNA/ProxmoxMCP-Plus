"""Tests for OpenAPI proxy wrapper."""

import asyncio
from fastapi.testclient import TestClient

from proxmox_mcp.openapi_proxy import create_app
from proxmox_mcp.services.jobs import JobConflictError, JobNotFoundError


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
    assert "/metrics" in paths


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
    assert payload["metrics"] == "/metrics"
    assert payload["jobs"] == "/jobs"


def test_health_endpoint_includes_auth_and_rate_limit_details():
    app = create_app(
        server_command=["python", "-c", "print('ok')"],
        api_key="secret",
        strict_auth=True,
        cors_allow_origins=["*"],
        rate_limit_rpm=42,
    )
    endpoint = _get_route_endpoint(app, "/health")
    response = asyncio.run(endpoint())
    payload = response.body.decode("utf-8")

    assert '"api_key_configured":true' in payload
    assert '"strict_auth":true' in payload
    assert '"requests_per_minute":42' in payload
    assert '"enabled":false' in payload


def test_health_endpoint_reports_security_warnings_for_unsafe_defaults():
    app = create_app(
        server_command=["python", "-c", "print('ok')"],
        api_key=None,
        strict_auth=False,
        cors_allow_origins=["*"],
    )
    endpoint = _get_route_endpoint(app, "/health")
    response = asyncio.run(endpoint())
    payload = response.body.decode("utf-8")

    assert "OpenAPI proxy is running without PROXMOX_API_KEY" in payload
    assert "CORS allows all origins" in payload


def test_metrics_endpoint_renders_labeled_series():
    app = create_app(
        server_command=["python", "-c", "print('ok')"],
        api_key=None,
        strict_auth=False,
        cors_allow_origins=["*"],
    )
    app.state.http_metrics.observe("/health", "GET", 200, 12.5)
    endpoint = _get_route_endpoint(app, "/metrics")
    response = asyncio.run(endpoint())
    body = response.body.decode("utf-8")

    assert 'route="/health"' in body
    assert 'method="GET"' in body
    assert 'status="200"' in body


class _FakeJobStore:
    def list_jobs(self, **kwargs):
        return [{"job_id": "job-1", "status": kwargs.get("status") or "running"}]

    def get_job(self, job_id: str):
        if job_id == "missing":
            raise JobNotFoundError("missing")
        return {"job_id": job_id, "status": "running"}

    def poll_job(self, job_id: str):
        return {"job_id": job_id, "status": "completed"}

    def cancel_job(self, job_id: str):
        if job_id == "bad":
            raise JobConflictError("cannot cancel")
        return {"job_id": job_id, "status": "cancel_requested"}

    def retry_job(self, job_id: str):
        return {"job_id": job_id, "status": "running", "attempts": 2}


def test_jobs_routes_return_expected_status_codes():
    app = create_app(
        server_command=["python", "-c", "print('ok')"],
        api_key=None,
        strict_auth=False,
        cors_allow_origins=["*"],
        job_store=_FakeJobStore(),
    )
    client = TestClient(app)

    list_response = client.get("/jobs", params={"status": "running"})
    assert list_response.status_code == 200
    assert list_response.json()[0]["job_id"] == "job-1"

    get_response = client.get("/jobs/job-1")
    assert get_response.status_code == 200
    assert get_response.json()["job_id"] == "job-1"

    missing_response = client.get("/jobs/missing")
    assert missing_response.status_code == 404
    assert missing_response.json()["message"] == "Job was not found"

    poll_response = client.post("/jobs/job-1/poll")
    assert poll_response.status_code == 200
    assert poll_response.json()["status"] == "completed"

    cancel_response = client.post("/jobs/job-1/cancel")
    assert cancel_response.status_code == 202
    assert cancel_response.json()["status"] == "cancel_requested"

    conflict_response = client.post("/jobs/bad/cancel")
    assert conflict_response.status_code == 409
    assert conflict_response.json()["message"] == "Job cannot perform that operation right now"

    retry_response = client.post("/jobs/job-1/retry")
    assert retry_response.status_code == 202
    assert retry_response.json()["attempts"] == 2


def test_jobs_routes_hide_internal_error_details():
    class _BrokenJobStore:
        def list_jobs(self, **kwargs):
            raise ValueError("sensitive backend detail")

    app = create_app(
        server_command=["python", "-c", "print('ok')"],
        api_key=None,
        strict_auth=False,
        cors_allow_origins=["*"],
        job_store=_BrokenJobStore(),
    )
    client = TestClient(app)

    response = client.get("/jobs")

    assert response.status_code == 400
    assert response.json()["message"] == "Job request failed"
