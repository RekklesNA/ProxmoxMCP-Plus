import json
from unittest.mock import Mock

import pytest

from proxmox_mcp.tools.backup import BackupTools
from proxmox_mcp.tools.containers import ContainerTools
from proxmox_mcp.tools.iso import ISOTools
from proxmox_mcp.tools.snapshots import SnapshotTools
from proxmox_mcp.tools.vm import VMTools


def test_delete_vm_refuses_running_vm_without_force():
    proxmox = Mock()
    vm_api = proxmox.nodes.return_value.qemu.return_value
    vm_api.status.current.get.return_value = {"status": "running", "name": "db"}
    tools = VMTools(proxmox)

    with pytest.raises(ValueError, match="currently running"):
        tools.delete_vm("pve1", "100", force=False)

    vm_api.status.stop.post.assert_not_called()
    vm_api.delete.assert_not_called()


def test_delete_container_refuses_running_container_without_force():
    proxmox = Mock()
    ct_api = proxmox.nodes.return_value.lxc.return_value
    ct_api.status.current.get.return_value = {"status": "running"}
    tools = ContainerTools(proxmox)
    tools._resolve_targets = Mock(return_value=[("pve1", 101, "web")])  # type: ignore[method-assign]

    response = tools.delete_container("web", force=False, format_style="json")
    payload = json.loads(response[0].text)

    assert payload[0]["ok"] is False
    assert "running" in payload[0]["error"]
    ct_api.status.stop.post.assert_not_called()
    ct_api.delete.assert_not_called()


def test_delete_backup_refuses_protected_backup():
    proxmox = Mock()
    storage_api = proxmox.nodes.return_value.storage.return_value
    storage_api.content.get.return_value = [
        {"volid": "local:backup/vzdump-qemu-100.vma.zst", "protected": 1}
    ]
    tools = BackupTools(proxmox)

    response = tools.delete_backup(
        "pve1",
        "local",
        "local:backup/vzdump-qemu-100.vma.zst",
    )

    assert "protected" in response[0].text
    storage_api.content.return_value.delete.assert_not_called()


def test_delete_iso_missing_filename_does_not_delete():
    proxmox = Mock()
    storage_api = proxmox.nodes.return_value.storage.return_value
    storage_api.content.get.return_value = [
        {"volid": "local:iso/debian.iso"},
    ]
    tools = ISOTools(proxmox)

    response = tools.delete_iso("pve1", "local", "ubuntu.iso")

    assert "Could not find" in response[0].text
    storage_api.content.return_value.delete.assert_not_called()


def test_delete_snapshot_uses_qemu_snapshot_endpoint():
    proxmox = Mock()
    snapshot_api = proxmox.nodes.return_value.qemu.return_value.snapshot.return_value
    snapshot_api.delete.return_value = "UPID:snapshot-delete"
    tools = SnapshotTools(proxmox)

    response = tools.delete_snapshot("pve1", "100", "before-upgrade", vm_type="qemu")

    assert "Snapshot Deleted" in response[0].text
    assert "UPID:snapshot-delete" in response[0].text
    snapshot_api.delete.assert_called_once()


def test_restore_lxc_backup_uses_lxc_endpoint():
    proxmox = Mock()
    proxmox.nodes.return_value.lxc.post.return_value = "UPID:restore-lxc"
    tools = BackupTools(proxmox)

    response = tools.restore_backup(
        "pve1",
        "local:backup/vzdump-lxc-101.tar.zst",
        "201",
        storage="local-lvm",
        unique=True,
    )

    assert "Container Restore Started" in response[0].text
    proxmox.nodes.return_value.lxc.post.assert_called_once_with(
        ostemplate="local:backup/vzdump-lxc-101.tar.zst",
        restore=1,
        vmid=201,
        storage="local-lvm",
        unique=1,
    )
    proxmox.nodes.return_value.qemu.post.assert_not_called()
