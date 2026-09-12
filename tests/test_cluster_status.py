"""Regression cases for issue #125 using recorded-shape Proxmox responses."""

from unittest.mock import Mock

import pytest

from proxmox_mcp.formatting import ProxmoxTemplates
from proxmox_mcp.tools.cluster import ClusterTools


@pytest.mark.parametrize(
    "records, name, quorum, nodes",
    [
        pytest.param(
            [{"type": "node", "name": "pve", "local": 1, "online": 1}],
            "n/a (not clustered)", "n/a (not clustered)", 1, id="standalone",
        ),
        pytest.param([], "unknown", "unknown", 0, id="empty-response"),
        pytest.param(None, "unknown", "unknown", 0, id="null-response"),
        pytest.param(
            [{"type": "node", "name": "pve"},
             {"type": "cluster", "name": "lab", "quorate": 1}],
            "lab", "OK", 1, id="cluster-record-last",
        ),
        pytest.param(
            [{"type": "node", "name": "pve"},
             {"type": "cluster", "name": "lab", "quorate": 0}],
            "lab", "NOT OK", 1, id="one-node-cluster-without-quorum",
        ),
        pytest.param(
            [{"type": "cluster", "name": "lab", "quorate": 1},
             {"type": "node", "name": "pve1"}, {"type": "node", "name": "pve2"}],
            "lab", "OK", 2, id="healthy-cluster",
        ),
        pytest.param(
            [{"type": "cluster", "name": "lab", "quorate": 0},
             {"type": "node", "name": "pve1"}, {"type": "node", "name": "pve2"}],
            "lab", "NOT OK", 2, id="cluster-without-quorum",
        ),
        pytest.param(
            [{"type": "cluster", "name": "lab", "quorate": None}],
            "lab", "unknown", 0, id="null-quorum",
        ),
        pytest.param(
            [{"type": "cluster", "name": "lab"}],
            "lab", "unknown", 0, id="missing-quorum",
        ),
    ],
)
def test_cluster_status_reports_applicable_verdict(records, name, quorum, nodes):
    api = Mock()
    api.cluster.status.get.return_value = records
    tool = ClusterTools(api)

    text = tool.get_cluster_status()[0].text
    assert f"  - Name: {name}" in text
    assert f"  - Quorum: {quorum}" in text
    assert f"  - Nodes: {nodes}" in text
    if quorum != "NOT OK":
        assert "NOT OK" not in text

    # The cached response must retain the same classification and verdict.
    assert tool.get_cluster_status()[0].text == text
    api.cluster.status.get.assert_called_once_with()


@pytest.mark.parametrize("quorum, expected", [(True, "OK"), (False, "NOT OK"), (None, "unknown")])
def test_legacy_template_input_without_clustered_flag(quorum, expected):
    text = ProxmoxTemplates.cluster_status({"name": "lab", "quorum": quorum, "nodes": 2})
    assert "Name: lab" in text
    assert f"Quorum: {expected}" in text


def test_cluster_status_api_failure_is_not_reported_as_standalone(monkeypatch):
    api = Mock()
    api.cluster.status.get.side_effect = RuntimeError("upstream unavailable")
    monkeypatch.setattr("proxmox_mcp.tools.base.time.sleep", lambda _: None)

    with pytest.raises(RuntimeError, match="upstream unavailable"):
        ClusterTools(api).get_cluster_status()
