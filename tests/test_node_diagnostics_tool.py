"""Node diagnostics API and partial-results coverage."""
import json
from unittest.mock import MagicMock
import pytest
from proxmox_mcp.tools.node import NodeTools


def test_diagnostics_scoped_metrics_and_io_sample():
    api = MagicMock()
    api.nodes.return_value.status.get.return_value = {"cpu": 0.2, "wait": 0.05, "loadavg": [1, 2, 3]}
    api.nodes.return_value.storage.get.return_value = [{"storage": "local-lvm", "avail": 1024}]
    api.nodes.return_value.rrddata.get.return_value = [{"time": 10, "diskread": 5}, {"time": 20, "diskread": 12}]
    data = json.loads(NodeTools(api).get_node_diagnostics("six")[0].text)
    assert data["latest_rrd_io"]["diskread"] == 12
    assert data["io_wait_fraction"] == 0.05
    assert data["complete"] is True
    assert data["process_list_available"] is False
    assert all(call.args == ("six",) for call in api.nodes.call_args_list)


def test_optional_failures_keep_primary_status():
    api = MagicMock()
    api.nodes.return_value.status.get.return_value = {"cpu": 0.0}
    api.nodes.return_value.storage.get.side_effect = PermissionError("denied")
    api.nodes.return_value.rrddata.get.side_effect = PermissionError("denied")
    data = json.loads(NodeTools(api).get_node_diagnostics("six")[0].text)
    assert data["cpu_fraction"] == 0.0
    assert data["complete"] is False
    assert len(data["warnings"]) == 2


def test_primary_status_failure_is_not_masked():
    api = MagicMock()
    api.nodes.return_value.status.get.side_effect = ConnectionError("offline")
    tool = NodeTools(api)
    tool._call_with_retry = lambda label, fn: fn()
    with pytest.raises(RuntimeError, match="offline"):
        tool.get_node_diagnostics("go")

def test_diagnostics_rejects_empty_node_and_malformed_status():
    with pytest.raises(ValueError, match="non-empty"):
        NodeTools(MagicMock()).get_node_diagnostics("")
    api = MagicMock()
    api.nodes.return_value.status.get.return_value = []
    with pytest.raises(ValueError, match="invalid response"):
        NodeTools(api).get_node_diagnostics("six")


@pytest.mark.parametrize("field", ["storage", "rrddata"])
def test_diagnostics_invalid_optional_api_shape_is_partial(field):
    api = MagicMock()
    api.nodes.return_value.status.get.return_value = {"cpu": 0.15}
    api.nodes.return_value.storage.get.return_value = []
    api.nodes.return_value.rrddata.get.return_value = []
    if field == "storage":
        api.nodes.return_value.storage.get.return_value = {}
    else:
        api.nodes.return_value.rrddata.get.return_value = {}
    result = json.loads(NodeTools(api).get_node_diagnostics("six")[0].text)
    assert result["complete"] is False
    assert result["warnings"]


def test_diagnostics_registry_dispatch():
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
    assert registered["get_node_diagnostics"](node="six", target="prod") == {"node": "six", "target": "prod"}
    assert plugin._wrap_sync.call_args.args[1] == "get_node_diagnostics"
