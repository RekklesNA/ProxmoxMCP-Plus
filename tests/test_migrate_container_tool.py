"""High-risk LXC migration must preflight and register a non-retryable task."""
import json
from unittest.mock import MagicMock
import pytest
from proxmox_mcp.tools.containers import ContainerTools


def migration_api(running=False):
    api = MagicMock()
    api.nodes.get.return_value = [{"node": "sam", "status": "online"}, {"node": "six", "status": "online"}]
    guest = api.nodes.return_value.lxc.return_value
    guest.config.get.return_value = {"rootfs": "local-lvm:vm-115-disk-0,size=40G"}
    guest.status.current.get.return_value = {"status": "running" if running else "stopped"}
    guest.migrate.post.return_value = "UPID:sam:migrate:115"
    api.cluster.ha.resources.get.return_value = []
    api.nodes.return_value.storage.return_value.status.get.return_value = {
        "active": 1, "enabled": 1, "content": "rootdir,images", "avail": 100 * 1024**3,
    }
    api.nodes.return_value.storage.get.return_value = [{"storage": "local", "content": "backup"}]
    api.nodes.return_value.storage.return_value.content.get.return_value = [{"volid": "local:backup/ct-115"}]
    return api


def test_submits_once_and_registers_job_without_retry():
    api = migration_api()
    store = MagicMock()
    store.register_task.return_value = {"job_id": "job-migrate-115"}
    tool = ContainerTools(api, job_store=store)
    response = json.loads(tool.migrate_container("sam", "115", "six", confirm_migration=True)[0].text)
    assert response["status"] == "submitted"
    assert response["job_id"] == "job-migrate-115"
    api.nodes.return_value.lxc.return_value.migrate.post.assert_called_once_with(
        target="six", restart=0, **{"with-local-disks": 1}
    )
    details = store.register_task.call_args.kwargs
    assert details["retry_spec"] is None
    assert details["retry_factory"] is None


def test_requires_explicit_confirmation_without_submitting():
    api = migration_api()
    with pytest.raises(ValueError, match="confirm_migration"):
        ContainerTools(api).migrate_container("sam", "115", "six")
    api.nodes.return_value.lxc.return_value.migrate.post.assert_not_called()


def test_running_guest_requires_downtime_confirmation():
    api = migration_api(running=True)
    with pytest.raises(ValueError, match="confirm_downtime"):
        ContainerTools(api).migrate_container("sam", "115", "six", confirm_migration=True)
    api.nodes.return_value.lxc.return_value.migrate.post.assert_not_called()


def test_insufficient_space_blocks_before_post():
    api = migration_api()
    api.nodes.return_value.storage.return_value.status.get.return_value["avail"] = 2 * 1024**3
    with pytest.raises(ValueError, match="capacity"):
        ContainerTools(api).migrate_container("sam", "115", "six", confirm_migration=True)
    api.nodes.return_value.lxc.return_value.migrate.post.assert_not_called()


def test_ha_guest_blocks_before_post():
    api = migration_api()
    api.cluster.ha.resources.get.return_value = [{"sid": "ct:115"}]
    with pytest.raises(ValueError, match="HA-managed"):
        ContainerTools(api).migrate_container("sam", "115", "six", confirm_migration=True)
    api.nodes.return_value.lxc.return_value.migrate.post.assert_not_called()


def test_missing_backup_blocks_before_post():
    api = migration_api()
    api.nodes.return_value.storage.return_value.content.get.return_value = []
    with pytest.raises(ValueError, match="backup"):
        ContainerTools(api).migrate_container("sam", "115", "six", confirm_migration=True)
    api.nodes.return_value.lxc.return_value.migrate.post.assert_not_called()
