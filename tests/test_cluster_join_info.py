from unittest.mock import Mock

from proxmox_mcp.tools.cluster import ClusterTools


def test_cluster_join_info_uses_proxmox_api():
    api = Mock()
    expected = {"nodelist": [{"name": "ichi", "pve_addr": "192.0.2.1"}], "totem": {}}
    api.cluster.config.join.get.return_value = expected
    tool = ClusterTools(api)
    tool._call_with_retry = lambda label, fn: fn()
    tool._format_response = lambda data: data
    assert tool.get_cluster_join_info() == expected
    api.cluster.config.join.get.assert_called_once_with()
