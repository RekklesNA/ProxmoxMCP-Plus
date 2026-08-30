from proxmox_mcp.services.jobs import JobStore


def test_job_store_persists_target_name(tmp_path):
    store = JobStore(object(), sqlite_path=str(tmp_path / "jobs.sqlite3"), target_name="pl")
    try:
        job = store.register_task(
            tool_name="create_vm", summary="create", node="pve", upid="UPID:1"
        )
        assert job["metadata"]["target"] == "pl"
    finally:
        store.close()
