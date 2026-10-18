"""Migration preflight fails closed without critical evidence."""
import json
from unittest.mock import MagicMock
import pytest
from proxmox_mcp.tools.containers import ContainerTools


def api_for_preflight():
    api = MagicMock()
    api.nodes.get.return_value = [{"node": "sam", "status": "online"}, {"node": "six", "status": "online"}]
    api.nodes.return_value.lxc.return_value.config.get.return_value = {
        "rootfs": "local-lvm:vm-115-disk-0,size=40G", "memory": 8192,
    }
    api.nodes.return_value.lxc.return_value.status.current.get.return_value = {"status": "stopped"}
    api.nodes.return_value.storage.return_value.status.get.return_value = {
        "active": 1, "enabled": 1, "content": "images,rootdir", "avail": 100 * 1024**3,
    }
    api.nodes.return_value.storage.get.return_value = [{"storage": "local", "content": "backup"}]
    api.nodes.return_value.storage.return_value.content.get.return_value = [{"vmid": 115, "volid": "local:backup/test"}]
    api.cluster.ha.resources.get.return_value = []
    return api


def check(api, **kwargs):
    return json.loads(ContainerTools(api).preflight_container_migration("sam", "115", "six", **kwargs)[0].text)


def test_preflight_with_complete_evidence():
    result = check(api_for_preflight())
    assert result["ready"] is True
    assert result["checks"]["backup_found"] is True


@pytest.mark.parametrize("runtime", [{}, {"status": "unknown"}, []])
def test_unknown_runtime_never_reports_ready(runtime):
    api = api_for_preflight()
    api.nodes.return_value.lxc.return_value.status.current.get.return_value = runtime
    assert check(api)["ready"] is False


@pytest.mark.parametrize("resources", [{}, None, [None], [{"sid": "unrecognized"}]])
def test_malformed_ha_inventory_never_reports_ready(resources):
    api = api_for_preflight()
    api.cluster.ha.resources.get.return_value = resources
    assert check(api)["ready"] is False


def test_fractional_rootfs_size_is_parsed():
    api = api_for_preflight()
    api.nodes.return_value.lxc.return_value.config.get.return_value["rootfs"] = "local-lvm:vm-115-disk-0,size=4.5G"
    result = check(api)
    assert result["ready"] is True
    assert result["checks"]["provisioned_rootfs_bytes"] == 4.5 * 1024**3


def test_unused_volume_requires_manual_inspection():
    api = api_for_preflight()
    api.nodes.return_value.lxc.return_value.config.get.return_value["unused0"] = "other:vm-115-disk-1"
    assert check(api)["ready"] is False


def test_unrelated_backup_is_not_rollback_evidence():
    api = api_for_preflight()
    api.nodes.return_value.storage.return_value.content.get.return_value = [{"vmid": 116, "volid": "local:backup/ct-116"}]
    assert check(api)["ready"] is False


@pytest.mark.parametrize("path,value", [
    ("nodes", {}), ("config", []),
])
def test_primary_malformed_evidence_is_an_error(path, value):
    api = api_for_preflight()
    if path == "nodes":
        api.nodes.get.return_value = value
    else:
        api.nodes.return_value.lxc.return_value.config.get.return_value = value
    with pytest.raises(ValueError, match="Unexpected"):
        check(api)


@pytest.mark.parametrize("field,value", [
    ("status", []), ("content", {"rootdir": True}), ("avail", float("nan")),
    ("avail", float("inf")), ("avail", True), ("active", "0"), ("enabled", "0"),
])
def test_invalid_storage_evidence_blocks_readiness(field, value):
    api = api_for_preflight()
    if field == "status":
        api.nodes.return_value.storage.return_value.status.get.return_value = value
    else:
        api.nodes.return_value.storage.return_value.status.get.return_value[field] = value
    assert check(api)["ready"] is False


@pytest.mark.parametrize("stores", [None, [None], [{"storage": "bad/path", "content": "backup"}]])
def test_malformed_backup_store_inventory_is_unknown(stores):
    api = api_for_preflight()
    api.nodes.return_value.storage.get.return_value = stores
    result = check(api)
    assert result["ready"] is False
    assert any("Backup inventory" in unknown for unknown in result["unknowns"])


def test_string_downtime_confirmation_is_rejected():
    with pytest.raises(ValueError, match="boolean"):
        check(api_for_preflight(), allow_downtime="false")


def test_running_container_requires_downtime():
    api = api_for_preflight()
    api.nodes.return_value.lxc.return_value.status.current.get.return_value = {"status": "running"}
    result = check(api)
    assert result["ready"] is False
    assert any("downtime" in x for x in result["blockers"])


def test_extra_mount_and_insufficient_disk_block_migration():
    api = api_for_preflight()
    api.nodes.return_value.lxc.return_value.config.get.return_value["mp0"] = "/host/data,mp=/data"
    api.nodes.return_value.storage.return_value.status.get.return_value["avail"] = 3 * 1024**3
    result = check(api)
    assert result["ready"] is False
    assert any("mount" in x for x in result["blockers"])
    assert any("capacity" in x for x in result["blockers"])


def test_backup_unknown_fails_closed():
    api = api_for_preflight()
    api.nodes.return_value.storage.get.side_effect = PermissionError("backup inventory denied")
    result = check(api)
    assert result["ready"] is False
    assert any("Backup" in x for x in result["unknowns"])


def test_ha_membership_blocks_migration():
    api = api_for_preflight()
    api.cluster.ha.resources.get.return_value = [{"sid": "ct:115"}]
    result = check(api)
    assert result["ready"] is False
    assert any("HA" in x for x in result["blockers"])


def test_same_node_is_rejected():
    with pytest.raises(ValueError):
        ContainerTools(MagicMock()).preflight_container_migration("sam", "115", "sam")


def test_non_numeric_container_id_rejected():
    with pytest.raises(ValueError, match="numeric"):
        ContainerTools(MagicMock()).preflight_container_migration("sam", "oops", "six")


def test_offline_destination_fails_without_fetching_guest_config():
    api = api_for_preflight()
    api.nodes.get.return_value = [{"node": "sam", "status": "online"}, {"node": "six", "status": "offline"}]
    result = check(api)
    assert result["ready"] is False
    assert "six" in result["blockers"][0]
    api.nodes.return_value.lxc.return_value.config.get.assert_not_called()


def test_invalid_rootfs_and_missing_size_block_readiness():
    api = api_for_preflight()
    api.nodes.return_value.lxc.return_value.config.get.return_value = {"rootfs": "invalid"}
    result = check(api)
    assert result["ready"] is False
    assert any("parseable" in x for x in result["blockers"])
    assert any("size" in x for x in result["unknowns"])


def test_custom_device_and_container_lock_are_blockers():
    api = api_for_preflight()
    config = api.nodes.return_value.lxc.return_value.config.get.return_value
    config["dev0"] = "/dev/null"
    config["lock"] = "migrate"
    result = check(api)
    assert any("devices" in x for x in result["blockers"])
    assert any("locked" in x for x in result["blockers"])


def test_running_container_confirmed_downtime_reports_warning():
    api = api_for_preflight()
    api.nodes.return_value.lxc.return_value.status.current.get.return_value = {"status": "running"}
    result = check(api, allow_downtime=True)
    assert result["ready"] is True
    assert any("downtime" in x for x in result["warnings"])


def test_unavailable_guest_runtime_fails_closed():
    api = api_for_preflight()
    api.nodes.return_value.lxc.return_value.status.current.get.side_effect = PermissionError("denied")
    result = check(api)
    assert result["ready"] is False
    assert any("running state" in x for x in result["unknowns"])


def test_destination_storage_inactive_and_unknown_available_bytes():
    api = api_for_preflight()
    api.nodes.return_value.storage.return_value.status.get.return_value = {
        "active": 0, "enabled": 1, "content": ["images"], "avail": None,
    }
    result = check(api)
    assert result["ready"] is False
    assert any("inactive" in x for x in result["blockers"])
    assert any("available bytes" in x for x in result["unknowns"])


def test_unreachable_storage_status_is_unknown():
    api = api_for_preflight()
    api.nodes.return_value.storage.return_value.status.get.side_effect = ConnectionError("unreachable")
    result = check(api)
    assert result["ready"] is False
    assert any("storage status" in x for x in result["unknowns"])


def test_ha_query_error_does_not_report_ready():
    api = api_for_preflight()
    api.cluster.ha.resources.get.side_effect = PermissionError("denied")
    result = check(api)
    assert result["ready"] is False
    assert any("HA" in x for x in result["unknowns"])


def test_backup_unlisted_storage_and_missing_backup():
    api = api_for_preflight()
    api.nodes.return_value.storage.get.return_value = [{"storage": "local", "content": "images"}]
    result = check(api)
    assert result["ready"] is False
    assert any("No backup inventory" in x for x in result["unknowns"])

    api = api_for_preflight()
    api.nodes.return_value.storage.return_value.content.get.return_value = []
    result = check(api)
    assert result["ready"] is False
    assert any("No matching backup" in x for x in result["blockers"])


def test_primary_cluster_failure_surfaces_explicit_error():
    api = api_for_preflight()
    api.nodes.get.side_effect = RuntimeError("cluster unavailable")
    with pytest.raises(RuntimeError, match="cluster unavailable"):
        check(api)


def test_preflight_mcp_registry_dispatch():
    from types import SimpleNamespace
    from proxmox_mcp.services.builtin_tool_plugins import ContainerToolsPlugin

    registered = {}
    def register(**kwargs):
        def decorator(fn):
            registered[fn.__name__] = fn
            return fn
        return decorator

    server = SimpleNamespace(
        tool_registry=SimpleNamespace(tool=register),
        config=SimpleNamespace(ssh=None), logger=MagicMock(),
    )
    plugin = ContainerToolsPlugin()
    plugin._wrap_sync = MagicMock(return_value=lambda **kwargs: kwargs)
    plugin.register(server)
    dispatched = registered["preflight_container_migration"](
        node="sam", vmid="115", destination="six", allow_downtime=True, target="default"
    )
    assert dispatched["destination"] == "six"
    assert dispatched["allow_downtime"] is True
    assert plugin._wrap_sync.call_args.args[1] == "preflight_container_migration"
