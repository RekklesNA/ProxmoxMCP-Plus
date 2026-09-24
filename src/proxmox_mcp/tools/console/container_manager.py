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
import time
from threading import Event, Timer
from typing import Dict, Any

import paramiko  # type: ignore[import-untyped]


def _log_safe(value: object, max_length: int = 200) -> str:
    text = str(value).replace("\r", "").replace("\n", "")
    return text[:max_length]


class ContainerConsoleManager:
    """Execute shell commands inside LXC containers via SSH + pct exec."""

    COMMAND_TIMEOUT = 60
    KILL_GRACE = 5
    SSH_TIMEOUT = 70

    def _timeout_result(self, output: str = "", error: str = "") -> Dict[str, Any]:
        return {
            "success": False,
            "code": "COMMAND_TIMEOUT",
            "timed_out": True,
            "output": output,
            "error": f"Command timeout (command limit {self.COMMAND_TIMEOUT}s; SSH wait limit {self.SSH_TIMEOUT}s). "
                     "Partial changes may have occurred; check state before retrying."
                     + (f"\n{error}" if error else ""),
            "exit_code": 124,
        }

    def _result(self, code: int, output: str, error: str) -> Dict[str, Any]:
        if code in (124, 137):
            return self._timeout_result(output, error)
        return {"success": code == 0, "output": output, "error": error, "exit_code": code}

    def _read_channel(self, channel: Any) -> Dict[str, Any]:
        """Drain both streams fairly, with a wall-clock rather than idle timeout."""
        deadline = time.monotonic() + self.SSH_TIMEOUT
        out, err = bytearray(), bytearray()
        try:
            while time.monotonic() < deadline:
                received = False
                # One chunk per stream per iteration: continuously busy stdout
                # must not starve stderr or prevent checking the deadline.
                if channel.recv_ready():
                    out.extend(channel.recv(65536))
                    received = True
                if channel.recv_stderr_ready():
                    err.extend(channel.recv_stderr(65536))
                    received = True
                if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                    return self._result(channel.recv_exit_status(),
                                        out.decode("utf-8", errors="replace"),
                                        err.decode("utf-8", errors="replace"))
                if not received:
                    time.sleep(0.01)
            return self._timeout_result(out.decode("utf-8", errors="replace"),
                                        err.decode("utf-8", errors="replace"))
        finally:
            channel.close()

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
        if getattr(self.ssh_cfg, "user", None):
            # Explicitly pass the SSH username. On Linux, OpenSSH often falls
            # back to the current system user, but on Windows it falls back to
            # the Windows login name, which rarely has access to the Proxmox
            # host. Passing -l keeps behaviour consistent across platforms.
            ssh_cmd.extend(["-l", self.ssh_cfg.user])
        # `-o BatchMode=yes` makes OpenSSH fail immediately instead of waiting
        # for interactive input (host key confirmation, password prompts,
        # etc.) which is essential when the MCP server runs headless.
        # `-o StrictHostKeyChecking=accept-new` silently trusts first-seen
        # host keys so first-time connections do not block execution.
        ssh_cmd.extend([
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
        ])
        # `--` ends OpenSSH option processing so a target accidentally starting
        # with "-" (e.g. a misconfigured host_overrides value) cannot be
        # reinterpreted as a flag like -oProxyCommand=...
        ssh_cmd.extend(["--", target, cmd])

        self.logger.debug(
            "Executing command via OpenSSH client on target %s with %s arguments",
            _log_safe(target),
            len(ssh_cmd),
        )
        # `stdin=subprocess.DEVNULL` is required on Windows. Without it,
        # OpenSSH inherits the MCP server's stdin pipe, blocks indefinitely
        # reading from it, and the call hangs until the 70s timeout. This
        # does not reproduce on Linux where stdin behaves differently.
        try:
            completed = subprocess.run(  # noqa: S603
                ssh_cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=self.SSH_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            # subprocess.run kills and reaps the local SSH process on timeout.
            def text(value: Any) -> str:
                return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else (value or "")
            return self._timeout_result(text(error.stdout), text(error.stderr))
        return self._result(completed.returncode, completed.stdout, completed.stderr)

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
        prefix = "sudo -n " if self.ssh_cfg.use_sudo else ""
        # Run the watchdog INSIDE the container so it owns the shell's process
        # group even if the SSH connection disappears. Never fall back to an
        # unbounded command if the container lacks GNU coreutils timeout.
        cmd = (f"{prefix}/usr/sbin/pct exec {shlex.quote(str(vmid))} -- "
               f"/usr/bin/timeout --signal=TERM --kill-after={self.KILL_GRACE}s "
               f"{self.COMMAND_TIMEOUT}s sh -c {shlex.quote(command)}")
        self.logger.info("Executing command on CT %s@%s", _log_safe(vmid), _log_safe(node))
        target = self._ssh_host(node)

        if self._use_system_ssh():
            return self._execute_via_system_ssh(target, cmd)

        # 3. SSH to node and run command
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        if self.ssh_cfg.known_hosts_file:
            client.load_host_keys(os.path.expanduser(self.ssh_cfg.known_hosts_file))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        if not self.ssh_cfg.strict_host_key_checking:
            self.logger.warning(
                "Ignoring strict_host_key_checking=false for Paramiko execution; "
                "unknown SSH host keys are always rejected. "
                "Use prefer_ssh_client=true if you need OpenSSH-specific host key behavior."
            )

        connect_kwargs: Dict[str, Any] = dict(
            hostname=target,
            port=self.ssh_cfg.port,
            username=self.ssh_cfg.user,
            timeout=10,
            banner_timeout=10,
            auth_timeout=10,
            channel_timeout=10,
        )
        if self.ssh_cfg.key_file:
            connect_kwargs["key_filename"] = os.path.expanduser(self.ssh_cfg.key_file)
        elif self.ssh_cfg.password:
            connect_kwargs["password"] = self.ssh_cfg.password

        watchdog = None
        expired = Event()

        def close_expired_session() -> None:
            expired.set()
            client.close()

        try:
            client.connect(**connect_kwargs)
            # Paramiko's exec-request acknowledgement waits on an event, not
            # the channel read timeout. Closing the transport releases it too.
            watchdog = Timer(self.SSH_TIMEOUT, close_expired_session)
            watchdog.daemon = True
            watchdog.start()
            stdin, stdout, _ = client.exec_command(cmd, timeout=10)
            stdin.close()
            stdout.channel.shutdown_write()
            result = self._read_channel(stdout.channel)
            if expired.is_set():
                return self._timeout_result(result["output"], result["error"])
            return result
        except TimeoutError:
            return self._timeout_result()
        except paramiko.SSHException as e:
            if expired.is_set():
                return self._timeout_result()
            self.logger.error("SSH error connecting to %s: %s", _log_safe(node), _log_safe(e))
            raise RuntimeError(f"SSH error connecting to node {node}: {e}") from e
        finally:
            if watchdog is not None:
                watchdog.cancel()
            client.close()
