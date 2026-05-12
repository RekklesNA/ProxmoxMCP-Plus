from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

from proxmox_mcp.core.ssh_tunnel import SSHTunnelManager


def test_api_tunnel_uses_ssh_config_options() -> None:
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

    with patch("proxmox_mcp.core.ssh_tunnel.subprocess.Popen", return_value=Mock()) as popen:
        manager._start_process()

    command = popen.call_args.args[0]

    assert command[-1] == "mcp-agent@jump-host"
    assert command[command.index("-p") + 1] == "2222"
    assert command[command.index("-i") + 1] == os.path.expanduser("~/id_ed25519")
    assert f"UserKnownHostsFile={os.path.expanduser('~/known_hosts.proxmox')}" in command
    assert "StrictHostKeyChecking=no" in command


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
