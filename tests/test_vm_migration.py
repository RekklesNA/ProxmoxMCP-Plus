"""QEMU migration must reject incomplete evidence before submitting any task."""

import json
from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from proxmoxer.core import ResourceException

from proxmox_mcp.config.models import CommandPolicyConfig
from proxmox_mcp.security.command_policy import CommandPolicyGate
from proxmox_mcp.tools.vm import VMTools


GIB = 1024**3
UPID = "UPID:one:00000001:00000002:00000003:qmigrate:105:root@pam:"
CONFIRMATIONS = {
    "confirm_migration": True,
    "confirm_backup_verified": True,
    "confirm_workload_drained": True,
    "confirm_cpu_compatibility": True,
}


@pytest.fixture
def migration_api():
    api = MagicMock()
    api.nodes.get.return_value = [
        {"node": "one", "status": "online"},
        {"node": "two", "status": "online"},
    ]
    api.cluster.resources.get.return_value = [
        {"vmid": 105, "type": "qemu", "node": "one"},
    ]
    api.cluster.ha.resources.get.return_value = []
    guest = api.nodes.return_value.qemu.return_value
    guest.config.get.return_value = {
        "scsi0": "local-lvm:vm-105-disk-0,size=32G",
        "net0": "virtio=02:00:00:00:01:05,bridge=vmbr0",
        "cpu": "x86-64-v2-AES",
        "memory": 2048,
    }
    guest.status.current.get.return_value = {"status": "stopped"}
    # This is the native GET /nodes/one/qemu/105/migrate response, whose
    # volume list includes current, pending and snapshot references.
    guest.migrate.get.return_value = {
        "running": 0,
        "allowed_nodes": ["two"],
        "not_allowed_nodes": {},
        "local_disks": [{
            "volid": "local-lvm:vm-105-disk-0", "size": 32 * GIB,
            "cdrom": 0, "is_unused": 0, "is_cloudinit": 0,
            "shared": 0, "is_vmstate": 0, "is_attached": 1,
        }],
        "local_resources": [],
        "mapped-resources": [],
        "mapped-resource-info": {},
    }
    guest.migrate.post.return_value = UPID
    api.nodes.return_value.storage.get.return_value = [{
        "storage": "local-lvm", "active": 1, "enabled": 1,
        "content": "images,rootdir", "avail": 100 * GIB, "shared": 0,
    }]
    api.nodes.return_value.network.get.return_value = [
        {"iface": "vmbr0", "type": "bridge", "active": 1},
    ]
    return api


def assessment(api):
    result = VMTools(api).preflight_vm_migration("one", "105", "two")
    return json.loads(result[0].text)


def migrate(api, *, store=None, **overrides):
    confirmations = {**CONFIRMATIONS, **overrides}
    result = VMTools(api, job_store=store).migrate_vm(
        "one", "105", "two", **confirmations
    )
    return json.loads(result[0].text)


def test_preflight_reads_native_target_preconditions_without_mutating(migration_api):
    result = assessment(migration_api)
    assert result["ready"] is True
    assert result["mode"] == "offline"
    migration_api.nodes.return_value.qemu.return_value.migrate.get.assert_called_once_with(
        target="two"
    )
    migration_api.nodes.return_value.qemu.return_value.migrate.post.assert_not_called()
    assert result["warnings"]  # Observation does not reserve space or verify backups.


@pytest.mark.parametrize("runtime", [{}, None, {"status": "running"}, {"status": "unknown"}])
def test_missing_or_running_guest_status_never_reports_ready(migration_api, runtime):
    migration_api.nodes.return_value.qemu.return_value.status.current.get.return_value = runtime
    assert assessment(migration_api)["ready"] is False


@pytest.mark.parametrize("inventory", [
    [], None, {}, [None],
    [{"vmid": 105, "type": "lxc", "node": "one"}],
    [{"vmid": 105, "type": "qemu", "node": "other"}],
    [{"vmid": 105, "type": "qemu", "node": "one"}] * 2,
])
def test_vm_ownership_must_be_unambiguous(migration_api, inventory):
    migration_api.cluster.resources.get.return_value = inventory
    assert assessment(migration_api)["ready"] is False


@pytest.mark.parametrize("node,vmid,destination", [
    ("one", "00105", "two"), ("one", "oops", "two"),
    ("one", "99", "two"), ("one", "1000000000", "two"),
    ("one/../other", "105", "two"), ("one", "105", "two/tasks"),
    ("one", "105", "one"), ("", "105", "two"),
])
def test_invalid_migration_identity_is_rejected_without_api_access(migration_api, node, vmid, destination):
    with pytest.raises(ValueError):
        VMTools(migration_api).preflight_vm_migration(node, vmid, destination)
    migration_api.nodes.assert_not_called()
    migration_api.nodes.get.assert_not_called()


@pytest.mark.parametrize("inventory", [None, {}, [None], [{"sid": "unrecognized"}]])
def test_malformed_ha_inventory_is_not_proof_of_no_membership(migration_api, inventory):
    migration_api.cluster.ha.resources.get.return_value = inventory
    assert assessment(migration_api)["ready"] is False


def test_ha_managed_vm_never_submits_direct_migration(migration_api):
    migration_api.cluster.ha.resources.get.return_value = [{"sid": "vm:105"}]
    with pytest.raises(ValueError):
        migrate(migration_api)
    migration_api.nodes.return_value.qemu.return_value.migrate.post.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("lock", "backup"), ("template", 1),
    ("hostpci0", "0000:01:00.0"), ("usb0", "host=1234:5678"),
    ("serial0", "/dev/ttyS0"), ("parallel0", "/dev/parport0"),
    ("virtiofs0", "dirid=host-data"), ("ivshmem", "size=32"),
    ("unused0", "local-lvm:vm-105-disk-1"),
    ("args", "-drive file=/host/local.img"),
    ("cicustom", "user=local:snippets/user.yaml"),
    ("hookscript", "local:snippets/start-hook.pl"),
    ("vmstate", "local-lvm:vm-105-state-suspended"),
])
def test_unsupported_local_resources_require_manual_review(migration_api, field, value):
    migration_api.nodes.return_value.qemu.return_value.config.get.return_value[field] = value
    assert assessment(migration_api)["ready"] is False


def test_serial_socket_is_recreated_by_proxmox_on_destination(migration_api):
    migration_api.nodes.return_value.qemu.return_value.config.get.return_value["serial0"] = "socket"
    assert assessment(migration_api)["ready"] is True


@pytest.mark.parametrize("field,value", [
    ("avail", float("nan")), ("avail", float("inf")),
    ("avail", -1), ("avail", None), ("avail", True),
    ("active", "1"), ("enabled", 0),
    ("content", {"images": True}),
])
def test_malformed_storage_evidence_fails_closed(migration_api, field, value):
    migration_api.nodes.return_value.storage.get.return_value[0][field] = value
    assert assessment(migration_api)["ready"] is False


def test_local_disk_requires_enough_destination_capacity(migration_api):
    migration_api.nodes.return_value.storage.get.return_value[0]["avail"] = GIB
    with pytest.raises(ValueError):
        migrate(migration_api)
    migration_api.nodes.return_value.qemu.return_value.migrate.post.assert_not_called()


def test_shared_disk_does_not_consume_its_provisioned_size_again(migration_api):
    migration_api.nodes.return_value.storage.get.return_value[0].update(shared=1, avail=GIB)
    migration_api.nodes.return_value.qemu.return_value.migrate.get.return_value["local_disks"] = []
    assert assessment(migration_api)["ready"] is True


@pytest.mark.parametrize("network", [None, "", {"bridge": "vmbr0"}])
def test_unparseable_guest_network_never_reports_ready(migration_api, network):
    migration_api.nodes.return_value.qemu.return_value.config.get.return_value["net0"] = network
    assert assessment(migration_api)["ready"] is False


def test_destination_must_have_required_guest_bridge(migration_api):
    migration_api.nodes.return_value.network.get.return_value = []
    assert assessment(migration_api)["ready"] is False


@pytest.mark.parametrize("native", [None, [], {}, "ready"])
def test_missing_native_preconditions_are_not_a_success(migration_api, native):
    migration_api.nodes.return_value.qemu.return_value.migrate.get.return_value = native
    assert assessment(migration_api)["ready"] is False


@pytest.mark.parametrize("field,value", [
    ("running", "0"), ("running", None), ("running", 1),
    ("allowed_nodes", "two"), ("allowed_nodes", [None]),
    ("not_allowed_nodes", []),
    ("local_disks", {}), ("local_disks", [None]),
    ("local_resources", {}), ("local_resources", [None]),
])
def test_malformed_native_preconditions_cannot_authorize_submission(migration_api, field, value):
    native = migration_api.nodes.return_value.qemu.return_value.migrate.get.return_value
    native[field] = value
    assert assessment(migration_api)["ready"] is False


@pytest.mark.parametrize("field", ["running", "allowed_nodes", "local_disks", "local_resources"])
def test_missing_native_safety_fields_are_unknown(migration_api, field):
    native = migration_api.nodes.return_value.qemu.return_value.migrate.get.return_value
    native.pop(field)
    assert assessment(migration_api)["ready"] is False


@pytest.mark.parametrize("blocker", [
    {"unavailable_storages": ["local-lvm"]},
    {"unavailable-resources": ["virtiofs0"]},
    {"blocking-ha-resources": [{"sid": "vm:106", "cause": "resource-affinity"}]},
])
def test_native_destination_blockers_win_over_allowed_node_list(migration_api, blocker):
    native = migration_api.nodes.return_value.qemu.return_value.migrate.get.return_value
    native["not_allowed_nodes"] = {"two": blocker}
    with pytest.raises(ValueError):
        migrate(migration_api)
    migration_api.nodes.return_value.qemu.return_value.migrate.post.assert_not_called()


def test_native_target_must_explicitly_be_allowed(migration_api):
    migration_api.nodes.return_value.qemu.return_value.migrate.get.return_value["allowed_nodes"] = ["other"]
    assert assessment(migration_api)["ready"] is False


def test_native_local_resources_block_even_when_config_missed_them(migration_api):
    migration_api.nodes.return_value.qemu.return_value.migrate.get.return_value["local_resources"] = ["ivshmem"]
    assert assessment(migration_api)["ready"] is False


def test_native_local_iso_is_not_silently_ignored(migration_api):
    guest = migration_api.nodes.return_value.qemu.return_value
    guest.config.get.return_value["ide2"] = "local:iso/rescue.iso,media=cdrom"
    guest.migrate.get.return_value["local_disks"].append({
        "volid": "local:iso/rescue.iso", "cdrom": 1, "is_unused": 0,
    })
    assert assessment(migration_api)["ready"] is False


def test_generated_cloudinit_can_be_recreated_without_a_reported_size(migration_api):
    guest = migration_api.nodes.return_value.qemu.return_value
    guest.config.get.return_value["ide2"] = "local-lvm:vm-105-cloudinit,media=cdrom"
    guest.migrate.get.return_value["local_disks"].append({
        "volid": "local-lvm:vm-105-cloudinit", "cdrom": 1,
        "is_unused": 0, "is_cloudinit": 1, "shared": 0,
        "is_vmstate": 0, "is_attached": 1,
    })
    assert assessment(migration_api)["ready"] is True


@pytest.mark.parametrize("image_format", ["qcow2", "raw"])
def test_directory_cloudinit_uses_image_storage_instead_of_iso_content(migration_api, image_format):
    guest = migration_api.nodes.return_value.qemu.return_value
    volid = f"local:105/vm-105-cloudinit.{image_format}"
    guest.config.get.return_value["ide2"] = f"{volid},media=cdrom"
    guest.migrate.get.return_value["local_disks"].append({
        "volid": volid, "cdrom": 1, "is_cloudinit": 1,
        "is_unused": 0, "shared": 0, "is_vmstate": 0, "is_attached": 1,
    })
    migration_api.nodes.return_value.storage.get.return_value.append({
        "storage": "local", "active": 1, "enabled": 1,
        "content": "images", "avail": 100 * GIB, "shared": 0,
    })
    assert assessment(migration_api)["ready"] is True


def test_native_larger_disk_size_cannot_be_hidden_by_stale_flat_config(migration_api):
    # Native enumeration can observe a resize or a larger pending/snapshot
    # reference after the flat configuration was read. Provision for the larger
    # observation rather than reporting enough space for only the older 32G.
    migration_api.nodes.return_value.qemu.return_value.migrate.get.return_value["local_disks"][0]["size"] = 200 * GIB
    result = assessment(migration_api)
    assert result["ready"] is False
    assert result["checks"]["disk_bytes_by_storage"]["local-lvm"] >= 200 * GIB


@pytest.mark.parametrize("field,value", [
    ("volid", None), ("size", None), ("size", -1),
    ("size", float("nan")), ("size", float("inf")), ("size", True),
    ("cdrom", "0"), ("is_unused", "0"), ("is_unused", 1),
])
def test_native_disk_metadata_must_support_safe_capacity_accounting(migration_api, field, value):
    migration_api.nodes.return_value.qemu.return_value.migrate.get.return_value["local_disks"][0][field] = value
    assert assessment(migration_api)["ready"] is False


def test_snapshot_only_local_disk_cannot_escape_capacity_review(migration_api):
    # Native preconditions can reveal disks referenced only in snapshots or
    # pending config, which are absent from the flat current config response.
    disk = deepcopy(migration_api.nodes.return_value.qemu.return_value.migrate.get.return_value["local_disks"][0])
    disk.update(volid="local-lvm:vm-105-disk-1", size=200 * GIB, is_attached=0)
    migration_api.nodes.return_value.qemu.return_value.migrate.get.return_value["local_disks"].append(disk)
    assert assessment(migration_api)["ready"] is False


def test_native_precondition_permission_failure_never_submits(migration_api):
    migration_api.nodes.return_value.qemu.return_value.migrate.get.side_effect = ResourceException(
        403, "Forbidden", "VM.Migrate permission required"
    )
    with pytest.raises(ValueError):
        migrate(migration_api)
    migration_api.nodes.return_value.qemu.return_value.migrate.post.assert_not_called()


@pytest.mark.parametrize("field", list(CONFIRMATIONS))
@pytest.mark.parametrize("value", [False, 1, "true"])
def test_each_safety_confirmation_requires_literal_true_before_api_reads(migration_api, field, value):
    with pytest.raises(ValueError):
        migrate(migration_api, **{field: value})
    migration_api.nodes.assert_not_called()
    migration_api.nodes.get.assert_not_called()


def test_submits_one_offline_task_and_registers_non_retryable_job(migration_api):
    store = MagicMock()
    store.register_task.return_value = {"job_id": "migration-105"}
    result = migrate(migration_api, store=store)
    assert result["success"] is True
    assert result["status"] == "submitted"
    assert result["task_id"] == UPID
    assert result["job_id"] == "migration-105"
    migration_api.nodes.return_value.qemu.return_value.migrate.post.assert_called_once_with(
        target="two", online=0, **{"with-local-disks": 1}
    )
    registration = store.register_task.call_args.kwargs
    assert registration["node"] == "one"
    assert registration["upid"] == UPID
    assert registration["retry_spec"] is None
    assert registration["retry_factory"] is None


@pytest.mark.parametrize("response", [None, {}, "", "not-a-UPID"])
def test_invalid_submission_response_is_uncertain_and_never_retried(migration_api, response):
    migration_api.nodes.return_value.qemu.return_value.migrate.post.return_value = response
    result = migrate(migration_api)
    assert result["code"] == "SUBMISSION_UNCERTAIN"
    assert result["success"] is False
    assert result["retryable"] is False
    migration_api.nodes.return_value.qemu.return_value.migrate.post.assert_called_once()


@pytest.mark.parametrize("error", [ConnectionError("response lost"), ResourceException(503, "Unavailable", "gateway failed")])
def test_lost_submission_response_is_uncertain_and_never_retried(migration_api, error):
    migration_api.nodes.return_value.qemu.return_value.migrate.post.side_effect = error
    result = migrate(migration_api)
    assert result["code"] == "SUBMISSION_UNCERTAIN"
    assert result["retryable"] is False
    migration_api.nodes.return_value.qemu.return_value.migrate.post.assert_called_once()


def test_definite_api_rejection_is_not_reported_as_possible_submission(migration_api):
    migration_api.nodes.return_value.qemu.return_value.migrate.post.side_effect = ResourceException(
        403, "Forbidden", "VM.Migrate permission required"
    )
    with pytest.raises((ResourceException, RuntimeError, ValueError), match="permission required"):
        migrate(migration_api)
    migration_api.nodes.return_value.qemu.return_value.migrate.post.assert_called_once()


def test_local_tracking_failure_preserves_submitted_remote_task(migration_api):
    store = MagicMock()
    store.register_task.side_effect = OSError("local job database unavailable")
    result = migrate(migration_api, store=store)
    assert result["success"] is True
    assert result["status"] == "submitted"
    assert result["task_id"] == UPID
    assert result["job_id"] is None
    migration_api.nodes.return_value.qemu.return_value.migrate.post.assert_called_once()


def test_default_high_risk_policy_covers_vm_migration():
    gate = CommandPolicyGate(CommandPolicyConfig(
        high_risk_mode="enforce", high_risk_require_approval_token=True,
        high_risk_approval_token="migration-approval",
    ))
    assert gate.evaluate_operation("migrate_vm").allowed is False
    assert gate.evaluate_operation("migrate_vm", approval_token="migration-approval").allowed is True


def assert_blocked_before_submission(api, *, unknown=False):
    """A failed assessment must also prevent the mutating tool from posting."""
    result = assessment(api)
    assert result["ready"] is False
    if unknown:
        assert result["unknowns"]
    with pytest.raises(ValueError):
        migrate(api)
    api.nodes.return_value.qemu.return_value.migrate.post.assert_not_called()


@pytest.mark.parametrize("nodes", [
    [{"node": "one", "status": "online"}, {"node": "two", "status": "offline"}],
    None, [None],
])
def test_unavailable_or_malformed_nodes_prevent_migration(migration_api, nodes):
    migration_api.nodes.get.return_value = nodes
    assert_blocked_before_submission(migration_api)


def test_node_inventory_permission_failure_is_unknown_not_online(migration_api):
    migration_api.nodes.get.side_effect = PermissionError("node inventory denied")
    assert_blocked_before_submission(migration_api, unknown=True)


@pytest.mark.parametrize("config", [{}, []])
def test_missing_guest_configuration_is_unknown_and_blocks_submission(migration_api, config):
    migration_api.nodes.return_value.qemu.return_value.config.get.return_value = config
    assert_blocked_before_submission(migration_api, unknown=True)


def test_unreadable_guest_configuration_is_unknown_and_blocks_submission(migration_api):
    migration_api.nodes.return_value.qemu.return_value.config.get.side_effect = PermissionError(
        "configuration denied"
    )
    assert_blocked_before_submission(migration_api, unknown=True)


@pytest.mark.parametrize("field,value", [
    ("mapped-resources", {}), ("mapped-resource-info", []),
])
def test_malformed_resource_mapping_evidence_never_authorizes_submission(migration_api, field, value):
    migration_api.nodes.return_value.qemu.return_value.migrate.get.return_value[field] = value
    assert_blocked_before_submission(migration_api, unknown=True)


@pytest.mark.parametrize("drive", [
    None, [], "unrecognized-volume", "local-lvm:vm-105-disk-0",
    "local-lvm:vm-105-disk-0,size=0G",
])
def test_unaccountable_drive_storage_or_capacity_prevents_submission(migration_api, drive):
    migration_api.nodes.return_value.qemu.return_value.config.get.return_value["scsi0"] = drive
    assert_blocked_before_submission(migration_api, unknown=True)


def test_ejected_cdrom_adds_no_local_iso_dependency(migration_api):
    migration_api.nodes.return_value.qemu.return_value.config.get.return_value["ide2"] = "none,media=cdrom"
    assert assessment(migration_api)["ready"] is True
    migration_api.nodes.return_value.qemu.return_value.migrate.post.assert_not_called()


def test_configuration_without_any_managed_volume_requires_manual_review(migration_api):
    guest = migration_api.nodes.return_value.qemu.return_value
    guest.config.get.return_value = {"cpu": "x86-64-v2-AES", "memory": 2048}
    guest.migrate.get.return_value["local_disks"] = []
    assert_blocked_before_submission(migration_api, unknown=True)


def test_duplicate_destination_storage_records_are_not_unambiguous_capacity_evidence(migration_api):
    stores = migration_api.nodes.return_value.storage.get.return_value
    stores.append(deepcopy(stores[0]))
    assert_blocked_before_submission(migration_api, unknown=True)


def test_destination_storage_must_support_the_existing_disk_content(migration_api):
    migration_api.nodes.return_value.storage.get.return_value[0]["content"] = "backup,iso"
    assert_blocked_before_submission(migration_api)


def test_shared_destination_cannot_override_native_local_disk_evidence(migration_api):
    migration_api.nodes.return_value.storage.get.return_value[0]["shared"] = 1
    assert_blocked_before_submission(migration_api, unknown=True)


def test_malformed_network_inventory_is_unknown_and_blocks_submission(migration_api):
    migration_api.nodes.return_value.network.get.return_value = None
    assert_blocked_before_submission(migration_api, unknown=True)


def test_unreadable_network_inventory_is_unknown_and_blocks_submission(migration_api):
    migration_api.nodes.return_value.network.get.side_effect = PermissionError("network inventory denied")
    assert_blocked_before_submission(migration_api, unknown=True)
