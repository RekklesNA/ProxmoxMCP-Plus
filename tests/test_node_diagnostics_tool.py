from unittest.mock import Mock
from proxmox_mcp.tools.node import NodeTools


def test_node_diagnostics_uses_only_requested_node():
    api = Mock()
    api.nodes.return_value.status.get.return_value = {"cpu": 0.25, "loadavg": [1, 2, 3], "memory": {"used": 10}}
    api.nodes.return_value.storage.get.return_value = [{"storage": "local-lvm", "avail": 200}]
    tool = NodeTools(api)
    tool._format_response = lambda data: data
    result = tool.get_node_diagnostics("six")
    assert result["node"] == "six"
    assert result["storage"][0]["avail"] == 200
    assert api.nodes.call_count == 2
