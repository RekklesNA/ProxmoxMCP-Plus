"""Exercise the public FastMCP boundary for guarded VM provisioning tools."""

import json
from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from proxmox_mcp.server import ProxmoxMCPServer


APPROVAL = "test-vm-tool-approval"
DIGEST = "a" * 40
MUTATIONS = ("migrate_vm", "import_cloud_image", "configure_vm_serial_console")
ALL_TOOLS = ("preflight_vm_migration", *MUTATIONS)


def _arguments(tool):
    args = {"node": "sam", "vmid": "142", "target": "chosen"}
    if tool in {"preflight_vm_migration", "migrate_vm"}:
        args["destination"] = "six"
    if tool == "migrate_vm":
        args.update(
            confirm_migration=True,
            confirm_backup_verified=True,
            confirm_workload_drained=True,
            confirm_cpu_compatibility=True,
        )
    elif tool == "import_cloud_image":
        args.update(
            source_volume="source:import/debian.qcow2",
            destination_storage="local-lvm",
            disk_device="scsi1",
            confirm_import=True,
        )
    elif tool == "configure_vm_serial_console":
        args["confirm_display_change"] = True
    return args


def _api():
    """Use separate source/destination resources, including real config digests."""
    api = MagicMock()
    nodes = {name: MagicMock() for name in ("sam", "six")}
    api.nodes.side_effect = lambda name: nodes[name]
    api.nodes.get.return_value = [
        {"node": name, "status": "online"} for name in nodes
    ]
    api.cluster.resources.get.return_value = [
        {"id": "qemu/142", "vmid": 142, "node": "sam", "type": "qemu", "status": "stopped"}
    ]
    api.cluster.ha.resources.get.return_value = []
    api.storage.get.return_value = [
        {"storage": "source", "type": "dir", "content": "import", "shared": 0},
        {"storage": "local-lvm", "type": "lvmthin", "content": "images,rootdir", "shared": 0},
    ]
    for node in nodes.values():
        node.storage.get.return_value = [
            {"storage": "source", "type": "dir", "content": "import", "active": 1,
             "enabled": 1, "shared": 0, "avail": 100 * 1024**3, "total": 200 * 1024**3},
            {"storage": "local-lvm", "type": "lvmthin", "content": "images,rootdir",
             "active": 1, "enabled": 1, "shared": 0, "avail": 100 * 1024**3,
             "total": 200 * 1024**3},
        ]
        node.network.get.return_value = [{"iface": "vmbr0", "type": "bridge", "active": 1}]
        node.storage.return_value.content.get.return_value = [
            {"volid": "source:import/debian.qcow2", "content": "import", "format": "qcow2",
             "size": 1024**3},
        ]
    guest = nodes["sam"].qemu.return_value
    guest.status.current.get.return_value = {"status": "stopped", "vmid": 142}
    guest.config.get.return_value = {
        "digest": DIGEST, "name": "dispatch-test", "cpu": "kvm64",
        "scsi0": "local-lvm:vm-142-disk-0,size=40G",
        "net0": "virtio=02:00:00:00:00:01,bridge=vmbr0",
    }
    guest.migrate.get.return_value = {
        "running": 0, "allowed_nodes": ["six"], "not_allowed_nodes": {},
        "local_resources": [], "mapped-resources": [], "mapped-resource-info": {},
        "local_disks": [{
            "volid": "local-lvm:vm-142-disk-0", "size": 40 * 1024**3,
            "cdrom": 0, "is_unused": 0, "is_cloudinit": 0, "is_vmstate": 0,
            "shared": 0, "is_attached": 1,
        }],
    }
    guest.migrate.post.return_value = "UPID:sam:00001234:00000001:12345678:qmigrate:142:test@pve:"
    guest.config.post.return_value = "UPID:sam:00001234:00000001:12345678:qmconfig:142:test@pve:"
    return api, nodes, guest


def _server(tmp_path, *, readonly=False, client_tools=None, client_targets=None):
    fixtures = {name: _api() for name in ("chosen", "other")}
    policy = {
        "high_risk_mode": "enforce", "high_risk_require_approval_token": True,
        "high_risk_approval_token": APPROVAL,
        # Deliberately use the default high_risk_operations: omitting a new tool
        # from that default must cause the public no-token regression to fail.
    }
    targets = {
        name: {
            "host": name, "readonly": readonly,
            "command_policy": {**policy, "high_risk_approval_token": APPROVAL if name == "chosen" else APPROVAL + "-other"},
            "auth": {"user": "test@pve", "token_name": "test", "token_value": "test-value"},
        }
        for name in fixtures
    }
    config = {"targets": targets, "jobs": {"sqlite_path": str(tmp_path / "jobs.sqlite3")}}
    if client_tools is not None or client_targets is not None:
        config["mcp"] = {"client_permissions": {"_local": {
            "targets": client_targets if client_targets is not None else ["chosen"],
            "tools": client_tools if client_tools is not None else list(ALL_TOOLS),
        }}}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with patch("proxmox_mcp.core.proxmox.ProxmoxAPI", side_effect=lambda **kwargs: fixtures[kwargs["host"]][0]):
        server = ProxmoxMCPServer(str(path))
    for api, _, _ in fixtures.values():
        api.reset_mock()
    return server, fixtures


def _assert_no_guest_access(fixtures):
    for api, nodes, _ in fixtures.values():
        api.nodes.assert_not_called()
        api.nodes.get.assert_not_called()
        api.cluster.resources.get.assert_not_called()
        for node in nodes.values():
            node.qemu.assert_not_called()
            node.storage.assert_not_called()
            node.storage.get.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", MUTATIONS)
@pytest.mark.parametrize("token", [None, "wrong-approval"])
async def test_default_operation_policy_blocks_missing_or_wrong_token_before_api(tmp_path, tool, token):
    server, fixtures = _server(tmp_path)
    try:
        args = _arguments(tool)
        if token is not None:
            args["approval_token"] = token
        with pytest.raises(ToolError, match="approval token"):
            await server.mcp.call_tool(tool, args)
        _assert_no_guest_access(fixtures)
    finally:
        server.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", MUTATIONS)
async def test_readonly_rejects_new_mutations_before_api_even_with_approval(tmp_path, tool):
    server, fixtures = _server(tmp_path, readonly=True)
    try:
        with pytest.raises(ToolError, match="read-only"):
            await server.mcp.call_tool(tool, {**_arguments(tool), "approval_token": APPROVAL})
        _assert_no_guest_access(fixtures)
    finally:
        server.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", MUTATIONS)
async def test_client_tool_grant_rejects_mutations_even_with_approval(tmp_path, tool):
    server, fixtures = _server(tmp_path, client_tools=["preflight_vm_migration"])
    try:
        with pytest.raises(ToolError, match="not authorized"):
            await server.mcp.call_tool(tool, {**_arguments(tool), "approval_token": APPROVAL})
        _assert_no_guest_access(fixtures)
    finally:
        server.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ALL_TOOLS)
async def test_client_target_grant_cannot_be_bypassed_by_tool_approval(tmp_path, tool):
    server, fixtures = _server(tmp_path, client_targets=["other"])
    try:
        args = _arguments(tool)
        if tool in MUTATIONS:
            args["approval_token"] = APPROVAL
        with pytest.raises(ToolError, match="not authorized"):
            await server.mcp.call_tool(tool, args)
        _assert_no_guest_access(fixtures)
    finally:
        server.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", MUTATIONS)
async def test_approval_token_is_checked_against_the_selected_target_policy(tmp_path, tool):
    server, fixtures = _server(tmp_path)
    try:
        args = {**_arguments(tool), "target": "other", "approval_token": APPROVAL}
        with pytest.raises(ToolError, match="approval token"):
            await server.mcp.call_tool(tool, args)
        _assert_no_guest_access(fixtures)
    finally:
        server.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ALL_TOOLS)
@pytest.mark.parametrize("target", [None, "not-configured"])
async def test_multiple_targets_require_an_explicit_known_target_before_api(tmp_path, tool, target):
    server, fixtures = _server(tmp_path)
    try:
        args = _arguments(tool)
        if target is None:
            args.pop("target")
        else:
            args["target"] = target
        if tool in MUTATIONS:
            args["approval_token"] = APPROVAL
        with pytest.raises(ToolError):
            await server.mcp.call_tool(tool, args)
        _assert_no_guest_access(fixtures)
    finally:
        server.close()


@pytest.mark.asyncio
async def test_readonly_preflight_is_dispatched_to_only_the_selected_target(tmp_path):
    server, fixtures = _server(tmp_path, readonly=True)
    try:
        result = await server.mcp.call_tool("preflight_vm_migration", _arguments("preflight_vm_migration"))
        content = result[0] if isinstance(result, tuple) else result
        assert json.loads(content[0].text)["ready"] is True
        fixtures["chosen"][2].migrate.post.assert_not_called()
        fixtures["other"][0].nodes.assert_not_called()
        fixtures["other"][0].cluster.resources.get.assert_not_called()
    finally:
        server.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", MUTATIONS)
async def test_approved_vm_mutations_reach_real_handler_without_leaking_token(tmp_path, tool):
    server, fixtures = _server(tmp_path)
    try:
        result = await server.mcp.call_tool(tool, {**_arguments(tool), "approval_token": APPROVAL})
        content = result[0] if isinstance(result, tuple) else result
        payload = json.loads(content[0].text)
        if tool == "configure_vm_serial_console":
            assert payload["changed"] is True
        else:
            assert payload["status"] == "submitted"
            assert payload["task_id"].startswith("UPID:")
        _, _, guest = fixtures["chosen"]
        if tool == "migrate_vm":
            guest.migrate.post.assert_called_once_with(target="six", online=0, **{"with-local-disks": 1})
            guest.config.put.assert_not_called()
            guest.config.post.assert_not_called()
        elif tool == "import_cloud_image":
            guest.config.post.assert_called_once_with(
                scsi1="local-lvm:0,import-from=source:import/debian.qcow2", digest=DIGEST,
            )
            guest.migrate.post.assert_not_called()
            guest.config.put.assert_not_called()
        else:
            guest.config.put.assert_called_once_with(serial0="socket", vga="serial0", digest=DIGEST)
            guest.migrate.post.assert_not_called()
            guest.config.post.assert_not_called()
        fixtures["other"][0].nodes.assert_not_called()
        fixtures["other"][0].cluster.resources.get.assert_not_called()
    finally:
        server.close()


@pytest.mark.asyncio
async def test_public_vm_schemas_expose_target_and_guarded_operation_parameters(tmp_path):
    server, _ = _server(tmp_path)
    try:
        tools = {tool.name: tool for tool in await server.mcp.list_tools()}
        for name in ALL_TOOLS:
            properties = tools[name].inputSchema["properties"]
            assert {"node", "vmid", "target"} <= properties.keys()
            # The registry uniformly adds approval metadata to every tool.
            assert properties["approval_token"]["default"] is None
        migration = tools["migrate_vm"].inputSchema["properties"]
        # The MVP deliberately cannot request live migration or disable copying
        # local disks through a public tool argument.
        assert {"online", "with_local_disks", "with-local-disks", "force"}.isdisjoint(migration)
        for name in (
            "confirm_migration", "confirm_backup_verified", "confirm_workload_drained",
            "confirm_cpu_compatibility",
        ):
            assert migration[name]["default"] is False
    finally:
        server.close()
