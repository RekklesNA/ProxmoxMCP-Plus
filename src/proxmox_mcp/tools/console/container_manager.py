"""
Module for managing LXC container console operations via SSH + pct exec.

pct exec is not exposed through the Proxmox REST API; it must be invoked
as a subprocess on the Proxmox node where the container lives. This module
SSHes to the appropriate node and runs:
    pct exec <vmid> -- sh -c '<cmd>'
"""

import os
import shlex
import logging
import subprocess
from typing import Dict, Any

import paramiko  # type: ignore[import-untyped]


class ContainerConsoleManager:
    """Execute shell commands inside LXC containers via SSH + pct exec."""

    def __init__(self, proxmox_api: Any, ssh_config: Any) -> None:
        self.proxmox = proxmox_api
        self.ssh_cfg = ssh_config
        self.logger = logging.getLogger("proxmox-mcp.ct-console")

    def _ssh_host(self, node: str) -> str:
        return self.ssh_cfg.host_overrides.get(node, node)

    def _use_system_ssh(self) -> bool:
        return bool(getattr(self.ssh_cfg, "prefer_ssh_client", False))

    def _execute_via_system_ssh(self, target: str, cmd: str) -> Dict[str, Any]:
        ssh_cmd = ["ssh"]
        key_file = getattr(self.ssh_cfg, "key_file", None)
        if key_file:
            ssh_cmd.extend(["-i", os.path.expanduser(key_file)])
        if getattr(self.ssh_cfg, "port", None):
            ssh_cmd.extend(["-p", str(self.ssh_cfg.port)])
        ssh_cmd.extend([target, cmd])

        self.logger.debug("Executing via OpenSSH client: %s", " ".join(shlex.quote(p) for p in ssh_cmd))
        completed = subprocess.run(  # noqa: S603
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=70,
            check=False,
        )
        return {
            "success": completed.returncode == 0,
            "output": completed.stdout,
            "error": completed.stderr,
            "exit_code": completed.returncode,
        }

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
        target = self._ssh_host(node)

        if self._use_system_ssh():
            return self._execute_via_system_ssh(target, cmd)

        # 3. SSH to node and run command
        client = paramiko.SSHClient()
        if self.ssh_cfg.strict_host_key_checking:
            client.load_system_host_keys()
            if self.ssh_cfg.known_hosts_file:
                client.load_host_keys(os.path.expanduser(self.ssh_cfg.known_hosts_file))
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs: Dict[str, Any] = dict(
            hostname=target,
            port=self.ssh_cfg.port,
            username=self.ssh_cfg.user,
            timeout=10,
        )
        if self.ssh_cfg.key_file:
            connect_kwargs["key_filename"] = os.path.expanduser(self.ssh_cfg.key_file)
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
