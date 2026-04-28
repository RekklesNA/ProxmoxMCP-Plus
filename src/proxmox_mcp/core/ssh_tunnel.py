"""Helpers for managing local SSH port forwards to remote Proxmox endpoints."""

from __future__ import annotations

import atexit
import logging
import os
import shlex
import socket
import subprocess
import time
from pathlib import Path
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
            self.tunnel_config.ssh_host,
        ]

        ssh_key = getattr(self.ssh_config, "key_file", None) if self.ssh_config is not None else None
        if ssh_key:
            command[1:1] = ["-i", os.path.expanduser(str(ssh_key))]

        self.logger.info("Starting Proxmox API SSH tunnel via %s", self.tunnel_config.ssh_host)
        self.logger.debug("Tunnel command: %s", " ".join(shlex.quote(part) for part in command))
        self._process = subprocess.Popen(  # noqa: S603
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

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
