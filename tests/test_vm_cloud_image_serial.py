"""Submission and mutation boundaries for disk import and serial configuration."""
import json
from unittest.mock import MagicMock

import pytest
from proxmoxer.core import ResourceException

from proxmox_mcp.models.tooling import result_status, result_succeeded
from proxmox_mcp.tools.vm import VMTools


_DEFAULT = object()
UPID = "UPID:six:00000001:00000001:00000001:qmconfig:142:root@pam:"


def _tools(*, status="stopped", config=_DEFAULT, storage=_DEFAULT, imports=_DEFAULT):
    """Preserve explicitly supplied empty/malformed API data for fail-closed tests."""
    api = MagicMock()
    guest = api.nodes.return_value.qemu.return_value
    guest.status.current.get.return_value = {"status": status}
    guest.config.get.return_value = {"digest": "abc"} if config is _DEFAULT else config
    api.nodes.return_value.storage.get.return_value = [
        {"storage": "source", "content": "import", "active": 1},
        {"storage": "local-lvm", "content": "images,rootdir", "active": 1},
    ] if storage is _DEFAULT else storage
    api.nodes.return_value.storage.return_value.content.get.return_value = [
        {"volid": "source:import/debian.qcow2"}
    ] if imports is _DEFAULT else imports
    guest.config.post.return_value = UPID
    return VMTools(api), guest


def _import(tool, **kwargs):
    arguments = dict(node="six", vmid="142", source_volume="source:import/debian.qcow2",
                     destination_storage="local-lvm", confirm_import=True)
    arguments.update(kwargs)
    return tool.import_cloud_image(**arguments)


def _serial(tool, **kwargs):
    arguments = dict(node="six", vmid="142", confirm_display_change=True)
    arguments.update(kwargs)
    return tool.configure_vm_serial_console(**arguments)


def test_serial_requires_confirmation_and_stopped_vm():
    tool, guest = _tools()
    with pytest.raises(ValueError, match="confirm_display_change"):
        tool.configure_vm_serial_console("six", "142")
    guest.config.put.assert_not_called()
    tool, guest = _tools(status="running")
    with pytest.raises(ValueError, match="stopped"):
        _serial(tool)
    guest.config.put.assert_not_called()


def test_serial_does_not_overwrite_existing_serial_device():
    tool, guest = _tools(config={"digest": "abc", "serial0": "/dev/ttyS0"})
    with pytest.raises(ValueError, match="already configured"):
        _serial(tool)
    guest.config.put.assert_not_called()


def test_serial_setup_accepts_wrapper_approval_parameter_and_sets_only_console_fields():
    tool, guest = _tools(config={"digest": "abc", "serial1": "/dev/ttyS1", "boot": "order=scsi0"})
    result = _serial(tool, approval_token="fixture")
    guest.config.put.assert_called_once_with(serial0="socket", vga="serial0", digest="abc")
    assert json.loads(result[0].text)["changed"] is True
    assert result_succeeded(result)


def test_serial_repeated_call_is_idempotent():
    tool, guest = _tools(config={"digest": "abc", "serial0": "socket", "vga": "serial0"})
    assert json.loads(_serial(tool)[0].text)["changed"] is False
    guest.config.put.assert_not_called()


@pytest.mark.parametrize("error", [TimeoutError("response lost"), ResourceException(503, "Unavailable", "unavailable")])
def test_serial_uncertain_submission_is_not_marked_success_or_retried(error):
    tool, guest = _tools()
    guest.config.put.side_effect = error
    result = _serial(tool)
    payload = json.loads(result[0].text)
    assert payload["code"] == "SUBMISSION_UNCERTAIN"
    assert payload["retryable"] is False
    assert not result_succeeded(result)
    guest.config.put.assert_called_once()


def test_serial_known_rejection_is_reported_as_error():
    tool, guest = _tools()
    guest.config.put.side_effect = ResourceException(403, "Forbidden", "permission denied")
    with pytest.raises((ResourceException, ValueError, RuntimeError)):
        _serial(tool)
    guest.config.put.assert_called_once()


@pytest.mark.parametrize("configure", [_serial, _import], ids=["serial", "import"])
@pytest.mark.parametrize("config", [{}, None, [], {"digest": ""}, {"digest": None}, {"digest": 1}])
def test_mutations_require_a_readable_configuration_and_nonempty_digest(configure, config):
    tool, guest = _tools(config=config)
    with pytest.raises(ValueError):
        configure(tool)
    guest.config.put.assert_not_called()
    guest.config.post.assert_not_called()


@pytest.mark.parametrize("configure", [_serial, _import], ids=["serial", "import"])
@pytest.mark.parametrize("extra", [{"template": 1}, {"lock": "backup"}, {"lock": "migrate"}])
def test_templates_and_locked_guests_cannot_be_mutated(configure, extra):
    tool, guest = _tools(config={"digest": "abc", **extra})
    with pytest.raises(ValueError):
        configure(tool)
    guest.config.put.assert_not_called()
    guest.config.post.assert_not_called()


@pytest.mark.parametrize("configure", [_serial, _import], ids=["serial", "import"])
@pytest.mark.parametrize("status", ["running", "paused", "unknown", None])
def test_only_known_stopped_guests_can_be_mutated(configure, status):
    tool, guest = _tools(status=status)
    with pytest.raises(ValueError, match="stopped"):
        configure(tool)
    guest.config.put.assert_not_called()
    guest.config.post.assert_not_called()


@pytest.mark.parametrize("configure", [_serial, _import], ids=["serial", "import"])
@pytest.mark.parametrize("arguments", [
    {"node": "../six"}, {"node": "six/qemu/142"}, {"node": "six\n"},
    {"vmid": "0142"}, {"vmid": "142/../../"}, {"vmid": "99"}, {"vmid": "1000000000"},
])
def test_invalid_guest_identifiers_are_rejected_before_api_access(configure, arguments):
    tool, guest = _tools()
    with pytest.raises(ValueError):
        configure(tool, **arguments)
    tool.proxmox.nodes.assert_not_called()
    guest.config.put.assert_not_called()
    guest.config.post.assert_not_called()


def test_import_requires_explicit_confirmation():
    tool, guest = _tools()
    with pytest.raises(ValueError, match="confirm_import"):
        _import(tool, confirm_import=False)
    guest.config.post.assert_not_called()


@pytest.mark.parametrize("source", [
    "../../etc/passwd", "/var/lib/vz/import/debian.qcow2", "https://example.com/disk.qcow2",
    "source:import/../debian.qcow2", "source:import/a/debian.qcow2",
    "source:import/debian.qcow2,backup=0", "source:import/debian.qcow2\n",
    "source:import/debian.ova", "source:import/debian.qcow2.gz",
])
def test_import_rejects_urls_paths_archives_and_drive_option_injection(source):
    tool, guest = _tools()
    with pytest.raises(ValueError, match="source_volume"):
        _import(tool, source_volume=source)
    guest.config.post.assert_not_called()


@pytest.mark.parametrize("slot", ["scsi31", "scsi01", "virtio0", "scsi1,discard=on", "scsi1\n"])
def test_import_rejects_invalid_disk_slots(slot):
    tool, guest = _tools()
    with pytest.raises(ValueError):
        _import(tool, disk_device=slot)
    guest.config.post.assert_not_called()


@pytest.mark.parametrize("slot", ["scsi0", "scsi1", "scsi30"])
def test_import_refuses_to_overwrite_any_supported_slot(slot):
    tool, guest = _tools(config={"digest": "abc", slot: "local-lvm:vm-142-disk-1"})
    with pytest.raises(ValueError, match="already in use"):
        _import(tool, disk_device=slot)
    guest.config.post.assert_not_called()


@pytest.mark.parametrize("destination", ["../local-lvm", "local-lvm:0", "local-lvm,format=raw", "local-lvm\n"])
def test_import_rejects_destination_storage_option_injection(destination):
    tool, guest = _tools()
    with pytest.raises(ValueError):
        _import(tool, destination_storage=destination)
    guest.config.post.assert_not_called()


@pytest.mark.parametrize("storage", [None, {}, [], [None], [{"storage": "source", "content": "import", "active": 1}]])
def test_import_requires_available_source_and_destination_storage(storage):
    tool, guest = _tools(storage=storage)
    with pytest.raises(ValueError):
        _import(tool)
    guest.config.post.assert_not_called()


@pytest.mark.parametrize("pool,field,value", [
    ("source", "active", 0), ("source", "content", "images"),
    ("local-lvm", "active", 0), ("local-lvm", "content", "rootdir"),
])
def test_import_checks_storage_activity_and_content_type(pool, field, value):
    tool, guest = _tools()
    for entry in tool.proxmox.nodes.return_value.storage.get.return_value:
        if entry["storage"] == pool:
            entry[field] = value
    with pytest.raises(ValueError):
        _import(tool)
    guest.config.post.assert_not_called()


@pytest.mark.parametrize("imports", [None, {}, [], [None], [{"volid": "other:import/debian.qcow2"}],
                                     [{"volid": "source:import/other.qcow2"}]])
def test_import_requires_exact_source_volume_identity(imports):
    tool, guest = _tools(imports=imports)
    with pytest.raises(ValueError, match="Image"):
        _import(tool)
    guest.config.post.assert_not_called()


def test_import_submits_exact_import_from_api_payload_without_changing_boot_disk():
    tool, guest = _tools(config={"digest": "abc", "scsi0": "local-lvm:vm-142-disk-0", "boot": "order=scsi0"})
    result = _import(tool, approval_token="fixture")
    guest.config.post.assert_called_once_with(
        scsi1="local-lvm:0,import-from=source:import/debian.qcow2", digest="abc")
    tool.proxmox.nodes.return_value.storage.return_value.content.get.assert_called_once_with(content="import")
    guest.config.put.assert_not_called()
    assert result_status(result) == "submitted"
    assert json.loads(result[0].text)["task_id"] == UPID


def test_import_accepts_storage_capabilities_as_structured_lists():
    tool, guest = _tools(storage=[
        {"storage": "source", "content": ["import"], "active": 1},
        {"storage": "local-lvm", "content": ["images", "rootdir"], "active": 1},
    ])
    result = _import(tool)
    assert result_succeeded(result)
    assert result_status(result) == "submitted"
    guest.config.post.assert_called_once_with(
        scsi1="local-lvm:0,import-from=source:import/debian.qcow2", digest="abc")


def test_import_rejects_missing_source_volume_before_api_access():
    tool, guest = _tools()
    with pytest.raises(ValueError, match="source_volume"):
        _import(tool, source_volume=None)
    tool.proxmox.nodes.assert_not_called()
    guest.config.post.assert_not_called()


def test_import_rejects_ambiguous_storage_inventory_before_submission():
    tool, guest = _tools()
    inventory = tool.proxmox.nodes.return_value.storage.get.return_value
    inventory.append(dict(inventory[0]))
    with pytest.raises(ValueError, match="ambiguous storage inventory"):
        _import(tool)
    guest.config.post.assert_not_called()


def test_import_rejects_storage_record_without_identity_before_submission():
    tool, guest = _tools()
    tool.proxmox.nodes.return_value.storage.get.return_value.append({"content": "images", "active": 1})
    with pytest.raises(ValueError, match="Storage inventory"):
        _import(tool)
    guest.config.post.assert_not_called()


@pytest.mark.parametrize("response", [None, "", "not-a-task", {"data": UPID}])
def test_invalid_submission_response_is_not_success_or_retryable(response):
    tool, guest = _tools()
    guest.config.post.return_value = response
    result = _import(tool)
    payload = json.loads(result[0].text)
    assert payload["code"] == "SUBMISSION_UNCERTAIN"
    assert payload["retryable"] is False
    assert not result_succeeded(result)
    assert result_status(result) == "error"
    guest.config.post.assert_called_once()


def test_lost_import_response_is_not_retried_or_registered_as_success():
    tool, guest = _tools()
    guest.config.post.side_effect = TimeoutError("response lost")
    tool.job_store = MagicMock()
    result = _import(tool)
    payload = json.loads(result[0].text)
    assert payload["code"] == "SUBMISSION_UNCERTAIN"
    assert payload["retryable"] is False
    assert not result_succeeded(result)
    guest.config.post.assert_called_once()
    tool.job_store.register_task.assert_not_called()


def test_import_server_error_is_uncertain_and_never_retried():
    tool, guest = _tools()
    guest.config.post.side_effect = ResourceException(503, "Unavailable", "upstream connection lost")
    tool.job_store = MagicMock()
    result = _import(tool)
    payload = json.loads(result[0].text)
    assert payload["code"] == "SUBMISSION_UNCERTAIN"
    assert payload["retryable"] is False
    assert not result_succeeded(result)
    assert result_status(result) == "error"
    guest.config.post.assert_called_once()
    tool.job_store.register_task.assert_not_called()


def test_known_remote_rejection_is_not_reported_as_uncertain_submission():
    tool, guest = _tools()
    guest.config.post.side_effect = ResourceException(403, "Forbidden", "permission denied")
    with pytest.raises((ResourceException, ValueError, RuntimeError)):
        _import(tool)
    guest.config.post.assert_called_once()


def test_local_job_store_failure_preserves_remote_task_and_does_not_resubmit():
    tool, guest = _tools()
    tool.job_store = MagicMock()
    tool.job_store.register_task.side_effect = OSError("disk full")
    result = _import(tool)
    payload = json.loads(result[0].text)
    assert payload["status"] == "submitted"
    assert payload["task_id"] == UPID
    assert payload["job_id"] is None
    assert result_status(result) == "submitted"
    guest.config.post.assert_called_once()


def test_import_job_registration_never_enables_automatic_retries():
    tool, guest = _tools()
    tool.job_store = MagicMock()
    tool.job_store.register_task.return_value = {"job_id": "import-job"}
    result = _import(tool)
    registration = tool.job_store.register_task.call_args.kwargs
    assert registration["tool_name"] == "import_cloud_image"
    assert registration["upid"] == UPID
    assert registration.get("retry_factory") is None
    assert registration.get("retry_spec") is None
    assert json.loads(result[0].text)["job_id"] == "import-job"
    guest.config.post.assert_called_once()
