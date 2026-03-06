"""
Module for managing LXC container console operations via SSH + pct exec.

pct exec is not exposed through the Proxmox REST API; it must be invoked
as a subprocess on the Proxmox node where the container lives. This module
SSHes to the appropriate node and runs:
    pct exec <vmid> -- sh -c '<cmd>'
"""

import shlex
import logging
from typing import Dict, Any

import paramiko


class ContainerConsoleManager:
    """Execute shell commands inside LXC containers via SSH + pct exec."""

    def __init__(self, proxmox_api: Any, ssh_config: Any) -> None:
        self.proxmox = proxmox_api
        self.ssh_cfg = ssh_config
        self.logger = logging.getLogger("proxmox-mcp.ct-console")

    def _ssh_host(self, node: str) -> str:
        return self.ssh_cfg.host_overrides.get(node, node)

    def execute_command(self, node: str, vmid: str, command: str) -> Dict[str, Any]:
        """Execute *command* inside the LXC container identified by *vmid* on *node*.

        Args:
            node:    Proxmox node name (e.g. 'pve1').
            vmid:    Container ID as a string (e.g. '101').
            command: Shell command to run inside the container.

        Returns:
            {"success": bool, "output": str, "error": str, "exit_code": int}

        Raises:
            ValueError:  Container is not running.
            RuntimeError: SSH / pct exec failure.
        """
        # 1. Verify container is running via Proxmox API
        status = self.proxmox.nodes(node).lxc(vmid).status.current.get()
        if status.get("status") != "running":
            raise ValueError(f"Container {vmid} on node {node} is not running")

        # 2. Build pct exec command
        prefix = "sudo " if self.ssh_cfg.use_sudo else ""
        cmd = f"{prefix}/usr/sbin/pct exec {shlex.quote(str(vmid))} -- sh -c {shlex.quote(command)}"
        self.logger.info("Executing on CT %s@%s: %s", vmid, node, command)

        # 3. SSH to node and run command
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs: Dict[str, Any] = dict(
            hostname=self._ssh_host(node),
            port=self.ssh_cfg.port,
            username=self.ssh_cfg.user,
            timeout=10,
        )
        if self.ssh_cfg.key_file:
            connect_kwargs["key_filename"] = self.ssh_cfg.key_file
        elif self.ssh_cfg.password:
            connect_kwargs["password"] = self.ssh_cfg.password

        try:
            client.connect(**connect_kwargs)
            _, stdout, stderr = client.exec_command(cmd, timeout=60)
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            exit_code = stdout.channel.recv_exit_status()
            return {
                "success": exit_code == 0,
                "output": out,
                "error": err,
                "exit_code": exit_code,
            }
        except paramiko.SSHException as e:
            self.logger.error("SSH error connecting to %s: %s", node, e)
            raise RuntimeError(f"SSH error connecting to node {node}: {e}") from e
        finally:
            client.close()
