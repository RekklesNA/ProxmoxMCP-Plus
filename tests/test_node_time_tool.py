"""Node clock diagnostic contract."""
import json
from unittest.mock import MagicMock
import pytest
from proxmox_mcp.tools.node import NodeTools


def test_get_node_time_read_only_scoped():
    api = MagicMock()
    api.nodes.return_value.time.get.return_value = {"time": 1760000000, "localtime": 1760025200, "timezone": "Asia/Bangkok"}
    payload = json.loads(NodeTools(api).get_node_time("six")[0].text)
    assert payload == {"node": "six", "time": 1760000000, "localtime": 1760025200, "timezone": "Asia/Bangkok"}
    api.nodes.assert_called_once_with("six")
    api.nodes.return_value.time.get.assert_called_once_with()


def test_node_time_rejects_empty_node():
    with pytest.raises(ValueError, match="non-empty"):
        NodeTools(MagicMock()).get_node_time(" ")


def test_node_time_rejects_invalid_response():
    api = MagicMock()
    api.nodes.return_value.time.get.return_value = {"timezone": "UTC"}
    with pytest.raises(RuntimeError, match="epoch timestamp"):
        NodeTools(api).get_node_time("ichi")


def test_node_time_handles_offline_node():
    api = MagicMock()
    api.nodes.return_value.time.get.side_effect = ConnectionError("node offline")
    tool = NodeTools(api)
    tool._call_with_retry = lambda label, fn: fn()
    with pytest.raises(RuntimeError, match="offline"):
        tool.get_node_time("go")

def test_node_time_mcp_registry_dispatch():
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
    assert registered["get_node_time"](node="six", target="prod") == {"node": "six", "target": "prod"}
    assert plugin._wrap_sync.call_args.args[1] == "get_node_time"
