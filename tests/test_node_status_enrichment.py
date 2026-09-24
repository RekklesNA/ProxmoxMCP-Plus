"""Keep node samples authoritative and optional enrichment best effort."""
from unittest.mock import MagicMock

import pytest

from proxmox_mcp.tools.node import NodeTools


@pytest.mark.parametrize("cpu", [0, 0.25])
def test_existing_cpu_sample_is_preserved(cpu):
    api = MagicMock()
    api.nodes.return_value.status.get.return_value = {"cpu": cpu}
    api.cluster.resources.get.return_value = [{"node": "pve1", "cpu": 0.75}]
    result = NodeTools(api).get_node_status("pve1")[0].text
    assert f"CPU Usage: {cpu * 100:.1f}%" in result
    api.cluster.resources.get.assert_not_called()


@pytest.mark.parametrize("sample", [{}, {"cpu": None}])
@pytest.mark.parametrize("cpu", [0, 0.25])
def test_missing_cpu_uses_matching_node(sample, cpu):
    api = MagicMock()
    api.nodes.return_value.status.get.return_value = sample.copy()
    api.cluster.resources.get.return_value = [
        {"node": "other", "cpu": 0.9}, {"node": "pve1", "cpu": cpu}
    ]
    result = NodeTools(api).get_node_status("pve1")[0].text
    assert f"CPU Usage: {cpu * 100:.1f}%" in result
    api.cluster.resources.get.assert_called_once_with(type="node")


def test_enrichment_permission_failure_does_not_hide_status():
    api = MagicMock()
    api.nodes.return_value.status.get.return_value = {}
    api.cluster.resources.get.side_effect = PermissionError("denied")
    result = NodeTools(api).get_node_status("pve1")[0].text
    assert "Status: ONLINE" in result
    assert "CPU Usage" not in result
    api.nodes.get.assert_not_called()
