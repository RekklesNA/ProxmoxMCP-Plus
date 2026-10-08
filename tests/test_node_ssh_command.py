"""Regression tests for opt-in Proxmox physical-host command execution."""

from unittest.mock import MagicMock, patch

import pytest

from proxmox_mcp.config.models import SSHConfig, CommandPolicyConfig
from proxmox_mcp.security.command_policy import CommandPolicyGate
from proxmox_mcp.tools.console.container_manager import ContainerConsoleManager
from proxmox_mcp.tools.containers import ContainerTools


def _manager(*, enabled=True, prefer_ssh_client=True):
    api = MagicMock()
    api.nodes.get.return_value = [{"node": "ichi"}, {"node": "two"}]
    ssh = SSHConfig(
        user="root",
        host_overrides={"ichi": "ichi.pve.example", "two": "two.pve.example"},
        allow_node_commands=enabled,
        prefer_ssh_client=prefer_ssh_client,
    )
    return ContainerConsoleManager(api, ssh)


def test_host_commands_disabled_by_default():
    assert not SSHConfig().allow_node_commands
    manager = _manager(enabled=False)
    with pytest.raises(PermissionError, match="disabled"):
        manager.execute_node_command("ichi", "id")
    manager.proxmox.nodes.get.assert_not_called()


@pytest.mark.parametrize("node", ["unknown", "", "-oProxyCommand=evil", "ichi && echo bad"])
def test_unknown_or_invalid_host_never_reaches_ssh(node):
    manager = _manager()
    with patch.object(manager, "_run_ssh") as ssh:
        with pytest.raises(ValueError):
            manager.execute_node_command(node, "id")
    ssh.assert_not_called()


def test_host_ssh_bounded_and_quotes_shell_payload():
    import shlex
    manager = _manager()
    command = "echo \"a'b\"; printf '%s' $(whoami)"
    with patch.object(manager, "_run_ssh", return_value={"success": True}) as ssh:
        result = manager.execute_node_command("ichi", command)
    assert result["success"]
    node, argv = ssh.call_args.args
    assert node == "ichi"
    assert shlex.split(argv) == [
        "/usr/bin/timeout", "--signal=TERM", "--kill-after=5s",
        "60s", "/bin/sh", "-c", command
    ]


@pytest.mark.parametrize("command", ["", "  ", "x" * 8193])
def test_invalid_command_rejected_before_ssh(command):
    manager = _manager()
    with patch.object(manager, "_run_ssh") as ssh:
        with pytest.raises(ValueError):
            manager.execute_node_command("ichi", command)
    ssh.assert_not_called()


def test_container_tools_enforce_command_gate_before_host_execution():
    api = MagicMock()
    ssh = SSHConfig(allow_node_commands=True)
    policy = CommandPolicyGate(CommandPolicyConfig(mode="deny_all"))
    tools = ContainerTools(api, ssh, command_policy=policy)
    with patch.object(tools.console_manager, "execute_node_command") as execute:
        result = tools.execute_node_command("ichi", "rm -rf /")
    assert "CMD_POLICY" in result[0].text
    execute.assert_not_called()


def test_target_specific_host_opt_in_is_not_derived_from_other_target():
    blocked = _manager(enabled=False)
    allowed = _manager(enabled=True)
    with pytest.raises(PermissionError):
        blocked.execute_node_command("ichi", "id")
    with patch.object(allowed, "_run_ssh", return_value={"success": True}) as ssh:
        allowed.execute_node_command("ichi", "id")
    ssh.assert_called_once()


def test_host_command_requires_ssh_configuration():
    tools = ContainerTools(MagicMock())
    with pytest.raises(RuntimeError, match="SSH is not configured"):
        tools.execute_node_command("ichi", "id")


def test_container_tools_execute_host_command_and_format_result():
    import json

    policy = CommandPolicyGate(CommandPolicyConfig(mode="allowlist", allow_patterns=[r"^id$"]))
    tools = ContainerTools(MagicMock(), SSHConfig(allow_node_commands=True), command_policy=policy)
    with patch.object(
        tools.console_manager,
        "execute_node_command",
        return_value={"success": True, "output": "uid=0", "exit_code": 0},
    ) as execute:
        result = tools.execute_node_command("ichi", "id")
    execute.assert_called_once_with("ichi", "id")
    assert json.loads(result[0].text) == {
        "success": True,
        "output": "uid=0",
        "exit_code": 0,
    }


def test_container_tools_report_host_command_failure():
    tools = ContainerTools(MagicMock(), SSHConfig(allow_node_commands=True))
    with patch.object(
        tools.console_manager,
        "execute_node_command",
        side_effect=RuntimeError("SSH connection failed"),
    ):
        with pytest.raises(RuntimeError, match="SSH connection failed"):
            tools.execute_node_command("ichi", "id")
