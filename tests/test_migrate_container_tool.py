"""High-risk LXC migration must preflight and register a non-retryable task."""
import json
from unittest.mock import MagicMock
import pytest
from proxmox_mcp.tools.containers import ContainerTools


def migration_api(running=False):
    api = MagicMock()
    api.nodes.get.return_value = [{"node": "sam", "status": "online"}, {"node": "six", "status": "online"}]
    guest = api.nodes.return_value.lxc.return_value
    guest.config.get.return_value = {"rootfs": "local-lvm:vm-115-disk-0,size=40G"}
    guest.status.current.get.return_value = {"status": "running" if running else "stopped"}
    guest.migrate.post.return_value = "UPID:sam:migrate:115"
    api.cluster.ha.resources.get.return_value = []
    api.nodes.return_value.storage.return_value.status.get.return_value = {
        "active": 1, "enabled": 1, "content": "rootdir,images", "avail": 100 * 1024**3,
    }
    api.nodes.return_value.storage.get.return_value = [{"storage": "local", "content": "backup"}]
    api.nodes.return_value.storage.return_value.content.get.return_value = [{"volid": "local:backup/ct-115", "vmid": 115}]
    return api


def test_submits_once_and_registers_job_without_retry():
    api = migration_api()
    store = MagicMock()
    store.register_task.return_value = {"job_id": "job-migrate-115"}
    tool = ContainerTools(api, job_store=store)
    response = json.loads(tool.migrate_container("sam", "115", "six", confirm_migration=True)[0].text)
    assert response["status"] == "submitted"
    assert response["job_id"] == "job-migrate-115"
    api.nodes.return_value.lxc.return_value.migrate.post.assert_called_once_with(
        target="six", restart=0
    )
    details = store.register_task.call_args.kwargs
    assert details["retry_spec"] is None
    assert details["retry_factory"] is None


def test_requires_explicit_confirmation_without_submitting():
    api = migration_api()
    with pytest.raises(ValueError, match="confirm_migration"):
        ContainerTools(api).migrate_container("sam", "115", "six")
    api.nodes.return_value.lxc.return_value.migrate.post.assert_not_called()


def test_default_high_risk_policy_requires_migration_approval():
    from proxmox_mcp.config.models import CommandPolicyConfig
    from proxmox_mcp.security.command_policy import CommandPolicyGate

    gate = CommandPolicyGate(CommandPolicyConfig(
        high_risk_mode="enforce", high_risk_require_approval_token=True,
        high_risk_approval_token="test-approval",
    ))
    assert gate.evaluate_operation("migrate_container").allowed is False
    assert gate.evaluate_operation("migrate_container", approval_token="test-approval").allowed is True


def test_running_guest_requires_downtime_confirmation():
    api = migration_api(running=True)
    with pytest.raises(ValueError, match="confirm_downtime"):
        ContainerTools(api).migrate_container("sam", "115", "six", confirm_migration=True)
    api.nodes.return_value.lxc.return_value.migrate.post.assert_not_called()


def test_insufficient_space_blocks_before_post():
    api = migration_api()
    api.nodes.return_value.storage.return_value.status.get.return_value["avail"] = 2 * 1024**3
    with pytest.raises(ValueError, match="capacity"):
        ContainerTools(api).migrate_container("sam", "115", "six", confirm_migration=True)
    api.nodes.return_value.lxc.return_value.migrate.post.assert_not_called()


def test_ha_guest_blocks_before_post():
    api = migration_api()
    api.cluster.ha.resources.get.return_value = [{"sid": "ct:115"}]
    with pytest.raises(ValueError, match="HA-managed"):
        ContainerTools(api).migrate_container("sam", "115", "six", confirm_migration=True)
    api.nodes.return_value.lxc.return_value.migrate.post.assert_not_called()


def test_missing_backup_blocks_before_post():
    api = migration_api()
    api.nodes.return_value.storage.return_value.content.get.return_value = []
    with pytest.raises(ValueError, match="backup"):
        ContainerTools(api).migrate_container("sam", "115", "six", confirm_migration=True)
    api.nodes.return_value.lxc.return_value.migrate.post.assert_not_called()

@pytest.mark.parametrize("node,vmid,destination,expect", [
    ("sam", "115", "sam", "distinct"),
    ("sam", "oops", "six", "numeric"),
    ("sam", "00115", "six", "canonical"),
    ("sam", "99", "six", "between"),
    ("sam/../other", "115", "six", "distinct"),
])
def test_migration_rejects_unsafe_arguments(node, vmid, destination, expect):
    api = migration_api()
    with pytest.raises(ValueError, match=expect):
        ContainerTools(api).migrate_container(
            node, vmid, destination, confirm_migration=True
        )
    api.nodes.return_value.lxc.return_value.migrate.post.assert_not_called()


def test_migration_fails_if_destination_offline():
    api = migration_api()
    api.nodes.get.return_value[1]["status"] = "offline"
    with pytest.raises(ValueError, match="online"):
        ContainerTools(api).migrate_container("sam", "115", "six", confirm_migration=True)


@pytest.mark.parametrize("config,expected", [
    ({"rootfs": "invalid"}, "rootfs"),
    ({"rootfs": "local-lvm:vm-115-disk-0,size=40G", "lock": "backup"}, "locked"),
    ({"rootfs": "local-lvm:vm-115-disk-0,size=40G", "mp0": "/host,mp=/data"}, "mounts"),
    ({"rootfs": "local-lvm:vm-115-disk-0"}, "size"),
])
def test_migration_rejects_problematic_guest_config(config, expected):
    api = migration_api()
    api.nodes.return_value.lxc.return_value.config.get.return_value = config
    with pytest.raises(ValueError, match=expected):
        ContainerTools(api).migrate_container("sam", "115", "six", confirm_migration=True)
    api.nodes.return_value.lxc.return_value.migrate.post.assert_not_called()


def test_migration_rejects_unknown_runtime():
    api = migration_api()
    api.nodes.return_value.lxc.return_value.status.current.get.return_value = {}
    with pytest.raises(ValueError, match="runtime status"):
        ContainerTools(api).migrate_container("sam", "115", "six", confirm_migration=True)


def test_migration_rejects_incompatible_destination():
    api = migration_api()
    api.nodes.return_value.storage.return_value.status.get.return_value["content"] = "images"
    with pytest.raises(ValueError, match="incompatible"):
        ContainerTools(api).migrate_container("sam", "115", "six", confirm_migration=True)


def test_migration_skips_non_backup_storage():
    api = migration_api()
    api.nodes.return_value.storage.get.return_value = [
        {"storage": "local", "content": "images"},
        {"storage": "backup", "content": "backup"},
    ]
    result = json.loads(ContainerTools(api).migrate_container("sam", "115", "six", confirm_migration=True)[0].text)
    assert result["status"] == "submitted"


@pytest.mark.parametrize("inventory", [None, {}, [None]])
def test_malformed_backup_inventory_blocks_submission(inventory):
    api = migration_api()
    api.nodes.return_value.storage.return_value.content.get.return_value = inventory
    with pytest.raises(ValueError, match="Backup inventory"):
        ContainerTools(api).migrate_container("sam", "115", "six", confirm_migration=True)
    api.nodes.return_value.lxc.return_value.migrate.post.assert_not_called()


@pytest.mark.parametrize("invalid", [None, {}, "", "not-a-task"])
def test_invalid_submission_response_is_uncertain_without_retry(invalid):
    api = migration_api()
    api.nodes.return_value.lxc.return_value.migrate.post.return_value = invalid
    response = json.loads(ContainerTools(api).migrate_container("sam", "115", "six", confirm_migration=True)[0].text)
    assert response["code"] == "SUBMISSION_UNCERTAIN"
    assert response["success"] is False
    assert response["retryable"] is False
    api.nodes.return_value.lxc.return_value.migrate.post.assert_called_once()


def test_lost_submission_response_is_uncertain_without_retry():
    api = migration_api()
    api.nodes.return_value.lxc.return_value.migrate.post.side_effect = ConnectionError("response lost")
    response = json.loads(ContainerTools(api).migrate_container("sam", "115", "six", confirm_migration=True)[0].text)
    assert response["code"] == "SUBMISSION_UNCERTAIN"
    api.nodes.return_value.lxc.return_value.migrate.post.assert_called_once()


@pytest.mark.parametrize("status", [400, 503])
def test_http_submission_failure_never_retries(status):
    from proxmoxer.core import ResourceException

    api = migration_api()
    api.nodes.return_value.lxc.return_value.migrate.post.side_effect = ResourceException(status, "failure", "migration rejected")
    if status == 400:
        with pytest.raises(RuntimeError, match="migration rejected"):
            ContainerTools(api).migrate_container("sam", "115", "six", confirm_migration=True)
    else:
        response = json.loads(ContainerTools(api).migrate_container("sam", "115", "six", confirm_migration=True)[0].text)
        assert response["code"] == "SUBMISSION_UNCERTAIN"
    api.nodes.return_value.lxc.return_value.migrate.post.assert_called_once()


@pytest.mark.parametrize("kwargs", [
    {"restart": "yes"}, {"confirm_downtime": "yes"}, {"restart": True},
])
def test_invalid_downtime_confirmation_blocks_before_any_api_read(kwargs):
    api = migration_api()
    with pytest.raises(ValueError, match="booleans|confirm_downtime"):
        ContainerTools(api).migrate_container("sam", "115", "six", confirm_migration=True, **kwargs)
    api.nodes.assert_not_called()


def test_running_migration_with_confirmations_uses_lxc_restart():
    api = migration_api(running=True)
    ContainerTools(api).migrate_container(
        "sam", "115", "six", restart=True, confirm_migration=True, confirm_downtime=True
    )
    api.nodes.return_value.lxc.return_value.migrate.post.assert_called_once_with(target="six", restart=1)


def test_migration_mcp_registry_dispatch_and_policy():
    from types import SimpleNamespace
    from proxmox_mcp.services.builtin_tool_plugins import ContainerToolsPlugin

    registered = {}
    def register(**kwargs):
        def decorator(fn):
            registered[fn.__name__] = fn
            return fn
        return decorator
    server = SimpleNamespace(tool_registry=SimpleNamespace(tool=register),
                             config=SimpleNamespace(ssh=None), logger=MagicMock())
    plugin = ContainerToolsPlugin()
    plugin._wrap_sync = MagicMock(return_value=lambda **kwargs: kwargs)
    plugin.register(server)
    dispatched = registered["migrate_container"](
        node="sam", vmid="115", destination="six",
        restart=True, confirm_migration=True, confirm_downtime=True, target="default")
    assert dispatched["destination"] == "six"
    assert dispatched["confirm_downtime"] is True
    assert plugin._wrap_sync.call_args.kwargs.get("high_risk") is True


def test_migration_returns_remote_upid_even_when_job_tracking_fails():
    api = migration_api()
    store = MagicMock()
    store.register_task.side_effect = OSError("DB unavailable")
    response = json.loads(ContainerTools(api, job_store=store).migrate_container(
        "sam", "115", "six", confirm_migration=True
    )[0].text)
    assert response["status"] == "submitted"
    assert response["task_id"] == "UPID:sam:migrate:115"
    assert response["job_id"] is None
    api.nodes.return_value.lxc.return_value.migrate.post.assert_called_once()
