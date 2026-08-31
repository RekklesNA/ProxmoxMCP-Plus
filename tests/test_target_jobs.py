from proxmox_mcp.services.jobs import JobStore


import pytest


def test_job_store_persists_target_name(tmp_path):
    store = JobStore(object(), sqlite_path=str(tmp_path / "jobs.sqlite3"), target_name="pl")
    try:
        job = store.register_task(
            tool_name="create_vm", summary="create", node="pve", upid="UPID:1"
        )
        assert job["metadata"]["target"] == "pl"
    finally:
        store.close()


def test_named_job_stores_cannot_cross_target_access(tmp_path):
    path = str(tmp_path / "shared.sqlite3")
    one = JobStore(object(), sqlite_path=path, target_name="one")
    two = JobStore(object(), sqlite_path=path, target_name="two")
    try:
        job = one.register_task(tool_name="delete_vm", summary="x", node="pve", upid="UPID:1")
        assert two.list_jobs() == []
        for operation in (two.get_job, two.poll_job, two.cancel_job, two.retry_job):
            with pytest.raises(ValueError, match="Unknown job_id"):
                operation(job["job_id"])
    finally:
        one.close()
        two.close()


def test_job_persistence_redacts_retry_secrets_and_url_credentials(tmp_path):
    store = JobStore(object(), sqlite_path=str(tmp_path / "jobs.sqlite3"), target_name="pl")
    try:
        job = store.register_task(
            tool_name="download_iso", summary="x", node="pve", upid="UPID:1",
            retry_spec={"kind": "iso.download", "params": {"url": "https://u:pw@example.test/a?token=secret", "password": "pw"}},
        )
        rendered = repr(job)
        assert "pw" not in rendered
        assert "secret" not in rendered
        assert "example.test" in rendered
    finally:
        store.close()


def test_register_task_redacts_secrets_in_initial_audit_output(tmp_path):
    store = JobStore(object(), sqlite_path=str(tmp_path / "jobs.sqlite3"))
    try:
        job = store.register_task(
            tool_name="download_iso",
            summary="x",
            node="pve",
            upid="UPID:1",
            metadata={"password": "initial-password", "nested": {"token": "initial-token"}},
        )

        assert [event["event"] for event in job["audit_log"]] == ["created"]
        assert job["audit_log"][0]["details"]["metadata"] == {
            "password": "[REDACTED]",
            "nested": {"token": "[REDACTED]"},
        }
        assert "initial-password" not in repr(job)
        assert "initial-token" not in repr(job)
    finally:
        store.close()


def test_target_names_with_wildcards_cannot_cross_list_jobs(tmp_path):
    path = str(tmp_path / "shared.sqlite3")
    wildcard_target = JobStore(object(), sqlite_path=path, target_name="prod%_")
    literal_target = JobStore(object(), sqlite_path=path, target_name="prod-east")
    try:
        wildcard_job = wildcard_target.register_task(
            tool_name="start_vm", summary="wildcard", node="pve", upid="UPID:wildcard"
        )
        literal_job = literal_target.register_task(
            tool_name="start_vm", summary="literal", node="pve", upid="UPID:literal"
        )

        assert [job["job_id"] for job in wildcard_target.list_jobs()] == [wildcard_job["job_id"]]
        assert [job["job_id"] for job in literal_target.list_jobs()] == [literal_job["job_id"]]
    finally:
        wildcard_target.close()
        literal_target.close()
