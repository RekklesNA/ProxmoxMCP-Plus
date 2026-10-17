from unittest.mock import Mock
import pytest
from proxmox_mcp.tools.containers import ContainerTools


def test_migration_posts_to_source_and_returns_upid():
    api = Mock()
    api.nodes.return_value.lxc.return_value.migrate.post.return_value = "UPID:sam:0001"
    tool = ContainerTools(api)
    tool._format_response = lambda value: value
    result = tool.migrate_container("sam", "115", "six")
    assert result["status"] == "submitted"
    assert result["upid"] == "UPID:sam:0001"
    api.nodes.return_value.lxc.return_value.migrate.post.assert_called_once_with(
        target="six", restart=1, **{"with-local-disks": 1}
    )


def test_migration_rejects_same_node():
    with pytest.raises(ValueError):
        ContainerTools(Mock()).migrate_container("sam", "115", "sam")
