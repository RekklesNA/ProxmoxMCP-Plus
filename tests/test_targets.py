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
    assert registry.is_legacy is True


def test_named_default_target_is_not_legacy_mode():
    config = Config.model_validate({
        "targets": {
            "default": {
                "host": "pve.example",
                "auth": {"user": "u", "token_name": "n", "token_value": "v"},
                "ssh": {"user": "root", "key_file": "/tmp/key"},
            }
        }
    })
    registry = TargetRegistry(config)

    assert registry.is_legacy is False
    assert registry.resolve().ssh is not None


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


def test_describe_can_include_isolated_target_discovery():
    registry = TargetRegistry(_multi_config())

    def discover(target):
        if target.name == "pl":
            raise RuntimeError("https://u:secret@example.invalid")
        return {"reachable": True, "nodes": ["pve1", "pve2", "pve3"]}

    metadata = registry.describe(discover=discover)
    assert metadata[0]["reachable"] is True
    assert metadata[0]["nodes"] == ["pve1", "pve2", "pve3"]
    assert metadata[1]["reachable"] is False
    assert metadata[1]["error"] == "Unable to reach target 'pl'"
    assert "secret" not in repr(metadata)


def test_describe_sanitizes_url_credentials_in_host():
    config = Config.model_validate({
        "targets": {
            "unsafe": {
                "host": "https://user:secret@example.invalid",
                "auth": {"user": "u", "token_name": "t", "token_value": "v"},
            }
        }
    })

    metadata = TargetRegistry(config).describe()

    assert metadata[0]["host"] == "https://[REDACTED]@example.invalid"
    assert "secret" not in repr(metadata)


def test_target_tls_rejects_string_boolean():
    with pytest.raises(ValueError):
        Config.model_validate({
            "targets": {"a": {"host": "a", "auth": {"user": "u", "token_name": "t", "token_value": "v"}, "verify_ssl": "false"}},
        })


def test_target_readonly_rejects_string_boolean():
    with pytest.raises(ValueError):
        Config.model_validate({
            "targets": {"a": {"host": "a", "auth": {"user": "u", "token_name": "t", "token_value": "v"}, "readonly": "yes"}},
        })


def test_assume_external_rejects_string_boolean():
    with pytest.raises(ValueError):
        Config.model_validate({
            "targets": {"a": {"host": "a", "auth": {"user": "u", "token_name": "t", "token_value": "v"}, "api_tunnel": {"enabled": True, "assume_external": "true", "ssh_host": "jump"}}},
        })


def test_target_names_reject_path_traversal():
    with pytest.raises(ValueError, match="target name"):
        Config.model_validate({
            "targets": {"../escape": {"host": "a", "auth": {"user": "u", "token_name": "t", "token_value": "v"}}},
        })


def test_target_names_reject_trailing_newline():
    with pytest.raises(ValueError, match="target name"):
        Config.model_validate({
            "targets": {"safe\n": {"host": "a", "auth": {"user": "u", "token_name": "t", "token_value": "v"}}},
        })


def test_target_tls_requires_explicit_insecure_opt_in():
    data = {
        "targets": {"a": {"host": "a", "verify_ssl": False,
                            "auth": {"user": "u", "token_name": "t", "token_value": "v"}}},
    }
    with pytest.raises(ValueError, match="allow_insecure_tls"):
        Config.model_validate(data)
    data["targets"]["a"]["allow_insecure_tls"] = True
    assert Config.model_validate(data).targets["a"].verify_ssl is False


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


@pytest.mark.parametrize("field, value", [
    ("ssh", {"user": "root", "key_file": "/tmp/key"}),
    ("api_tunnel", {"enabled": True, "ssh_host": "jump", "local_port": 19001}),
])
def test_named_targets_reject_legacy_top_level_connection_settings(field, value):
    data = {
        "targets": {
            "cluster": {
                "host": "cluster.example",
                "auth": {"user": "u", "token_name": "t", "token_value": "v"},
            },
        },
        field: value,
    }
    with pytest.raises(ValueError, match=f"{field}.*targets"):
        Config.model_validate(data)


def test_distinct_ssh_gateways_may_share_remote_destination():
    """Two targets reaching the same remote host through different SSH
    services (different user/port) are a valid configuration."""
    auth = {"user": "root@pam", "token_name": "t", "token_value": "v"}

    def target(local_port, ssh_user, ssh_port):
        return {
            "host": "node.example",
            "auth": auth,
            "api_tunnel": {
                "enabled": True,
                "ssh_host": "gw.example",
                "local_host": "127.0.0.1",
                "local_port": local_port,
                "remote_host": "127.0.0.1",
                "remote_port": 8006,
            },
            "ssh": {"user": ssh_user, "port": ssh_port},
        }

    config = Config.model_validate(
        {
            "targets": {
                "a": target(18007, "opa", 22),
                "b": target(18008, "opb", 2222),
            }
        }
    )
    assert set(config.targets) == {"a", "b"}


def test_identical_ssh_gateways_still_reject_shared_remote_destination():
    auth = {"user": "root@pam", "token_name": "t", "token_value": "v"}

    def target(local_port):
        return {
            "host": "node.example",
            "auth": auth,
            "api_tunnel": {
                "enabled": True,
                "ssh_host": "gw.example",
                "local_host": "127.0.0.1",
                "local_port": local_port,
                "remote_host": "127.0.0.1",
                "remote_port": 8006,
            },
            "ssh": {"user": "same", "port": 22},
        }

    with pytest.raises(ValueError, match="remote endpoint"):
        Config.model_validate({"targets": {"a": target(18007), "b": target(18008)}})
