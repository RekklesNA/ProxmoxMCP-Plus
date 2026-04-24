from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from proxmox_mcp.services.jobs import JobConflictError, JobStore
from proxmox_mcp.server import ProxmoxMCPServer


@pytest.fixture
def mock_env_vars(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "proxmox": {
            "host": "test.proxmox.com",
            "port": 8006,
            "verify_ssl": True,
            "service": "PVE",
        },
        "auth": {
            "user": "test@pve",
            "token_name": "test_token",
            "token_value": "test_value",
        },
        "logging": {
            "level": "DEBUG",
        },
        "jobs": {
            "sqlite_path": str(tmp_path / "jobs.sqlite3"),
        },
        "command_policy": {
            "mode": "audit_only",
        },
    }))
    with patch.dict(os.environ, {"PROXMOX_MCP_CONFIG": str(config_path)}):
        yield str(config_path)


@pytest.fixture
def mock_proxmox():
    with patch("proxmox_mcp.core.proxmox.ProxmoxAPI") as mock:
        mock.return_value.nodes.get.return_value = [{"node": "node1", "status": "online"}]
        yield mock


@pytest.fixture
def server(mock_env_vars, mock_proxmox):
    return ProxmoxMCPServer(os.environ["PROXMOX_MCP_CONFIG"])


def test_job_store_register_poll_and_progress():
    proxmox = Mock()
    proxmox.nodes.return_value.tasks.return_value.status.get.return_value = {
        "status": "stopped",
        "exitstatus": "OK",
    }
    proxmox.nodes.return_value.tasks.return_value.log.get.return_value = [
        {"t": "starting task"},
        {"t": "download 45%"},
    ]

    store = JobStore(proxmox)
    job = store.register_task(
        tool_name="download_iso",
        summary="Download ISO",
        node="pve",
        upid="UPID:test",
    )
    polled = store.poll_job(job["job_id"])

    assert polled["status"] == "completed"
    assert polled["progress"] == 45
    assert [event["event"] for event in polled["audit_log"]] == ["created", "polled"]


def test_job_store_retry_and_cancel():
    proxmox = Mock()
    cancel = Mock()
    retry = Mock(return_value="UPID:retry")
    store = JobStore(proxmox)
    job = store.register_task(
        tool_name="create_backup",
        summary="Create backup",
        node="pve",
        upid="UPID:original",
        retry_factory=retry,
        cancel_factory=cancel,
    )

    cancelled = store.cancel_job(job["job_id"])
    retried = store.retry_job(job["job_id"])

    cancel.assert_called_once_with("UPID:original")
    retry.assert_called_once()
    assert cancelled["status"] == "cancel_requested"
    assert retried["upid"] == "UPID:retry"
    assert retried["attempts"] == 2
    assert retried["retry_count"] == 1
    assert retried["previous_upids"] == ["UPID:original"]


def test_job_store_persists_to_sqlite(tmp_path: Path):
    proxmox = Mock()
    db_path = tmp_path / "jobs.sqlite3"

    first = JobStore(proxmox, sqlite_path=str(db_path))
    created = first.register_task(
        tool_name="download_iso",
        summary="Download ISO",
        node="pve",
        upid="UPID:persisted",
        metadata={"filename": "test.iso"},
        retry_spec={"kind": "iso.delete", "params": {"node": "pve", "storage": "local", "volid": "local:iso/test.iso"}},
    )

    second = JobStore(proxmox, sqlite_path=str(db_path))
    loaded = second.get_job(created["job_id"])

    assert loaded["job_id"] == created["job_id"]
    assert loaded["metadata"]["filename"] == "test.iso"
    assert loaded["retry_spec"]["kind"] == "iso.delete"


def test_job_store_retry_uses_persisted_retry_spec(tmp_path: Path):
    proxmox = Mock()
    proxmox.nodes.return_value.qemu.return_value.status.start.post.return_value = "UPID:retry-from-sqlite"
    db_path = tmp_path / "jobs.sqlite3"

    first = JobStore(proxmox, sqlite_path=str(db_path))
    created = first.register_task(
        tool_name="start_vm",
        summary="Start VM",
        node="pve",
        upid="UPID:original",
        retry_spec={"kind": "vm.start", "params": {"node": "pve", "vmid": "101"}},
    )

    second = JobStore(proxmox, sqlite_path=str(db_path))
    retried = second.retry_job(created["job_id"])

    assert retried["upid"] == "UPID:retry-from-sqlite"
    assert retried["attempts"] == 2


def test_job_store_retry_raises_conflict_without_recipe(tmp_path: Path):
    proxmox = Mock()
    store = JobStore(proxmox, sqlite_path=str(tmp_path / "jobs.sqlite3"))
    created = store.register_task(
        tool_name="noop",
        summary="No retry",
        node="pve",
        upid="UPID:noop",
    )

    with pytest.raises(JobConflictError):
        store.retry_job(created["job_id"])


@pytest.mark.asyncio
async def test_start_vm_registers_job(server, mock_proxmox):
    mock_proxmox.return_value.nodes.return_value.qemu.return_value.status.current.get.return_value = {
        "status": "stopped"
    }
    mock_proxmox.return_value.nodes.return_value.qemu.return_value.status.start.post.return_value = "UPID:taskid"
    mock_proxmox.return_value.nodes.return_value.tasks.return_value.status.get.return_value = {
        "status": "running"
    }
    mock_proxmox.return_value.nodes.return_value.tasks.return_value.log.get.return_value = []

    response = await server.mcp.call_tool("start_vm", {"node": "node1", "vmid": "100"})
    assert "Job ID:" in response[0].text

    jobs = await server.mcp.call_tool("list_jobs", {})
    jobs_payload = json.loads(jobs[0].text)
    assert len(jobs_payload) == 1
    assert jobs_payload[0]["tool_name"] == "start_vm"

    job_id = jobs_payload[0]["job_id"]
    polled = await server.mcp.call_tool("poll_job", {"job_id": job_id})
    polled_payload = json.loads(polled[0].text)
    assert polled_payload["job_id"] == job_id
    assert polled_payload["status"] == "running"
