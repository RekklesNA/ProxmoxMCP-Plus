"""
Tests for LXC container console operations via SSH + pct exec.
"""

import pytest
from unittest.mock import MagicMock, patch

from proxmox_mcp.tools.console.container_manager import ContainerConsoleManager


@pytest.mark.parametrize("busy", [False, True])
def test_channel_wall_clock_timeout_and_cleanup(manager, monkeypatch, busy):
    channel = MagicMock()
    channel.recv_ready.return_value = busy
    channel.recv_stderr_ready.return_value = busy
    channel.recv.return_value = b"out"
    channel.recv_stderr.return_value = b"err"
    channel.exit_status_ready.return_value = False
    ticks = iter([0, 1, 2, 71])
    monkeypatch.setattr("proxmox_mcp.tools.console.container_manager.time.monotonic", lambda: next(ticks))
    result = manager._read_channel(channel)
    assert result["code"] == "COMMAND_TIMEOUT"
    assert result["timed_out"] is True
    assert result["exit_code"] == 124
    if busy:
        assert result["output"] == "outout"
        assert "errerr" in result["error"]
    channel.recv_exit_status.assert_not_called()
    channel.close.assert_called_once()


def test_channel_drains_stderr_before_waiting_for_exit(manager):
    client = _make_ssh_client(b"hello\n", b"warning\n")
    channel = client.exec_command.return_value[1].channel
    channel.exit_status_ready.side_effect = lambda: not channel.recv_ready() and not channel.recv_stderr_ready()
    result = manager._read_channel(channel)
    assert result["output"] == "hello\n"
    assert result["error"] == "warning\n"
    assert result["success"]
    channel.close.assert_called_once()


@patch("proxmox_mcp.tools.console.container_manager.subprocess.run")
def test_system_ssh_timeout_returns_partial_output(mock_run, manager, ssh_cfg):
    import subprocess
    ssh_cfg.prefer_ssh_client = True
    mock_run.side_effect = subprocess.TimeoutExpired("ssh", 70, output=b"partial\xff", stderr=b"progress")
    result = manager.execute_command("pve1", "101", "sleep 120")
    assert result["code"] == "COMMAND_TIMEOUT"
    assert result["output"].startswith("partial")
    assert "progress" in result["error"]
    assert mock_run.call_args.kwargs["timeout"] == 70


@pytest.mark.parametrize("exit_code", [124, 137])
@patch("proxmox_mcp.tools.console.container_manager.paramiko.SSHClient")
def test_remote_timeout_is_explicit_and_ssh_is_closed(factory, exit_code, manager):
    client = _make_ssh_client(b"partial", exit_code=exit_code)
    factory.return_value = client
    result = manager.execute_command("pve1", "101", "sleep 120")
    assert result["code"] == "COMMAND_TIMEOUT"
    client.close.assert_called_once()
    stdin, stdout, _ = client.exec_command.return_value
    stdin.close.assert_called_once()
    stdout.channel.shutdown_write.assert_called_once()
    stdout.read.assert_not_called()


def test_remote_watchdog_quotes_command_inside_container(manager, ssh_cfg):
    import shlex
    ssh_cfg.prefer_ssh_client = True
    command = "printf '%s' \"a'b; $(whoami)\" && sleep 120"
    with patch.object(manager, "_execute_via_system_ssh", return_value={}) as execute:
        manager.execute_command("pve1", "101", command)
    args = shlex.split(execute.call_args.args[1])
    assert args == ["/usr/sbin/pct", "exec", "101", "--", "/usr/bin/timeout",
                    "--signal=TERM", "--kill-after=5s", "60s", "sh", "-c", command]


def test_remote_watchdog_terminates_term_ignoring_shell(tmp_path):
    """Run the actual GNU watchdog on Linux, with a shorter test deadline."""
    import os
    import subprocess
    import time
    if os.name != "posix" or not os.path.exists("/usr/bin/timeout"):
        pytest.skip("Requires the Linux GNU timeout runtime used in containers")
    marker = tmp_path / "escaped"
    started = time.monotonic()
    result = subprocess.run(["/usr/bin/timeout", "--signal=TERM", "--kill-after=0.1s", "0.1s",
                             "sh", "-c", 'trap "" TERM; sleep 1; echo escaped > "$1"', "sh", str(marker)],
                            capture_output=True, timeout=3)
    # Direct subprocess execution reports SIGKILL as -9; an intervening shell
    # (as on SSH) reports 128 + SIGKILL instead.
    assert result.returncode in (-9, 137)
    assert time.monotonic() - started < 2
    time.sleep(1.1)
    assert not marker.exists(), "A foreground descendant survived the deadline"


@patch("proxmox_mcp.tools.console.container_manager.paramiko.SSHClient")
def test_unacknowledged_exec_request_is_interrupted(factory, manager):
    import threading
    import paramiko
    closed = threading.Event()
    client = MagicMock()
    client.close.side_effect = closed.set
    factory.return_value = client
    manager.SSH_TIMEOUT = 0.05

    def stuck_exec(*args, **kwargs):
        assert closed.wait(1), "exec request was never interrupted"
        raise paramiko.SSHException("Channel closed")

    client.exec_command.side_effect = stuck_exec
    result = manager.execute_command("pve1", "101", "sleep 120")
    assert result["code"] == "COMMAND_TIMEOUT"
    assert closed.is_set()


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
    prefer_ssh_client = False


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

    channel.recv_ready.side_effect = lambda: bool(stdout_chunks)
    channel.recv_stderr_ready.side_effect = lambda: bool(stderr_chunks)
    stdout_chunks = [stdout_data] if stdout_data else []
    stderr_chunks = [stderr_data] if stderr_data else []
    channel.recv.side_effect = lambda size: stdout_chunks.pop(0)
    channel.recv_stderr.side_effect = lambda size: stderr_chunks.pop(0)
    channel.exit_status_ready.return_value = True

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


@patch("proxmox_mcp.tools.console.container_manager.paramiko.RejectPolicy")
@patch("proxmox_mcp.tools.console.container_manager.paramiko.SSHClient")
def test_paramiko_always_rejects_unknown_host_keys(MockSSHClient, MockRejectPolicy, manager, ssh_cfg):
    ssh_cfg.strict_host_key_checking = False
    mock_client = _make_ssh_client(stdout_data=b"ok\n", exit_code=0)
    MockSSHClient.return_value = mock_client
    MockRejectPolicy.return_value = object()

    manager.execute_command("pve1", "101", "echo ok")

    mock_client.load_system_host_keys.assert_called_once()
    mock_client.set_missing_host_key_policy.assert_called_once_with(MockRejectPolicy.return_value)


@patch("proxmox_mcp.tools.console.container_manager.paramiko.RejectPolicy")
@patch("proxmox_mcp.tools.console.container_manager.paramiko.SSHClient")
def test_paramiko_loads_explicit_known_hosts_file(MockSSHClient, MockRejectPolicy, manager, ssh_cfg):
    ssh_cfg.known_hosts_file = "~/known_hosts.custom"
    mock_client = _make_ssh_client(stdout_data=b"ok\n", exit_code=0)
    MockSSHClient.return_value = mock_client
    MockRejectPolicy.return_value = object()

    manager.execute_command("pve1", "101", "echo ok")

    mock_client.load_host_keys.assert_called_once()
    mock_client.set_missing_host_key_policy.assert_called_once_with(MockRejectPolicy.return_value)


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
    assert cmd.startswith("sudo -n /usr/sbin/pct exec")


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


@patch("proxmox_mcp.tools.console.container_manager.subprocess.run")
def test_execute_command_via_system_ssh(mock_run, manager, ssh_cfg):
    ssh_cfg.prefer_ssh_client = True
    ssh_cfg.host_overrides = {"pve1": "ahg1"}
    mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")

    result = manager.execute_command("pve1", "101", "echo ok")

    assert result["success"] is True
    ssh_command = mock_run.call_args[0][0]
    assert ssh_command[-2] == "ahg1"
    assert "/usr/sbin/pct exec" in ssh_command[-1]
    # The argv must include "--" before the target so OpenSSH cannot reinterpret
    # a target beginning with "-" as an option flag.
    assert ssh_command[-3] == "--"


@patch("proxmox_mcp.tools.console.container_manager.subprocess.run")
def test_system_ssh_uses_double_dash_for_dash_prefixed_target(mock_run, manager, ssh_cfg):
    """A host_overrides value starting with '-' must not be parsed as an SSH option."""
    ssh_cfg.prefer_ssh_client = True
    # Worst-case attacker-controlled override: would be -oProxyCommand=... without `--`.
    ssh_cfg.host_overrides = {"pve1": "-oProxyCommand=evil"}
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    manager.execute_command("pve1", "101", "echo ok")

    ssh_command = mock_run.call_args[0][0]
    # `--` must appear before the target so option processing has ended.
    assert "--" in ssh_command
    dash_index = ssh_command.index("--")
    assert ssh_command[dash_index + 1] == "-oProxyCommand=evil"
    assert "/usr/sbin/pct exec" in ssh_command[dash_index + 2]


# ---------------------------------------------------------------------------
# Windows-compatibility regression tests (issue #100)
# ---------------------------------------------------------------------------

@patch("proxmox_mcp.tools.console.container_manager.subprocess.run")
def test_system_ssh_passes_user_with_dash_l(mock_run, manager, ssh_cfg):
    """Bug 1: system SSH command must include `-l <user>` so OpenSSH does not
    fall back to the current OS user (e.g. the Windows login name on Windows).
    """
    ssh_cfg.prefer_ssh_client = True
    ssh_cfg.user = "root@pam"
    ssh_cfg.host_overrides = {"pve1": "ahg1"}
    mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")

    manager.execute_command("pve1", "101", "echo ok")

    ssh_command = mock_run.call_args[0][0]
    assert "-l" in ssh_command
    l_index = ssh_command.index("-l")
    assert ssh_command[l_index + 1] == "root@pam"
    # `-l` must come before the `--` separator so OpenSSH parses it.
    assert l_index < ssh_command.index("--")


@patch("proxmox_mcp.tools.console.container_manager.subprocess.run")
def test_system_ssh_omits_dash_l_when_user_unset(mock_run, manager, ssh_cfg):
    """`-l` is only added when a user is configured; never emit `-l None`."""
    ssh_cfg.prefer_ssh_client = True
    ssh_cfg.user = None
    ssh_cfg.host_overrides = {"pve1": "ahg1"}
    mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")

    manager.execute_command("pve1", "101", "echo ok")

    ssh_command = mock_run.call_args[0][0]
    assert "-l" not in ssh_command


@patch("proxmox_mcp.tools.console.container_manager.subprocess.run")
def test_system_ssh_closes_stdin(mock_run, manager, ssh_cfg):
    """Bug 2: subprocess.run must use stdin=DEVNULL so OpenSSH does not
    inherit the MCP server's stdin pipe (causes 70s hang on Windows).
    """
    import subprocess as sp

    ssh_cfg.prefer_ssh_client = True
    ssh_cfg.host_overrides = {"pve1": "ahg1"}
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    manager.execute_command("pve1", "101", "echo ok")

    assert mock_run.call_args.kwargs.get("stdin") == sp.DEVNULL


@patch("proxmox_mcp.tools.console.container_manager.subprocess.run")
def test_system_ssh_uses_batch_mode_and_accept_new(mock_run, manager, ssh_cfg):
    """Bug 3: system SSH must pass BatchMode=yes and
    StrictHostKeyChecking=accept-new so headless MCP servers do not hang
    on host-key prompts.
    """
    ssh_cfg.prefer_ssh_client = True
    ssh_cfg.host_overrides = {"pve1": "ahg1"}
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    manager.execute_command("pve1", "101", "echo ok")

    ssh_command = mock_run.call_args[0][0]
    # `-o BatchMode=yes` and `-o StrictHostKeyChecking=accept-new` must both
    # be present, and they must come before the `--` separator.
    assert "-o" in ssh_command
    assert "BatchMode=yes" in ssh_command
    assert "StrictHostKeyChecking=accept-new" in ssh_command

    dash_index = ssh_command.index("--")
    for opt in ("BatchMode=yes", "StrictHostKeyChecking=accept-new"):
        assert ssh_command.index(opt) < dash_index, (
            f"{opt} must be passed as an SSH option, not as part of the target"
        )
