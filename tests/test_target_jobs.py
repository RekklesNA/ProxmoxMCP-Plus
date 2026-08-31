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
        with pytest.raises(ValueError, match="Unknown job_id"):
            two.get_job(job["job_id"])
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
