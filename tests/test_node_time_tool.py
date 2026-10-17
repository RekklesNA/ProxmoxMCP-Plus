from unittest.mock import Mock
from proxmox_mcp.tools.node import NodeTools


def test_node_time_reads_selected_node():
    api = Mock()
    api.nodes.return_value.time.get.return_value = {"time": 1760700000, "timezone": "Asia/Bangkok"}
    tool = NodeTools(api)
    tool._call_with_retry = lambda _label, fn: fn()
    tool._format_response = lambda data: data
    assert tool.get_node_time("six")["timezone"] == "Asia/Bangkok"
    api.nodes.assert_called_once_with("six")
