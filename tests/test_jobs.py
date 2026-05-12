from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from proxmox_mcp.services.jobs import JobConflictError, JobStore
from proxmox_mcp.server import ProxmoxMCPServer
from proxmox_mcp.tools.containers import ContainerTools


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


def test_job_store_register_poll_and_progress(tmp_path: Path):
    proxmox = Mock()
    proxmox.nodes.return_value.tasks.return_value.status.get.return_value = {
        "status": "stopped",
        "exitstatus": "OK",
    }
    proxmox.nodes.return_value.tasks.return_value.log.get.return_value = [
        {"t": "starting task"},
        {"t": "download 45%"},
    ]

    store = JobStore(proxmox, sqlite_path=str(tmp_path / "jobs.sqlite3"))
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


def test_job_store_retry_and_cancel(tmp_path: Path):
    proxmox = Mock()
    cancel = Mock()
    retry = Mock(return_value="UPID:retry")
    store = JobStore(proxmox, sqlite_path=str(tmp_path / "jobs.sqlite3"))
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


def test_job_store_configures_sqlite_for_concurrency(tmp_path: Path):
    proxmox = Mock()
    db_path = tmp_path / "jobs.sqlite3"

    store = JobStore(proxmox, sqlite_path=str(db_path))

    journal_mode = store._conn.execute("PRAGMA journal_mode").fetchone()[0]
    busy_timeout = store._conn.execute("PRAGMA busy_timeout").fetchone()[0]
    schema_version = store._conn.execute("SELECT version FROM schema_migrations").fetchone()[0]
    indexes = {
        row[1]
        for row in store._conn.execute("PRAGMA index_list('jobs')").fetchall()
    }

    assert journal_mode.lower() == "wal"
    assert busy_timeout == 5000
    assert schema_version == 1
    assert "idx_jobs_status_created_at" in indexes
    assert "idx_jobs_tool_created_at" in indexes


def test_job_store_list_jobs_filters_and_limits_in_sql_order(tmp_path: Path):
    proxmox = Mock()
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(proxmox, sqlite_path=str(db_path))

    first = store.register_task(
        tool_name="start_vm",
        summary="Start first",
        node="pve",
        upid="UPID:first",
    )
    second = store.register_task(
        tool_name="delete_vm",
        summary="Delete second",
        node="pve",
        upid="UPID:second",
    )
    third = store.register_task(
        tool_name="start_vm",
        summary="Start third",
        node="pve",
        upid="UPID:third",
    )

    store._conn.execute(
        "UPDATE jobs SET status = 'failed', created_at = '2024-01-01T00:00:00+00:00' WHERE job_id = ?",
        (first["job_id"],),
    )
    store._conn.execute(
        "UPDATE jobs SET created_at = '2024-01-02T00:00:00+00:00' WHERE job_id = ?",
        (second["job_id"],),
    )
    store._conn.execute(
        "UPDATE jobs SET created_at = '2024-01-03T00:00:00+00:00' WHERE job_id = ?",
        (third["job_id"],),
    )
    store._conn.commit()

    running_start_jobs = store.list_jobs(status="running", tool_name="start_vm", limit=1)

    assert [job["job_id"] for job in running_start_jobs] == [third["job_id"]]


def test_job_store_close_releases_connection(tmp_path: Path):
    proxmox = Mock()
    store = JobStore(proxmox, sqlite_path=str(tmp_path / "jobs.sqlite3"))

    store.close()

    with pytest.raises(sqlite3.ProgrammingError):
        store._conn.execute("SELECT 1")


def test_job_store_refreshes_records_written_by_another_instance(tmp_path: Path):
    proxmox = Mock()
    db_path = tmp_path / "jobs.sqlite3"

    reader = JobStore(proxmox, sqlite_path=str(db_path))
    writer = JobStore(proxmox, sqlite_path=str(db_path))
    created = writer.register_task(
        tool_name="start_vm",
        summary="Start VM",
        node="pve",
        upid="UPID:created-after-reader-started",
        retry_spec={"kind": "vm.start", "params": {"node": "pve", "vmid": "101"}},
    )

    jobs = reader.list_jobs()
    loaded = reader.get_job(created["job_id"])

    assert [job["job_id"] for job in jobs] == [created["job_id"]]
    assert loaded["upid"] == "UPID:created-after-reader-started"


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
    first._conn.execute("UPDATE jobs SET status = 'failed' WHERE job_id = ?", (created["job_id"],))
    first._conn.commit()

    second = JobStore(proxmox, sqlite_path=str(db_path))
    retried = second.retry_job(created["job_id"])

    assert retried["upid"] == "UPID:retry-from-sqlite"
    assert retried["attempts"] == 2


def test_job_store_retry_vm_clone_from_persisted_recipe(tmp_path: Path):
    proxmox = Mock()
    source_vm_api = proxmox.nodes.return_value.qemu.return_value
    source_vm_api.clone.post.return_value = "UPID:clone-retry"
    db_path = tmp_path / "jobs.sqlite3"

    first = JobStore(proxmox, sqlite_path=str(db_path))
    created = first.register_task(
        tool_name="clone_vm",
        summary="Clone VM",
        node="pve",
        upid="UPID:clone-original",
        retry_spec={
            "kind": "vm.clone",
            "params": {
                "node": "pve",
                "source_vmid": "9000",
                "clone_payload": {"newid": 9100, "full": 1, "name": "cloned-vm"},
            },
        },
    )
    first._conn.execute("UPDATE jobs SET status = 'failed' WHERE job_id = ?", (created["job_id"],))
    first._conn.commit()

    second = JobStore(proxmox, sqlite_path=str(db_path))
    retried = second.retry_job(created["job_id"])

    proxmox.nodes.assert_called_with("pve")
    proxmox.nodes.return_value.qemu.assert_called_with("9000")
    source_vm_api.clone.post.assert_called_once_with(newid=9100, full=1, name="cloned-vm")
    assert retried["upid"] == "UPID:clone-retry"
    assert retried["attempts"] == 2


def test_job_store_retry_rejects_running_and_completed_jobs(tmp_path: Path):
    proxmox = Mock()
    retry = Mock(return_value="UPID:retry")
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(proxmox, sqlite_path=str(db_path))
    created = store.register_task(
        tool_name="start_vm",
        summary="Start VM",
        node="pve",
        upid="UPID:original",
        retry_factory=retry,
    )

    with pytest.raises(JobConflictError, match="cannot be retried"):
        store.retry_job(created["job_id"])

    store._conn.execute("UPDATE jobs SET status = 'completed' WHERE job_id = ?", (created["job_id"],))
    store._conn.commit()

    with pytest.raises(JobConflictError, match="cannot be retried"):
        store.retry_job(created["job_id"])

    retry.assert_not_called()


def test_job_store_retry_claim_blocks_concurrent_retry(tmp_path: Path):
    proxmox = Mock()
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(proxmox, sqlite_path=str(db_path))
    retry_started = threading.Event()
    retry_release = threading.Event()
    retry_calls: list[str] = []

    def retry_factory() -> str:
        retry_calls.append("called")
        retry_started.set()
        assert retry_release.wait(5)
        return "UPID:retry"

    created = store.register_task(
        tool_name="delete_vm",
        summary="Delete VM",
        node="pve",
        upid="UPID:original",
        retry_factory=retry_factory,
    )
    store._conn.execute("UPDATE jobs SET status = 'failed' WHERE job_id = ?", (created["job_id"],))
    store._conn.commit()

    result: dict[str, Any] = {}
    errors: list[Exception] = []

    def run_retry() -> None:
        try:
            result["payload"] = store.retry_job(created["job_id"])
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=run_retry)
    thread.start()
    assert retry_started.wait(5)

    with pytest.raises(JobConflictError, match="cannot be retried"):
        store.retry_job(created["job_id"])

    retry_release.set()
    thread.join(5)

    assert not thread.is_alive()
    assert errors == []
    assert retry_calls == ["called"]
    assert result["payload"]["upid"] == "UPID:retry"
    assert result["payload"]["retry_count"] == 1


def test_job_store_poll_discards_stale_upid_after_retry(tmp_path: Path):
    proxmox = Mock()
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(proxmox, sqlite_path=str(db_path))
    retry = Mock(return_value="UPID:new")
    created = store.register_task(
        tool_name="start_vm",
        summary="Start VM",
        node="pve",
        upid="UPID:old",
        retry_factory=retry,
    )
    store._conn.execute("UPDATE jobs SET status = 'failed' WHERE job_id = ?", (created["job_id"],))
    store._conn.commit()

    def retry_during_poll():
        store.retry_job(created["job_id"])
        return {"status": "stopped", "exitstatus": "OK"}

    proxmox.nodes.return_value.tasks.return_value.status.get.side_effect = retry_during_poll
    proxmox.nodes.return_value.tasks.return_value.log.get.return_value = [{"t": "100%"}]

    polled = store.poll_job(created["job_id"])

    assert polled["upid"] == "UPID:new"
    assert polled["status"] == "running"
    assert polled["progress"] == 0
    assert [event["event"] for event in polled["audit_log"]][-2:] == ["retried", "poll_discarded"]


def test_job_store_cancel_discards_stale_upid(tmp_path: Path):
    proxmox = Mock()
    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(proxmox, sqlite_path=str(db_path))

    created = store.register_task(
        tool_name="start_vm",
        summary="Start VM",
        node="pve",
        upid="UPID:old",
    )

    def cancel_factory(upid: str) -> None:
        assert upid == "UPID:old"
        store._conn.execute(
            "UPDATE jobs SET upid = ?, status = ? WHERE job_id = ?",
            ("UPID:new", "running", created["job_id"]),
        )
        store._conn.commit()

    with store._lock:
        record = store._load_record_from_db(created["job_id"])
        record.cancel_factory = cancel_factory
        store._jobs[record.job_id] = record

    cancelled = store.cancel_job(created["job_id"])

    assert cancelled["upid"] == "UPID:new"
    assert cancelled["status"] == "running"
    assert cancelled["audit_log"][-1]["event"] == "cancel_discarded"


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


def test_create_container_does_not_persist_secret_retry_spec(tmp_path: Path):
    proxmox = Mock()
    proxmox.nodes.get.return_value = [{"node": "node1", "status": "online"}]
    proxmox.nodes.return_value.lxc.get.return_value = []
    proxmox.storage.get.return_value = [{"storage": "local-lvm", "content": "rootdir"}]
    proxmox.nodes.return_value.lxc.create.return_value = "UPID:ct-create-secret"

    db_path = tmp_path / "jobs.sqlite3"
    store = JobStore(proxmox, sqlite_path=str(db_path))
    tools = ContainerTools(proxmox, job_store=store)

    tools.create_container(
        node="node1",
        vmid="200",
        ostemplate="local:vztmpl/alpine.tar.xz",
        password="super-secret",
        ssh_public_keys="ssh-ed25519 AAAA-secret-key",
    )

    persisted = sqlite3.connect(db_path).execute("SELECT retry_spec_json FROM jobs").fetchone()[0]
    job = store.list_jobs()[0]

    assert persisted is None
    assert job["retry_spec"] is None
    proxmox.nodes.return_value.lxc.create.assert_called_once()
    create_kwargs = proxmox.nodes.return_value.lxc.create.call_args.kwargs
    assert create_kwargs["password"] == "super-secret"
    assert create_kwargs["ssh-public-keys"] == "ssh-ed25519 AAAA-secret-key"


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
