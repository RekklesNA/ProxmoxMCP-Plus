"""Cluster join metadata is read-only and never returns credentials."""
import json
from unittest.mock import MagicMock
import pytest
from proxmox_mcp.tools.cluster import ClusterTools


def test_join_info_returns_addresses_and_fingerprint():
    api = MagicMock()
    api.cluster.config.join.get.return_value = {
        "nodelist": [{"name": "ichi", "pve_addr": "192.0.2.1"}],
        "fingerprint": "AA:BB", "secret": "private", "nested": {"password": "private"},
    }
    payload = json.loads(ClusterTools(api).get_cluster_join_info()[0].text)
    assert payload["fingerprint"] == "AA:BB"
    assert payload["nodelist"][0]["name"] == "ichi"
    assert "secret" not in payload
    assert "password" not in payload["nested"]
    api.cluster.config.join.get.assert_called_once_with()


def test_join_info_rejects_unexpected_shape():
    api = MagicMock()
    api.cluster.config.join.get.return_value = []
    with pytest.raises(RuntimeError, match="Unexpected"):
        ClusterTools(api).get_cluster_join_info()


def test_join_info_surfaces_hostname_resolution_error():
    api = MagicMock()
    api.cluster.config.join.get.side_effect = RuntimeError("hostname lookup 'go' failed")
    tool = ClusterTools(api)
    tool._call_with_retry = lambda label, fn: fn()
    with pytest.raises(RuntimeError, match="hostname lookup"):
        tool.get_cluster_join_info()


def test_cluster_join_info_registry_dispatches_correct_target():
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
    assert registered["get_cluster_join_info"](target="prod") == {"target": "prod"}
    assert plugin._wrap_sync.call_args.args[1] == "get_cluster_join_info"
