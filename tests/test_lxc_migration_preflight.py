"""Migration preflight fails closed without critical evidence."""
import json
from unittest.mock import MagicMock
import pytest
from proxmox_mcp.tools.containers import ContainerTools


def api_for_preflight():
    api = MagicMock()
    api.nodes.get.return_value = [{"node": "sam", "status": "online"}, {"node": "six", "status": "online"}]
    api.nodes.return_value.lxc.return_value.config.get.return_value = {
        "rootfs": "local-lvm:vm-115-disk-0,size=40G", "memory": 8192,
    }
    api.nodes.return_value.lxc.return_value.status.current.get.return_value = {"status": "stopped"}
    api.nodes.return_value.storage.return_value.status.get.return_value = {
        "active": 1, "enabled": 1, "content": "images,rootdir", "avail": 100 * 1024**3,
    }
    api.nodes.return_value.storage.get.return_value = [{"storage": "local", "content": "backup"}]
    api.nodes.return_value.storage.return_value.content.get.return_value = [{"vmid": 115, "volid": "local:backup/test"}]
    api.cluster.ha.resources.get.return_value = []
    return api


def check(api, **kwargs):
    return json.loads(ContainerTools(api).preflight_container_migration("sam", "115", "six", **kwargs)[0].text)


def test_preflight_with_complete_evidence():
    result = check(api_for_preflight())
    assert result["ready"] is True
    assert result["checks"]["backup_found"] is True


def test_running_container_requires_downtime():
    api = api_for_preflight()
    api.nodes.return_value.lxc.return_value.status.current.get.return_value = {"status": "running"}
    result = check(api)
    assert result["ready"] is False
    assert any("downtime" in x for x in result["blockers"])


def test_extra_mount_and_insufficient_disk_block_migration():
    api = api_for_preflight()
    api.nodes.return_value.lxc.return_value.config.get.return_value["mp0"] = "/host/data,mp=/data"
    api.nodes.return_value.storage.return_value.status.get.return_value["avail"] = 3 * 1024**3
    result = check(api)
    assert result["ready"] is False
    assert any("mount" in x for x in result["blockers"])
    assert any("capacity" in x for x in result["blockers"])


def test_backup_unknown_fails_closed():
    api = api_for_preflight()
    api.nodes.return_value.storage.get.side_effect = PermissionError("backup inventory denied")
    result = check(api)
    assert result["ready"] is False
    assert any("Backup" in x for x in result["unknowns"])


def test_ha_membership_blocks_migration():
    api = api_for_preflight()
    api.cluster.ha.resources.get.return_value = [{"sid": "ct:115"}]
    result = check(api)
    assert result["ready"] is False
    assert any("HA" in x for x in result["blockers"])


def test_same_node_is_rejected():
    with pytest.raises(ValueError):
        ContainerTools(MagicMock()).preflight_container_migration("sam", "115", "sam")
