"""Regression coverage for guarded VM serial console and cloud-image operations."""
from unittest.mock import MagicMock

import pytest

from proxmox_mcp.tools.vm import VMTools


def _tools(*, status="stopped", config=None, storage=None, imports=None):
    api = MagicMock()
    guest = api.nodes.return_value.qemu.return_value
    guest.status.current.get.return_value = {"status": status}
    guest.config.get.return_value = config or {"digest": "abc"}
    api.nodes.return_value.storage.get.return_value = storage or [
        {"storage": "source", "content": "import", "active": 1},
        {"storage": "local-lvm", "content": "images,rootdir", "active": 1},
    ]
    api.nodes.return_value.storage.return_value.content.get.return_value = imports or [
        {"volid": "source:import/debian.qcow2"}
    ]
    tool = VMTools(api)
    return tool, guest


def test_serial_requires_confirmation_and_stopped_vm():
    tool, guest = _tools()
    with pytest.raises(ValueError, match="confirm_display_change"):
        tool.configure_vm_serial_console("six", "142")
    guest.config.put.assert_not_called()
    tool, guest = _tools(status="running")
    with pytest.raises(ValueError, match="stopped"):
        tool.configure_vm_serial_console("six", "142", confirm_display_change=True)
    guest.config.put.assert_not_called()


def test_serial_does_not_overwrite_existing_serial_device():
    tool, guest = _tools(config={"digest": "abc", "serial0": "/dev/ttyS0"})
    with pytest.raises(ValueError, match="already configured"):
        tool.configure_vm_serial_console("six", "142", confirm_display_change=True)
    guest.config.put.assert_not_called()


def test_serial_setup_sets_socket_and_vga():
    tool, guest = _tools()
    tool.configure_vm_serial_console("six", "142", confirm_display_change=True)
    guest.config.put.assert_called_once_with(serial0="socket", vga="serial0", digest="abc")


def test_import_requires_confirmation_and_stopped_vm():
    tool, guest = _tools()
    kwargs = dict(node="six", vmid="142", source_volume="source:import/debian.qcow2",
                  destination_storage="local-lvm")
    with pytest.raises(ValueError, match="confirm_import"):
        tool.import_cloud_image(**kwargs)
    guest.config.post.assert_not_called()
    tool, guest = _tools(status="running")
    with pytest.raises(ValueError, match="stopped"):
        tool.import_cloud_image(**kwargs, confirm_import=True)
    guest.config.post.assert_not_called()


def test_import_does_not_overwrite_disk_or_accept_arbitrary_path():
    kwargs = dict(node="six", vmid="142", destination_storage="local-lvm",
                  confirm_import=True)
    tool, guest = _tools(config={"digest": "abc", "scsi1": "local-lvm:vm-142-disk-1"})
    with pytest.raises(ValueError, match="already in use"):
        tool.import_cloud_image(source_volume="source:import/debian.qcow2", **kwargs)
    guest.config.post.assert_not_called()
    tool, guest = _tools()
    with pytest.raises(ValueError, match="source_volume"):
        tool.import_cloud_image(source_volume="../../etc/passwd", **kwargs)
    guest.config.post.assert_not_called()
