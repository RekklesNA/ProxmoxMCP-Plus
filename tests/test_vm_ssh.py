"""VM SSH routing, authorization and transport contracts."""

import json
import shlex
import subprocess
from unittest.mock import AsyncMock, Mock, patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

from proxmox_mcp.config.models import Config, VMSSHConfig
from proxmox_mcp.core.targets import TargetRegistry
from proxmox_mcp.server import ProxmoxMCPServer
from proxmox_mcp.tools.console import container_manager
from proxmox_mcp.tools.vm import VMTools


PROFILE = {
    "host": "vm.example",
    "user": "guest-operator",
    "key_file": "vm_key",
    "known_hosts_file": "guest keys",
    "port": 2222,
}
AUTH = {"user": "test@pve", "token_name": "test", "token_value": "test"}
POLICY = {
    "mode": "allowlist", "allow_patterns": ["id"],
    "require_approval_token": True, "approval_token": "approved",
}


def test_profiles_are_explicit_and_target_scoped():
    legacy = Config.model_validate({
        "proxmox": {"host": "a.example"}, "auth": AUTH, "vm_ssh": {"101": PROFILE},
    })
    assert TargetRegistry(legacy).resolve().vm_ssh["101"].host == "vm.example"
    target = {"host": "a.example", "auth": AUTH}
    with pytest.raises(ValidationError, match="Top-level vm_ssh"):
        Config.model_validate({"targets": {"a": target}, "vm_ssh": {"101": PROFILE}})
    with pytest.raises(ValidationError):
        Config.model_validate({"targets": {"a": dict(target, vm_ssh={"../101": PROFILE})}})
    with pytest.raises(ValidationError):
        VMSSHConfig.model_validate(dict(PROFILE, strict_host_key_checking=False))


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    "success", "no_profile", "wrong_approval", "partial_match", "readonly",
    "client_denied", "windows", "stopped", "lost_result", "transport_error", "nul", "blank",
])
async def test_vm_ssh_through_mcp(tmp_path, case):
    a = {"host": "pve-a.example", "auth": AUTH, "command_policy": POLICY,
         "vm_ssh": {"101": PROFILE}, "readonly": case == "readonly"}
    b = {"host": "pve-b.example", "auth": AUTH, "command_policy": POLICY}
    mcp = {"transport": "STDIO"}
    if case == "client_denied":
        mcp["client_permissions"] = {"_local": {"tools": ["get_nodes"], "targets": ["a"]}}
    if case in {"nul", "blank"}:
        a["command_policy"] = {"mode": "audit_only"}
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"targets": {"a": a, "b": b}, "mcp": mcp,
                                 "jobs": {"sqlite_path": str(tmp_path / "jobs.db")}}))
    with patch("proxmox_mcp.core.proxmox.ProxmoxAPI") as api:
        qemu = api.return_value.nodes.return_value.qemu.return_value
        qemu.status.current.get.return_value = {"status": "stopped" if case == "stopped" else "running"}
        server = ProxmoxMCPServer(str(config))
    try:
        target = "b" if case == "no_profile" else "a"
        args = {"node": "pve", "vmid": "101", "command": "id", "target": target,
                "transport": "ssh", "approval_token": "approved"}
        args.update({
            "wrong_approval": {"approval_token": "wrong"},
            "partial_match": {"command": "id; echo extra"},
            "windows": {"guest_os": "windows"},
            "nul": {"command": "id\0"},
            "blank": {"command": "  "},
        }.get(case, {}))
        result = {"success": case == "success", "output": "fixture", "error": "", "exit_code": 0}
        if case == "lost_result":
            result["exit_code"] = 255
        with patch.object(container_manager.ContainerConsoleManager, "_run_ssh", return_value=result) as ssh:
            if case == "transport_error":
                ssh.side_effect = OSError("private transport detail")
            if case in {"no_profile", "readonly", "client_denied", "windows", "stopped", "nul"}:
                with pytest.raises(ToolError):
                    await server.mcp.call_tool("execute_vm_command", args)
            else:
                contents = await server.mcp.call_tool("execute_vm_command", args)
                expected = {
                    "wrong_approval": "CMD_POLICY_APPROVAL_REQUIRED",
                    "partial_match": "CMD_POLICY_NOT_ALLOWLISTED",
                    "blank": "CMD_POLICY_EMPTY",
                    "lost_result": "SSH_RESULT_UNKNOWN",
                    "transport_error": "SSH_RESULT_UNKNOWN",
                    "success": '"transport": "ssh"',
                }
                assert expected[case] in str(contents)
                assert "private transport detail" not in str(contents)
            qemu.agent.assert_not_called()
            if case in {"success", "lost_result", "transport_error"}:
                ssh.assert_called_once()
                host, command = ssh.call_args.args
                assert host == PROFILE["host"]
                assert shlex.split(command) == [
                    "/usr/bin/timeout", "--signal=TERM", "--kill-after=5s", "60s", "/bin/sh", "-c", "id",
                ]
            else:
                ssh.assert_not_called()
    finally:
        server.close()


@pytest.mark.asyncio
async def test_direct_ssh_without_policy_is_denied():
    tools = VMTools(Mock())
    with pytest.raises(RuntimeError, match="requires a configured command policy"):
        await tools.execute_command("pve", "101", "id", transport="ssh")
    tools.console_manager.execute_command = AsyncMock(return_value={"success": True, "output": "fixture"})
    await tools.execute_command("pve", "101", "id")
    tools.console_manager.execute_command.assert_awaited_once()


@pytest.mark.asyncio
async def test_direct_ssh_rejects_empty_command_before_connection():
    tools = VMTools(Mock())
    with pytest.raises(ValueError, match="nonempty"):
        await tools.console_manager.execute_ssh_command("pve", "101", "", VMSSHConfig(**PROFILE))


@pytest.mark.asyncio
@pytest.mark.parametrize("system_ssh", [False, True])
async def test_vm_ssh_uses_only_configured_identity(system_ssh):
    api = Mock()
    api.nodes.return_value.qemu.return_value.status.current.get.return_value = {"status": "running"}
    tools = VMTools(api)
    profile = VMSSHConfig(**PROFILE, prefer_ssh_client=system_ssh)
    with patch.object(container_manager, "run_bounded") as run, patch.object(container_manager.paramiko, "SSHClient") as factory:
        run.return_value = subprocess.CompletedProcess(["ssh"], 0, stdout="ok", stderr="")
        client = factory.return_value
        channel = Mock()
        client.exec_command.return_value = (Mock(), Mock(channel=channel), Mock())
        channel.recv_ready.return_value = False
        channel.recv_stderr_ready.return_value = False
        channel.exit_status_ready.return_value = True
        channel.recv_exit_status.return_value = 0
        result = await tools.console_manager.execute_ssh_command("pve", "101", "id", profile)
    assert result["success"]
    if system_ssh:
        factory.assert_not_called()
        argv = run.call_args.args[0]
        for arg in ("IdentitiesOnly=yes", "IdentityAgent=none", "StrictHostKeyChecking=yes",
                    "GlobalKnownHostsFile=none", 'UserKnownHostsFile="guest keys"', PROFILE["key_file"]):
            assert arg in argv
        assert argv[-2] == PROFILE["host"]
    else:
        run.assert_not_called()
        client.load_system_host_keys.assert_not_called()
        client.load_host_keys.assert_called_once_with(PROFILE["known_hosts_file"])
        assert client.connect.call_args.kwargs["allow_agent"] is False
        assert client.connect.call_args.kwargs["look_for_keys"] is False
        assert client.connect.call_args.kwargs["key_filename"] == PROFILE["key_file"]
        client.close.assert_called_once()
