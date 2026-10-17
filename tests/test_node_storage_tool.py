"""Node-specific storage data must not borrow capacity from other nodes."""
import json
from unittest.mock import MagicMock
import pytest
from proxmox_mcp.tools.storage import StorageTools


def test_storage_scoped_to_destination_and_no_guarantee():
    api = MagicMock()
    api.nodes.return_value.storage.get.return_value = [{
        "storage": "local-lvm", "type": "lvmthin", "content": "images,rootdir",
        "total": 107374182400, "used": 2048, "avail": 4096, "active": 1, "enabled": 1,
    }]
    result = json.loads(StorageTools(api).get_node_storage("six", "local-lvm")[0].text)
    assert result[0]["node"] == "six"
    assert result[0]["available_bytes"] == 4096
    assert result[0]["thin_provisioned"] is True
    assert result[0]["migration_capacity_guaranteed"] is False
    assert result[0]["rootdir_supported"] is True
    api.nodes.assert_called_once_with("six")


def test_storage_inactive_and_unknown_capacity_are_not_invented():
    api = MagicMock()
    api.nodes.return_value.storage.get.return_value = [
        {"storage": "local-lvm", "type": "lvmthin", "active": 0, "enabled": 1}
    ]
    result = json.loads(StorageTools(api).get_node_storage("six")[0].text)[0]
    assert result["active"] is False
    assert result["available_bytes"] is None
    assert result["rootdir_supported"] is False


def test_storage_missing_selected_pool():
    api = MagicMock()
    api.nodes.return_value.storage.get.return_value = [{"storage": "local", "active": 1}]
    with pytest.raises(ValueError, match="not found"):
        StorageTools(api).get_node_storage("six", "local-lvm")


def test_storage_rejects_empty_name():
    with pytest.raises(ValueError, match="non-empty"):
        StorageTools(MagicMock()).get_node_storage("")


def test_storage_empty_records_is_not_treated_as_zero_capacity():
    api = MagicMock()
    api.nodes.return_value.storage.get.return_value = []
    with pytest.raises(RuntimeError, match="No storage status records"):
        StorageTools(api).get_node_storage("six")


def test_storage_skips_invalid_records_and_fails_when_none_valid():
    api = MagicMock()
    api.nodes.return_value.storage.get.return_value = [None, {"missing_storage_key": True}]
    with pytest.raises(RuntimeError, match="No valid storage status records"):
        StorageTools(api).get_node_storage("six")


def test_mcp_node_storage_registration_dispatches_selected_target():
    from types import SimpleNamespace
    from proxmox_mcp.services.builtin_tool_plugins import CoreToolsPlugin

    registered = {}
    def register(**kwargs):
        def decorator(fn):
            registered[fn.__name__] = fn
            return fn
        return decorator

    server = SimpleNamespace(proxmox_managers={}, tool_registry=SimpleNamespace(tool=register))
    plugin = CoreToolsPlugin()
    plugin._wrap_sync = MagicMock(return_value=lambda **kwargs: kwargs)
    plugin.register(server)
    assert registered["get_node_storage"](node="six", storage="local-lvm", target="prod") == {
        "node": "six", "storage": "local-lvm", "target": "prod"
    }
    assert plugin._wrap_sync.call_args.args[1] == "get_node_storage"
