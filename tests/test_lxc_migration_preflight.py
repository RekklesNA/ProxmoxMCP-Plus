from unittest.mock import Mock
from proxmox_mcp.tools.containers import ContainerTools


def test_preflight_flags_additional_mountpoints():
    api = Mock()
    api.nodes.get.return_value = [{"node": "sam", "status": "online"}, {"node": "six", "status": "online"}]
    api.nodes.return_value.lxc.return_value.config.get.return_value = {"rootfs": "local-lvm:vm-115-disk-0,size=40G", "mp0": "/host/data,mp=/data"}
    api.nodes.return_value.storage.get.return_value = [{"storage": "local-lvm", "active": 1}]
    tool = ContainerTools(api)
    tool._format_response = lambda value: value
    output = tool.preflight_container_migration("sam", "115", "six")
    assert output["ready"] is False
    assert any("mount" in warning for warning in output["warnings"])
