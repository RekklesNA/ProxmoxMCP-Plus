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
