from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from proxmox_mcp.tools.storage import StorageTools


def test_get_node_storage_is_scoped_to_requested_node():
    api = Mock()
    api.nodes.return_value.storage.get.return_value = [
        {"storage": "local-lvm", "type": "lvmthin", "total": 1000,
         "used": 300, "avail": 700, "active": 1, "shared": 0}
    ]
    tool = StorageTools(api)
    tool._format_response = lambda x: x
    tool._call_with_retry = lambda description, fn: fn()
    data = tool.get_node_storage("six")
    api.nodes.assert_called_once_with("six")
    assert data[0]["node"] == "six"
    assert data[0]["available"] == 700


def test_get_node_storage_rejects_blank_node():
    with pytest.raises(ValueError):
        StorageTools(Mock()).get_node_storage(" ")
