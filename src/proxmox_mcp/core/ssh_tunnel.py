"""Helpers for managing local SSH port forwards to remote Proxmox endpoints."""

from __future__ import annotations

import atexit
import logging
import os
import shlex
import socket
import subprocess
import time
from typing import Any


class SSHTunnelManager:
    """Maintain a single background SSH local-forward process."""

    def __init__(self, tunnel_config: Any, ssh_config: Any | None = None) -> None:
        self.tunnel_config = tunnel_config
        self.ssh_config = ssh_config
        self.logger = logging.getLogger("proxmox-mcp.ssh-tunnel")
        self._process: subprocess.Popen[str] | None = None
        atexit.register(self.close)

    def ensure_tunnel(self) -> None:
        if not getattr(self.tunnel_config, "enabled", False):
            return

        if self._is_local_endpoint_reachable():
            self.logger.info(
                "API tunnel already reachable on %s:%s",
                self.tunnel_config.local_host,
                self.tunnel_config.local_port,
            )
            return

        self._start_process()
        self._wait_for_local_listener()

    def close(self) -> None:
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None

    def _start_process(self) -> None:
        local = f"{self.tunnel_config.local_host}:{self.tunnel_config.local_port}:{self.tunnel_config.remote_host}:{self.tunnel_config.remote_port}"
        command = [
            "ssh",
            "-N",
            "-L",
            local,
            "-o",
            "ExitOnForwardFailure=yes",
        ]

        ssh_key = getattr(self.ssh_config, "key_file", None) if self.ssh_config is not None else None
        if ssh_key:
            command[1:1] = ["-i", os.path.expanduser(str(ssh_key))]
        ssh_port = getattr(self.ssh_config, "port", None) if self.ssh_config is not None else None
        if ssh_port:
            command.extend(["-p", str(ssh_port)])
        known_hosts_file = (
            getattr(self.ssh_config, "known_hosts_file", None)
            if self.ssh_config is not None
            else None
        )
        if known_hosts_file:
            command.extend(["-o", f"UserKnownHostsFile={os.path.expanduser(str(known_hosts_file))}"])
        strict_host_key_checking = (
            getattr(self.ssh_config, "strict_host_key_checking", True)
            if self.ssh_config is not None
            else True
        )
        command.extend([
            "-o",
            f"StrictHostKeyChecking={'yes' if strict_host_key_checking else 'no'}",
            self._ssh_target(),
        ])

        self.logger.info("Starting Proxmox API SSH tunnel via %s", self.tunnel_config.ssh_host)
        self.logger.debug("Tunnel command: %s", " ".join(shlex.quote(part) for part in command))
        self._process = subprocess.Popen(  # noqa: S603
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def _ssh_target(self) -> str:
        host = str(self.tunnel_config.ssh_host)
        user = getattr(self.ssh_config, "user", None) if self.ssh_config is not None else None
        if user and "@" not in host:
            return f"{user}@{host}"
        return host

    def _wait_for_local_listener(self) -> None:
        deadline = time.time() + max(int(self.tunnel_config.connect_timeout), 1)
        while time.time() < deadline:
            if self._process is not None and self._process.poll() is not None:
                stderr = ""
                if self._process.stderr is not None:
                    stderr = self._process.stderr.read().strip()
                raise RuntimeError(
                    f"Failed to establish SSH tunnel via {self.tunnel_config.ssh_host}: {stderr or 'ssh exited early'}"
                )
            if self._is_local_endpoint_reachable():
                self.logger.info(
                    "SSH tunnel ready on %s:%s",
                    self.tunnel_config.local_host,
                    self.tunnel_config.local_port,
                )
                return
            time.sleep(0.25)
        raise RuntimeError(
            "Timed out waiting for local API tunnel listener on "
            f"{self.tunnel_config.local_host}:{self.tunnel_config.local_port}"
        )

    def _is_local_endpoint_reachable(self) -> bool:
        try:
            with socket.create_connection(
                (self.tunnel_config.local_host, int(self.tunnel_config.local_port)),
                timeout=1.0,
            ):
                return True
        except OSError:
            return False
