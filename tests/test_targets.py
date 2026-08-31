import pytest

from proxmox_mcp.config.models import Config
from proxmox_mcp.core.targets import TargetRegistry


def _legacy_config() -> Config:
    return Config.model_validate({
        "proxmox": {"host": "cluster", "port": 8006},
        "auth": {"user": "u", "token_name": "t", "token_value": "v"},
        "logging": {},
    })


def _multi_config() -> Config:
    return Config.model_validate({
        "targets": {
            "cluster": {
                "host": "127.0.0.1", "port": 18007,
                "auth": {"user": "cluster-u", "token_name": "t", "token_value": "cluster-v"},
                "kind": "cluster",
            },
            "pl": {
                "host": "pl.hadm.net", "port": 8006,
                "auth": {"user": "pl-u", "token_name": "t", "token_value": "pl-v"},
                "kind": "standalone",
            },
        },
        "logging": {},
    })


def test_legacy_config_resolves_implicit_single_target():
    registry = TargetRegistry(_legacy_config())
    target = registry.resolve()
    assert target.name == "default"
    assert target.config.host == "cluster"


def test_multiple_targets_require_explicit_target():
    registry = TargetRegistry(_multi_config())
    with pytest.raises(ValueError, match="Multiple Proxmox targets"):
        registry.resolve()


def test_multiple_targets_resolve_cluster_and_pl_exactly():
    registry = TargetRegistry(_multi_config())
    assert registry.resolve("cluster").config.host == "127.0.0.1"
    assert registry.resolve("pl").config.host == "pl.hadm.net"


def test_unknown_target_lists_available_targets():
    registry = TargetRegistry(_multi_config())
    with pytest.raises(ValueError, match="cluster.*pl"):
        registry.resolve("missing")


def test_discovery_is_deterministic_and_secret_free():
    registry = TargetRegistry(_multi_config())
    metadata = registry.describe()
    assert [item["name"] for item in metadata] == ["cluster", "pl"]
    rendered = repr(metadata)
    assert "cluster-v" not in rendered
    assert "pl-v" not in rendered


def test_target_tls_rejects_string_boolean():
    with pytest.raises(ValueError):
        Config.model_validate({
            "targets": {"a": {"host": "a", "auth": {"user": "u", "token_name": "t", "token_value": "v"}, "verify_ssl": "false"}},
        })


def test_target_names_reject_path_traversal():
    with pytest.raises(ValueError, match="target name"):
        Config.model_validate({
            "targets": {"../escape": {"host": "a", "auth": {"user": "u", "token_name": "t", "token_value": "v"}}},
        })


def test_target_tunnels_require_distinct_remote_destinations_too():
    data = {"targets": {}}
    for name, host in (("a", "a"), ("b", "b")):
        data["targets"][name] = {"host": host, "auth": {"user": "u", "token_name": "t", "token_value": "v"}, "api_tunnel": {"enabled": True, "ssh_host": "jump", "local_port": 18000 + ord(name), "remote_host": "same", "remote_port": 8006}}
    with pytest.raises(ValueError, match="remote endpoint"):
        Config.model_validate(data)


def test_target_tunnels_require_distinct_local_endpoints():
    data = {"targets": {}}
    for name, host in (("a", "a"), ("b", "b")):
        data["targets"][name] = {"host": host, "auth": {"user": "u", "token_name": "t", "token_value": "v"}, "api_tunnel": {"enabled": True, "ssh_host": "jump"}}
    with pytest.raises(ValueError, match="shared by targets"):
        Config.model_validate(data)