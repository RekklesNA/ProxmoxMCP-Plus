from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from proxmox_mcp.core.proxmox import ProxmoxManager
from proxmox_mcp.core.ssh_tunnel import SSHTunnelManager


def test_api_tunnel_uses_ssh_config_options(caplog) -> None:
    tunnel_config = SimpleNamespace(
        enabled=True,
        ssh_host="jump-host",
        local_host="127.0.0.1",
        local_port=18006,
        remote_host="10.0.0.10",
        remote_port=8006,
        connect_timeout=15,
    )
    ssh_config = SimpleNamespace(
        user="mcp-agent",
        port=2222,
        key_file="~/id_ed25519",
        known_hosts_file="~/known_hosts.proxmox",
        strict_host_key_checking=False,
    )
    manager = SSHTunnelManager(tunnel_config, ssh_config)

    caplog.set_level("DEBUG", logger="proxmox-mcp.ssh-tunnel")
    with patch("proxmox_mcp.core.ssh_tunnel.subprocess.Popen", return_value=Mock()) as popen:
        manager._start_process()

    command = popen.call_args.args[0]

    assert command[-1] == "mcp-agent@jump-host"
    assert command[command.index("-p") + 1] == "2222"
    assert command[command.index("-i") + 1] == os.path.expanduser("~/id_ed25519")
    assert f"UserKnownHostsFile={os.path.expanduser('~/known_hosts.proxmox')}" in command
    assert "StrictHostKeyChecking=no" in command
    assert "id_ed25519" not in caplog.text
    assert "known_hosts.proxmox" not in caplog.text
    assert "Tunnel command" not in caplog.text


def test_api_tunnel_does_not_duplicate_user_in_ssh_host() -> None:
    tunnel_config = SimpleNamespace(
        enabled=True,
        ssh_host="root@jump-host",
        local_host="127.0.0.1",
        local_port=18006,
        remote_host="10.0.0.10",
        remote_port=8006,
        connect_timeout=15,
    )
    ssh_config = SimpleNamespace(user="mcp-agent", port=22, key_file=None)
    manager = SSHTunnelManager(tunnel_config, ssh_config)

    with patch("proxmox_mcp.core.ssh_tunnel.subprocess.Popen", return_value=Mock()) as popen:
        manager._start_process()

    assert popen.call_args.args[0][-1] == "root@jump-host"


def test_disabled_api_tunnel_does_not_start_process() -> None:
    tunnel_config = SimpleNamespace(enabled=False)
    manager = SSHTunnelManager(tunnel_config)

    with patch("proxmox_mcp.core.ssh_tunnel.subprocess.Popen") as popen:
        manager.ensure_tunnel()

    popen.assert_not_called()


def test_api_tunnel_reuses_reachable_local_endpoint() -> None:
    tunnel_config = SimpleNamespace(
        enabled=True,
        ssh_host="jump-host",
        local_host="127.0.0.1",
        local_port=18006,
        remote_host="10.0.0.10",
        remote_port=8006,
        connect_timeout=15,
    )
    manager = SSHTunnelManager(tunnel_config)

    with patch.object(manager, "_is_local_endpoint_reachable", return_value=True), patch.object(
        manager, "_start_process"
    ) as start_process:
        with pytest.raises(RuntimeError, match="identity.*cannot be verified"):
            manager.ensure_tunnel()

    start_process.assert_not_called()


def test_api_tunnel_can_explicitly_reuse_external_endpoint() -> None:
    tunnel_config = SimpleNamespace(
        enabled=True, assume_external=True, ssh_host="jump-host",
        local_host="127.0.0.1", local_port=18006,
        remote_host="10.0.0.10", remote_port=8006, connect_timeout=15,
    )
    manager = SSHTunnelManager(tunnel_config)

    with patch.object(manager, "_is_local_endpoint_reachable", return_value=True), patch.object(
        manager, "_start_process"
    ) as start_process:
        manager.ensure_tunnel()

    start_process.assert_not_called()


def test_api_tunnel_starts_and_waits_when_local_endpoint_unreachable() -> None:
    tunnel_config = SimpleNamespace(
        enabled=True,
        ssh_host="jump-host",
        local_host="127.0.0.1",
        local_port=18006,
        remote_host="10.0.0.10",
        remote_port=8006,
        connect_timeout=15,
    )
    manager = SSHTunnelManager(tunnel_config)

    with patch.object(manager, "_is_local_endpoint_reachable", return_value=False), patch.object(
        manager, "_start_process"
    ) as start_process, patch.object(manager, "_wait_for_local_listener") as wait_for_listener:
        manager.ensure_tunnel()

    start_process.assert_called_once()
    wait_for_listener.assert_called_once()


def test_api_tunnel_close_terminates_running_process() -> None:
    manager = SSHTunnelManager(SimpleNamespace(enabled=True))
    process = Mock()
    process.poll.return_value = None
    manager._process = process

    manager.close()

    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=5)
    process.kill.assert_not_called()
    assert manager._process is None


def test_api_tunnel_close_kills_process_after_timeout() -> None:
    manager = SSHTunnelManager(SimpleNamespace(enabled=True))
    process = Mock()
    process.poll.return_value = None
    process.wait.side_effect = TimeoutError()
    manager._process = process

    with patch("proxmox_mcp.core.ssh_tunnel.subprocess.TimeoutExpired", TimeoutError):
        manager.close()

    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert manager._process is None


def test_api_tunnel_wait_fails_when_ssh_exits_early() -> None:
    tunnel_config = SimpleNamespace(
        ssh_host="jump-host",
        local_host="127.0.0.1",
        local_port=18006,
        remote_host="10.0.0.10",
        remote_port=8006,
        connect_timeout=15,
    )
    manager = SSHTunnelManager(tunnel_config)
    process = Mock()
    process.poll.return_value = 255
    process.stderr.read.return_value = "bad\nkey"
    manager._process = process

    with pytest.raises(RuntimeError, match="Failed to establish SSH tunnel"):
        manager._wait_for_local_listener()


def test_api_tunnel_wait_times_out_without_listener() -> None:
    tunnel_config = SimpleNamespace(
        ssh_host="jump-host",
        local_host="127.0.0.1",
        local_port=18006,
        remote_host="10.0.0.10",
        remote_port=8006,
        connect_timeout=1,
    )
    manager = SSHTunnelManager(tunnel_config)
    process = Mock()
    process.poll.return_value = None
    manager._process = process

    with patch.object(manager, "_is_local_endpoint_reachable", return_value=False), patch(
        "proxmox_mcp.core.ssh_tunnel.time.time", side_effect=[0, 2]
    ), patch("proxmox_mcp.core.ssh_tunnel.time.sleep"):
        with pytest.raises(RuntimeError, match="Timed out waiting"):
            manager._wait_for_local_listener()


def test_api_tunnel_wait_returns_when_listener_becomes_reachable() -> None:
    tunnel_config = SimpleNamespace(
        ssh_host="jump-host",
        local_host="127.0.0.1",
        local_port=18006,
        remote_host="10.0.0.10",
        remote_port=8006,
        connect_timeout=1,
    )
    manager = SSHTunnelManager(tunnel_config)
    process = Mock()
    process.poll.return_value = None
    manager._process = process

    with patch.object(manager, "_is_local_endpoint_reachable", return_value=True):
        manager._wait_for_local_listener()


def test_proxmox_manager_close_releases_tunnel_manager() -> None:
    manager = object.__new__(ProxmoxManager)
    manager.tunnel_manager = Mock()

    manager.close()

    manager.tunnel_manager.close.assert_called_once()


def test_proxmox_manager_close_without_tunnel_is_noop() -> None:
    manager = object.__new__(ProxmoxManager)
    manager.tunnel_manager = None

    manager.close()


def test_assume_external_never_spawns_own_tunnel_process() -> None:
    """assume_external promises another supervisor owns the listener.

    If the external listener is temporarily unavailable, the server must fail
    loudly rather than silently spawning (and later killing) its own ssh.
    """
    tunnel_config = SimpleNamespace(
        enabled=True,
        assume_external=True,
        ssh_host="jump-host",
        local_host="127.0.0.1",
        local_port=18007,
        remote_host="127.0.0.1",
        remote_port=8006,
        connect_timeout=1,
    )
    manager = SSHTunnelManager(tunnel_config)

    with patch.object(manager, "_is_local_endpoint_reachable", return_value=False), \
         patch.object(manager, "_start_process") as start, \
         patch.object(manager, "_wait_for_local_listener") as wait:
        with pytest.raises(RuntimeError, match="(?i)externally managed"):
            manager.ensure_tunnel()

    start.assert_not_called()
    wait.assert_not_called()


def test_assume_external_reuses_reachable_external_listener() -> None:
    tunnel_config = SimpleNamespace(
        enabled=True,
        assume_external=True,
        ssh_host="jump-host",
        local_host="127.0.0.1",
        local_port=18007,
        remote_host="127.0.0.1",
        remote_port=8006,
        connect_timeout=1,
    )
    manager = SSHTunnelManager(tunnel_config)

    with patch.object(manager, "_is_local_endpoint_reachable", return_value=True), \
         patch.object(manager, "_start_process") as start:
        manager.ensure_tunnel()

    start.assert_not_called()


def test_external_tunnel_is_never_owned_or_terminated() -> None:
    """An externally supervised tunnel must not be adopted as our process."""
    tunnel_config = SimpleNamespace(
        enabled=True,
        assume_external=True,
        ssh_host="jump-host",
        local_host="127.0.0.1",
        local_port=18007,
        remote_host="127.0.0.1",
        remote_port=8006,
        connect_timeout=1,
    )
    manager = SSHTunnelManager(tunnel_config)

    with patch.object(manager, "_is_local_endpoint_reachable", return_value=True):
        manager.ensure_tunnel()

    assert manager._process is None
    manager.close()
    assert manager._process is None
