"""Offline cluster members must not turn incomplete backup inventories into false negatives."""
import json
from unittest.mock import MagicMock
import pytest
from proxmox_mcp.tools.backup import BackupTools


def test_offline_node_reported_incomplete_without_querying_it():
    api = MagicMock()
    api.nodes.get.return_value = [{"node": "sam", "status": "online"}, {"node": "go", "status": "offline"}]
    api.nodes.return_value.storage.get.return_value = []
    output = BackupTools(api).list_backups(vmid="115")
    assert "inventory incomplete" in output[0].text.lower()
    detail = json.loads(output[1].text)
    assert detail["code"] == "INCOMPLETE_INVENTORY"
    assert any("go" in warning for warning in detail["warnings"])
    api.nodes.assert_called_once_with("sam")


def test_partial_backups_retained_and_incompleteness_signaled():
    api = MagicMock()
    api.nodes.get.return_value = [{"node": "sam", "status": "online"}, {"node": "go", "status": "offline"}]
    api.nodes.return_value.storage.get.return_value = [{"storage": "local", "content": "backup"}]
    api.nodes.return_value.storage.return_value.content.get.return_value = [
        {"volid": "local:backup/vzdump-lxc-115.tar.zst", "vmid": 115, "ctime": 1}
    ]
    output = BackupTools(api).list_backups(vmid="115")
    assert "vzdump-lxc-115.tar.zst" in output[0].text
    assert "partial" in output[0].text.lower()
    assert json.loads(output[1].text)["code"] == "INCOMPLETE_INVENTORY"


def test_offline_free_empty_inventory_is_confirmed_empty():
    api = MagicMock()
    api.nodes.get.return_value = [{"node": "sam", "status": "online"}]
    api.nodes.return_value.storage.get.return_value = []
    output = BackupTools(api).list_backups(vmid="115")
    assert output[0].text == "No backups found for VM/CT 115"
    assert len(output) == 1


def test_unreachable_online_node_returns_incomplete_inventory():
    api = MagicMock()
    api.nodes.get.return_value = [{"node": "sam", "status": "online"}]
    api.nodes.return_value.storage.get.side_effect = ConnectionError("unreachable")
    with pytest.raises(RuntimeError, match="Backup listing incomplete"):
        BackupTools(api).list_backups()
