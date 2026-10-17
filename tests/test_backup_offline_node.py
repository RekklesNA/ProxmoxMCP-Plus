from unittest.mock import Mock
from proxmox_mcp.tools.backup import BackupTools


def test_list_backups_reports_offline_nodes_without_querying_them():
    api = Mock()
    api.nodes.get.return_value = [{"node": "sam", "status": "online"}, {"node": "go", "status": "offline"}]
    api.nodes.return_value.storage.get.return_value = []
    tool = BackupTools(api)
    result = tool.list_backups()
    assert "incomplete" in result[0].text
    assert "go" in result[0].text
