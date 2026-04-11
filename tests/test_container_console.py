"""
Tests for LXC container console operations via SSH + pct exec.
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from proxmox_mcp.tools.console.container_manager import ContainerConsoleManager


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

class _SSHConfig:
    """Minimal stand-in for SSHConfig."""
    user = "root"
    port = 22
    key_file = "/home/user/.ssh/proxmox_key"
    password = None
    host_overrides: dict = {}
    use_sudo = False
    known_hosts_file = None
    strict_host_key_checking = False


@pytest.fixture
def ssh_cfg():
    return _SSHConfig()


@pytest.fixture
def mock_proxmox():
    """Mock ProxmoxAPI with a running container."""
    m = MagicMock()
    m.nodes.return_value.lxc.return_value.status.current.get.return_value = {
        "status": "running"
    }
    return m


@pytest.fixture
def manager(mock_proxmox, ssh_cfg):
    return ContainerConsoleManager(mock_proxmox, ssh_cfg)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def _make_ssh_client(stdout_data: bytes = b"", stderr_data: bytes = b"", exit_code: int = 0):
    """Build a mock paramiko.SSHClient that returns the given output."""
    channel = MagicMock()
    channel.recv_exit_status.return_value = exit_code

    stdout = MagicMock()
    stdout.read.return_value = stdout_data
    stdout.channel = channel

    stderr = MagicMock()
    stderr.read.return_value = stderr_data

    client = MagicMock()
    client.exec_command.return_value = (MagicMock(), stdout, stderr)
    return client


@patch("proxmox_mcp.tools.console.container_manager.paramiko.SSHClient")
def test_execute_command_success(MockSSHClient, manager):
    """Happy-path: running container, command exits 0."""
    mock_client = _make_ssh_client(stdout_data=b"Linux ct-101\n", exit_code=0)
    MockSSHClient.return_value = mock_client

    result = manager.execute_command("pve1", "101", "uname -a")

    assert result["success"] is True
    assert "Linux ct-101" in result["output"]
    assert result["exit_code"] == 0
    assert result["error"] == ""

    # Verify pct exec was called with quoted vmid and command
    call_args = mock_client.exec_command.call_args
    cmd = call_args[0][0]
    assert "/usr/sbin/pct exec" in cmd
    assert "101" in cmd
    assert "uname -a" in cmd


@patch("proxmox_mcp.tools.console.container_manager.paramiko.SSHClient")
def test_execute_command_nonzero_exit(MockSSHClient, manager):
    """Command that exits non-zero sets success=False."""
    mock_client = _make_ssh_client(stderr_data=b"not found\n", exit_code=1)
    MockSSHClient.return_value = mock_client

    result = manager.execute_command("pve1", "101", "false")

    assert result["success"] is False
    assert result["exit_code"] == 1
    assert "not found" in result["error"]


def test_execute_command_container_not_running(manager, mock_proxmox):
    """Raises ValueError if container is stopped."""
    mock_proxmox.nodes.return_value.lxc.return_value.status.current.get.return_value = {
        "status": "stopped"
    }
    with pytest.raises(ValueError, match="not running"):
        manager.execute_command("pve1", "101", "echo hi")


@patch("proxmox_mcp.tools.console.container_manager.paramiko.SSHClient")
def test_execute_command_ssh_failure(MockSSHClient, manager):
    """SSH connection error is wrapped in RuntimeError."""
    import paramiko
    mock_client = MagicMock()
    mock_client.connect.side_effect = paramiko.SSHException("Connection refused")
    MockSSHClient.return_value = mock_client

    with pytest.raises(RuntimeError, match="SSH error"):
        manager.execute_command("pve1", "101", "uname -a")


@patch("proxmox_mcp.tools.console.container_manager.paramiko.SSHClient")
def test_ssh_host_override(MockSSHClient, manager, ssh_cfg):
    """host_overrides maps node name to IP for the SSH connection."""
    ssh_cfg.host_overrides = {"pve1": "192.168.1.101"}
    mock_client = _make_ssh_client(stdout_data=b"ok\n", exit_code=0)
    MockSSHClient.return_value = mock_client

    manager.execute_command("pve1", "101", "echo ok")

    connect_kwargs = mock_client.connect.call_args[1]
    assert connect_kwargs["hostname"] == "192.168.1.101"


@patch("proxmox_mcp.tools.console.container_manager.paramiko.SSHClient")
def test_use_sudo_prefix(MockSSHClient, manager, ssh_cfg):
    """When use_sudo=True, the pct command is prefixed with sudo."""
    ssh_cfg.use_sudo = True
    mock_client = _make_ssh_client(stdout_data=b"root\n", exit_code=0)
    MockSSHClient.return_value = mock_client

    manager.execute_command("pve1", "101", "whoami")

    cmd = mock_client.exec_command.call_args[0][0]
    assert cmd.startswith("sudo /usr/sbin/pct exec")


@patch("proxmox_mcp.tools.console.container_manager.paramiko.SSHClient")
def test_password_auth_used_when_no_key(MockSSHClient, manager, ssh_cfg):
    """Falls back to password auth when key_file is None."""
    ssh_cfg.key_file = None
    ssh_cfg.password = "s3cr3t"
    mock_client = _make_ssh_client(stdout_data=b"ok\n", exit_code=0)
    MockSSHClient.return_value = mock_client

    manager.execute_command("pve1", "101", "echo ok")

    connect_kwargs = mock_client.connect.call_args[1]
    assert connect_kwargs.get("password") == "s3cr3t"
    assert "key_filename" not in connect_kwargs
