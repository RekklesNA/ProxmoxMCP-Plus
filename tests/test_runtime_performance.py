"""Concurrent polling, bounded admission, session ownership and tail metrics."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch
import asyncio
import json
import math

import pytest
from requests import Response

from proxmox_mcp.config.models import AuthConfig, ProxmoxConfig, MCPConfig, JobsConfig, Config
from proxmox_mcp.config.loader import load_config
from proxmox_mcp.core.proxmox import ProxmoxManager
from proxmox_mcp.core.session_pool import SessionPool
from proxmox_mcp.core.targets import TargetRegistry
from proxmox_mcp.observability.metrics import ToolMetrics, HttpRequestMetrics, LabeledMetricSeries
from proxmox_mcp.services.dispatch import DispatchGate
from proxmox_mcp.services.jobs import JobStore, JobConflictError, JobNotFoundError
from proxmox_mcp.services.job_polling import PollCoordinator
from proxmox_mcp.server import ProxmoxMCPServer

AUTH = AuthConfig(user="root@pam", token_name="test", token_value="fixture")


def new_job(store):
    return store.register_task(tool_name="start_vm", summary="Start test VM", node="pve", upid="UPID:pve:old",
                               retry_factory=lambda: "UPID:pve:new")["job_id"]


def task_api(status="running", exitstatus=""):
    api = Mock()
    api.nodes.return_value.tasks.return_value.status.get.return_value = {"status": status, "exitstatus": exitstatus}
    api.nodes.return_value.tasks.return_value.log.get.return_value = [{"t": "Progress 50%"}]
    return api


def test_polling_coalesces_concurrent_requests_and_preserves_audit_pages(tmp_path):
    api = task_api()
    with JobStore(api, str(tmp_path / "jobs.db"), poll_cache_ttl=60) as store:
        job_id = new_job(store)
        entered, finish = Event(), Event()
        def slow_status():
            entered.set()
            assert finish.wait(5)
            return {"status": "running"}
        api.nodes.return_value.tasks.return_value.status.get.side_effect = slow_status
        with ThreadPoolExecutor(max_workers=8) as executor:
            first = executor.submit(store.poll_job, job_id, include_audit=False)
            assert entered.wait(5)
            rest = [executor.submit(store.poll_job, job_id) for _ in range(7)]
            finish.set()
            assert [e["event"] for e in first.result()["audit_log"]] == ["polled"]
            assert all(len(f.result()["audit_log"]) == 2 for f in rest)
        assert api.nodes.return_value.tasks.return_value.status.get.call_count == 1
        assert api.nodes.return_value.tasks.return_value.log.get.call_count == 1
        assert [e["event"] for e in store.get_audit(job_id)] == ["created", "polled"]


def test_poll_cache_expiry_force_and_terminal_restart(tmp_path):
    api = task_api()
    path = str(tmp_path / "jobs.db")
    with JobStore(api, path, poll_cache_ttl=1) as store:
        job_id = new_job(store)
        with patch("proxmox_mcp.services.job_polling.time.monotonic", return_value=10):
            store.poll_job(job_id)
        with patch("proxmox_mcp.services.job_polling.time.monotonic", return_value=12):
            store.poll_job(job_id)
            api.nodes.return_value.tasks.return_value.status.get.return_value = {"status": "stopped", "exitstatus": "OK"}
            assert store.poll_job(job_id, force=True)["status"] == "completed"
        store.poll_job(job_id)
        assert api.nodes.return_value.tasks.return_value.status.get.call_count == 3
    with JobStore(api, path) as restored:
        assert restored.poll_job(job_id)["status"] == "completed"
        assert api.nodes.return_value.tasks.return_value.status.get.call_count == 3
        restored.poll_job(job_id, force=True)
        assert api.nodes.return_value.tasks.return_value.status.get.call_count == 4


def test_cancel_retry_and_cross_store_updates_invalidate_poll_freshness(tmp_path):
    api = task_api()
    path = str(tmp_path / "jobs.db")
    with JobStore(api, path, poll_cache_ttl=60) as first, JobStore(api, path) as second:
        job_id = new_job(first)
        first.poll_job(job_id)
        second.cancel_job(job_id)
        assert first.poll_job(job_id)["status"] == "cancel_requested"
        with pytest.raises(JobConflictError):
            first.retry_job(job_id)
        api.nodes.return_value.tasks.return_value.status.get.return_value = {"status": "stopped"}
        assert first.poll_job(job_id, force=True)["status"] == "cancelled"
        first.retry_job(job_id)
        api.nodes.return_value.tasks.return_value.status.get.return_value = {"status": "running"}
        assert first.poll_job(job_id)["upid"] == "UPID:pve:new"
        assert api.nodes.return_value.tasks.return_value.status.get.call_count == 4


def test_poll_failures_are_not_cached_and_other_jobs_can_progress(tmp_path):
    api = task_api()
    with JobStore(api, str(tmp_path / "jobs.db"), poll_cache_ttl=60) as store:
        job_id = new_job(store)
        api.nodes.return_value.tasks.return_value.status.get.side_effect = ConnectionError("Disconnected")
        with pytest.raises(ConnectionError):
            store.poll_job(job_id)
        assert len(store.get_audit(job_id)) == 1
        api.nodes.return_value.tasks.return_value.status.get.side_effect = None
        assert store.poll_job(job_id)["status"] == "running"
        with JobStore(api, store.sqlite_path, target_name="other") as isolated:
            with pytest.raises(JobNotFoundError):
                isolated.poll_job(job_id)
    with pytest.raises(ValueError, match="poll_cache_ttl"):
        JobStore(api, ":memory:", poll_cache_ttl=-1)


@pytest.mark.parametrize("same_timestamp", [False, True])
def test_delayed_poll_cannot_reopen_a_task_completed_by_another_store(tmp_path, same_timestamp):
    api = task_api()
    completed_api = task_api("stopped", "OK")
    path = str(tmp_path / "jobs.db")
    with ExitStack() as stack:
        if same_timestamp:
            stack.enter_context(patch("proxmox_mcp.services.job_models._utcnow", return_value="2026-10-10T00:00:00+00:00"))
            stack.enter_context(patch("proxmox_mcp.services.jobs._utcnow", return_value="2026-10-10T00:00:00+00:00"))
        first = stack.enter_context(JobStore(api, path))
        second = stack.enter_context(JobStore(completed_api, path))
        job_id = new_job(first)
        def delayed_status():
            assert second.poll_job(job_id)["status"] == "completed"
            return {"status": "running"}
        api.nodes.return_value.tasks.return_value.status.get.side_effect = delayed_status
        assert first.poll_job(job_id)["status"] == "completed"
        assert [item["event"] for item in first.get_audit(job_id)] == ["created", "polled", "poll_discarded"]


def test_poll_coordinator_is_bounded_and_fingerprint_sensitive():
    cache = PollCoordinator(60)
    for i in range(501):
        record = SimpleNamespace(job_id=str(i), upid="u", node="n", status="running", updated_at="now", attempts=1)
        cache.remember(record)
    assert len(cache._fresh) == 500
    assert "0" not in cache._fresh
    assert cache.fresh(record)
    record.upid = "next"
    assert not cache.fresh(record)
    cache.invalidate(record.job_id)
    assert not cache.fresh(record)


def test_named_retention_and_legacy_failed_job_without_upid(tmp_path):
    api = task_api()
    path = str(tmp_path / "jobs.db")
    with JobStore(api, path, target_name="a", audit_retention_days=1) as store:
        job_id = new_job(store)
        store._conn.execute("UPDATE job_audit_events SET timestamp='2000-01-01T00:00:00+00:00' WHERE job_id=?", (job_id,))
        store._conn.commit()
        store.prune_audit_events()
        assert not store.get_audit(job_id)
        store._conn.execute("UPDATE jobs SET status='failed', upid=NULL WHERE job_id=?", (job_id,))
        store._conn.commit()
        retried = store.retry_job(job_id)
        assert retried["previous_upids"] == []
        assert retried["upid"] == "UPID:pve:new"
@pytest.mark.asyncio
async def test_dispatch_rejects_overflow_times_out_and_releases_cancelled_waiters():
    gate = DispatchGate(1, 1, 0.02)
    metrics = ToolMetrics()
    entered, finish = asyncio.Event(), asyncio.Event()
    async def hold():
        async with gate.acquire(metrics, "a"):
            entered.set()
            await finish.wait()
    first = asyncio.create_task(hold())
    await entered.wait()
    waiter = asyncio.create_task(hold())
    while not gate._waiting:
        await asyncio.sleep(0)
    with pytest.raises(RuntimeError, match="full"):
        async with gate.acquire(metrics, "a"):
            pytest.fail("Rejected dispatch executed")
    with pytest.raises(RuntimeError, match="timed out"):
        await waiter
    cancelled = asyncio.create_task(hold())
    while not gate._waiting:
        await asyncio.sleep(0)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    assert gate._waiting == 0
    finish.set()
    await first
    async with gate.acquire(metrics, "a"):
        pass
    assert metrics.snapshot()["dispatch_queue"]["error"]["a"]["calls"] == 3
    assert gate._limiter.borrowed_tokens == 0


@pytest.mark.asyncio
async def test_dispatch_waiter_succeeds_and_execution_failure_releases_slot():
    gate = DispatchGate(1, 1, 3)
    metrics = ToolMetrics()
    async def waiting():
        async with gate.acquire(metrics, "a"):
            return "executed"
    async with gate.acquire(metrics, "a"):
        task = asyncio.create_task(waiting())
        while not gate._waiting:
            await asyncio.sleep(0)
    assert await task == "executed"
    with pytest.raises(ValueError):
        async with gate.acquire(metrics, "a"):
            raise ValueError("Tool failed")
    assert gate._limiter.borrowed_tokens == 0
    async with DispatchGate(1, 0, 1).acquire(metrics, "b"):
        pass


def test_session_pool_exclusive_leases_timeout_failure_and_close():
    entered, finish = Event(), Event()
    session = Mock()
    def request(*args, **kwargs):
        entered.set()
        assert finish.wait(5)
        return SimpleNamespace(status_code=200)
    session.request.side_effect = request
    observe = Mock()
    pool = SessionPool([session], 0.02, Mock(), observe)
    with ThreadPoolExecutor(max_workers=3) as executor:
        active = executor.submit(pool.request, "GET", "/version")
        assert entered.wait(5)
        with pytest.raises(TimeoutError):
            pool.request("GET", "/version")
        closing = executor.submit(pool.close)
        with pool._condition:
            assert pool._condition.wait_for(lambda: pool._closed, timeout=5)
        with pytest.raises(RuntimeError, match="closed"):
            pool.request("GET", "/version")
        assert not closing.done()
        session.close.assert_not_called()
        finish.set()
        assert active.result().status_code == 200
        closing.result()
    pool.close()
    session.close.assert_called_once()
    assert any(c.args[0] == "api_queue" and c.args[2] is False for c in observe.call_args_list)


def test_pool_error_returns_lease_and_closes_every_session():
    first, second = Mock(), Mock()
    second.request.side_effect = ConnectionError("Disconnected")
    pool = SessionPool([first, second], 1, Mock(), Mock())
    with pytest.raises(ConnectionError):
        pool.request("POST", "/nodes/pve/qemu")
    assert pool._active == 0
    assert second.request.call_count == 1  # Never replay an uncertain mutation.
    second.request.side_effect = None
    second.request.return_value = SimpleNamespace(status_code=503)
    assert pool.request("GET", "/version").status_code == 503
    second.close.side_effect = OSError("Close failed")
    with pytest.raises(OSError):
        pool.close()
    first.close.assert_called_once()
    assert not pool._available


def test_real_proxmoxer_sessions_have_independent_auth_and_shutdown():
    metrics = ToolMetrics()
    manager = ProxmoxManager(ProxmoxConfig(host="pve.invalid", session_pool_size=3), AUTH, metrics=metrics, target_name="a")
    sessions = list(manager._sessions)
    assert len({id(s) for s in sessions}) == 3
    assert len({id(s.auth) for s in sessions}) == 3
    def response(*args, **kwargs):
        result = Response()
        result.status_code = 200
        result._content = b'{"data":{"version":"test"}}'
        return result
    for session in sessions:
        session.request = Mock(side_effect=response)
    assert manager.get_api().version.get() == {"version": "test"}
    assert metrics.snapshot()["api_request"]["success"]["a"]["calls"] == 1
    manager.close()
    with pytest.raises(RuntimeError):
        manager.get_api().version.get()


def test_manager_partial_pool_startup_failure_cleans_up():
    session = Mock()
    with patch("proxmox_mcp.core.proxmox.ProxmoxAPI", side_effect=[SimpleNamespace(_store={"session": session}), RuntimeError("setup failed")]):
        with pytest.raises(RuntimeError):
            ProxmoxManager(ProxmoxConfig(host="pve.invalid", session_pool_size=2), AUTH)
    session.close.assert_called_once()


def test_manager_serial_request_error_closed_state_and_close_failure():
    session = Mock()
    session.request.side_effect = ConnectionError("Disconnected")
    with patch("proxmox_mcp.core.proxmox.ProxmoxAPI", return_value=SimpleNamespace(_store={"session": session})):
        manager = ProxmoxManager(ProxmoxConfig(host="pve.invalid"), AUTH, metrics=ToolMetrics())
    with pytest.raises(ConnectionError):
        session.request("GET", "/version")
    session.close.side_effect = OSError("Close failed")
    manager.tunnel_manager = Mock()
    with pytest.raises(OSError):
        manager.close()
    manager.tunnel_manager.close.assert_called_once()
    with pytest.raises(RuntimeError, match="closed"):
        session.request("GET", "/version")
    manager.close()


def test_histograms_are_cumulative_bounded_and_thread_safe():
    metrics = ToolMetrics()
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: metrics.observe("probe", 50, True), range(1000)))
    payload = metrics.snapshot()["probe"]["success"]["default"]
    assert payload["calls"] == 1000
    assert 25 < payload["latency_ms_p95"] <= 50
    assert payload["latency_ms_p99"] >= payload["latency_ms_p95"]
    text = metrics.render_prometheus()
    assert 'latency_seconds_bucket{tool="probe",status="success",target="default",le="0.05"} 1000' in text
    assert 'le="+Inf"} 1000' in text
    assert 'latency_seconds_count{tool="probe",status="success",target="default"} 1000' in text
    assert ToolMetrics._escape_label('a\nb"\\') == 'a\\nb\\"\\\\'
    http = HttpRequestMetrics()
    http.observe("/probe", "GET", 200, 100)
    assert http.snapshot()["requests"][0]["latency_ms_p95"] is not None
    assert "# TYPE proxmox_mcp_http_latency_seconds histogram" in http.render_prometheus()
    empty = LabeledMetricSeries()
    assert empty.quantile(.95) is None
    for value in (math.nan, math.inf, -1):
        with pytest.raises(ValueError):
            empty.observe(value)
    empty.observe(1000000)
    assert empty.quantile(.99) is None
    assert empty.quantile(2) is None


@pytest.mark.parametrize("model, field, value", [
    (MCPConfig, "queue_limit", -1), (MCPConfig, "queue_timeout", 0),
    (MCPConfig, "queue_timeout", math.inf), (JobsConfig, "poll_cache_ttl", math.nan),
    (JobsConfig, "poll_cache_ttl", 61), (ProxmoxConfig, "session_pool_size", 0),
])
def test_runtime_configuration_rejects_invalid_limits(model, field, value):
    with pytest.raises(ValueError):
        model.model_validate({"host": "pve.invalid", field: value})


def test_runtime_limits_environment_and_target_propagation(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"proxmox": {"host": "pve.invalid"}, "auth": AUTH.model_dump()}))
    monkeypatch.setenv("MCP_WORKER_LIMIT", "2")
    monkeypatch.setenv("MCP_QUEUE_LIMIT", "3")
    monkeypatch.setenv("MCP_QUEUE_TIMEOUT", "4.5")
    monkeypatch.setenv("PROXMOX_JOBS_POLL_CACHE_TTL", "2.5")
    config = load_config(str(path))
    assert (config.mcp.worker_limit, config.mcp.queue_limit, config.mcp.queue_timeout) == (2, 3, 4.5)
    assert config.jobs.poll_cache_ttl == 2.5
    named = Config.model_validate({"targets": {"a": {"host": "pve.invalid", "auth": AUTH.model_dump(), "session_pool_size": 4, "session_pool_timeout": 5}}})
    assert TargetRegistry(named).resolve("a").config.session_pool_size == 4
    assert TargetRegistry(named).resolve("a").config.session_pool_timeout == 5


@pytest.mark.asyncio
async def test_force_poll_public_mcp_schema_and_dispatch(tmp_path):
    config = Config(proxmox=ProxmoxConfig(host="pve.invalid"), auth=AUTH, jobs=JobsConfig(sqlite_path=str(tmp_path / "jobs.db")))
    with patch("proxmox_mcp.server.load_config", return_value=config), patch("proxmox_mcp.core.proxmox.ProxmoxAPI", return_value=task_api()):
        server = ProxmoxMCPServer()
    try:
        job_id = new_job(server.job_store)
        result = await server.mcp.call_tool("poll_job", {"job_id": job_id, "force": True, "include_audit": False})
        assert json.loads(result[0].text)["status"] == "running"
        schema = next(t.inputSchema for t in await server.mcp.list_tools() if t.name == "poll_job")
        assert "force" in schema["properties"]
    finally:
        server.close()
