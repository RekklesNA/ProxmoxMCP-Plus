"""Verify lazy audit loading and request-specific Code Mode discovery."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from proxmox_mcp.server import ProxmoxMCPServer
from proxmox_mcp.services.jobs import JobStore


def test_summary_startup_preserves_history_and_later_poll_events(tmp_path):
    from unittest.mock import MagicMock
    import sqlite3

    api = MagicMock()
    api.nodes.return_value.tasks.return_value.status.get.return_value = {"status": "stopped", "exitstatus": "OK"}
    api.nodes.return_value.tasks.return_value.log.get.return_value = []
    database = tmp_path / "jobs.sqlite3"
    with JobStore(api, str(database)) as store:
        job = store.register_task(tool_name="start_vm", summary="Start", node="pve", upid="UPID:pve:old")
        store.poll_job(job["job_id"])
        history = store.get_audit(job["job_id"])
    queries = []
    connect = sqlite3.connect

    def traced_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connection.set_trace_callback(queries.append)
        return connection

    with patch("proxmox_mcp.services.jobs.sqlite3.connect", side_effect=traced_connect):
        with JobStore(api, str(database)) as reopened:
            assert not any("FROM job_audit_events" in query for query in queries)
            assert reopened._jobs[job["job_id"]].audit_log == []
            assert reopened.get_job(job["job_id"])["audit_log"] == [
                {key: value for key, value in event.items() if key != "id"} for event in history
            ]
            reopened.poll_job(job["job_id"], include_audit=False)
            page = reopened.get_audit(job["job_id"])
            assert [item["event"] for item in page] == ["created", "polled", "polled"]
            assert len({item["id"] for item in page}) == 3


@pytest.mark.asyncio
async def test_code_discovery_changes_per_client_without_cross_request_cache(tmp_path):
    target = {"host": "example.invalid", "auth": {"user": "user", "token_name": "token", "token_value": "value"}}
    config = {
        "targets": {"a": target, "b": target},
        "jobs": {"sqlite_path": str(tmp_path / "jobs.sqlite3")},
        "mcp": {"transport": "STDIO", "code_mode": True, "client_permissions": {
            "reader": {"tools": ["get_nodes", "list_targets"], "targets": ["a"]},
            "operator": {"tools": ["get_vms"], "targets": ["b"]},
            "empty": {"tools": ["get_nodes", "list_targets"], "targets": []},
            "wildcard": {"tools": ["*"], "targets": ["*"]},
        }},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with patch("proxmox_mcp.core.proxmox.ProxmoxAPI"):
        server = ProxmoxMCPServer(str(path))
    try:
        mode = server.code_mode
        for principal, expected in [("reader", {"get_nodes", "list_targets"}),
                                    ("operator", {"get_vms"}), ("unknown", set()),
                                    ("empty", {"list_targets"}), ("reader", {"get_nodes", "list_targets"})]:
            with patch("proxmox_mcp.security.access.get_access_token", return_value=SimpleNamespace(client_id=principal)):
                assert set(mode._runtime_tools()) == expected
                result = await server.mcp.call_tool("proxmox_code_get_schema", {"names": ["delete_vm"]})
                assert "Unknown or unavailable" in str(result)
                result = await server.mcp.call_tool("proxmox_code_search", {"query": ""})
                assert "delete_vm" not in str(result)
        with patch("proxmox_mcp.security.access.get_access_token", return_value=SimpleNamespace(client_id="wildcard")):
            assert set(mode._runtime_tools()) == set(mode.domain_tools)
        with patch("proxmox_mcp.security.access.get_access_token", return_value=SimpleNamespace(client_id="reader")):
            result = await server.mcp.call_tool("proxmox_code_get_schema", {"names": ["get_nodes"]})
            assert "target" in str(result)
            assert not (await mode.execute('await call_tool("delete_vm", {})'))["success"]
    finally:
        server.close()
