"""
Module for managing VM console operations.

This module provides functionality for interacting with VM consoles:
- Executing commands within VMs via QEMU guest agent
- Handling command execution lifecycle
- Managing command output and status
- Error handling and logging

The module implements a robust command execution system with:
- VM state verification
- Asynchronous command execution
- Detailed status tracking
- Comprehensive error handling
"""

import asyncio
import logging
from typing import Dict, Any

from proxmox_mcp.security.sanitization import sanitize_string


def _log_safe(value: object, max_length: int = 200) -> str:
    return sanitize_string(value, max_length=max_length)


class VMConsoleManager:
    """Manager class for VM console operations.
    
    Provides functionality for:
    - Executing commands in VM consoles
    - Managing command execution lifecycle
    - Handling command output and errors
    - Monitoring execution status
    
    Uses QEMU guest agent for reliable command execution with:
    - VM state verification before execution
    - Asynchronous command processing
    - Detailed output capture
    - Comprehensive error handling
    """

    def __init__(self, proxmox_api):
        """Initialize the VM console manager.

        Args:
            proxmox_api: Initialized ProxmoxAPI instance
        """
        self.proxmox = proxmox_api
        self.logger = logging.getLogger("proxmox-mcp.vm-console")

    async def _wait_for_exec_status(
        self,
        endpoint: Any,
        pid: int,
        *,
        timeout_seconds: int = 60,
        poll_interval_seconds: float = 1.0,
    ) -> Dict[str, Any]:
        """Poll QEMU guest-agent exec-status until completion or timeout."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        last_status: Dict[str, Any] = {}

        while True:
            try:
                self.logger.debug("Getting command status for pid=%s", _log_safe(pid))
                console = endpoint("exec-status").get(pid=pid)
                self.logger.debug("Raw exec-status response type: %s", type(console).__name__)
                if not console:
                    raise RuntimeError("No response from exec-status")
                if not isinstance(console, dict):
                    return {
                        "out-data": str(console),
                        "err-data": "",
                        "exitcode": 0,
                        "exited": 1,
                    }
                last_status = console
            except Exception as e:
                self.logger.error("Failed to get command status for pid=%s: %s", _log_safe(pid), _log_safe(e))
                raise RuntimeError(f"Failed to get command status: {str(e)}")

            if last_status.get("exited", 0):
                return last_status

            remaining = deadline - loop.time()
            if remaining <= 0:
                timed_out = dict(last_status)
                timed_out["timed_out"] = True
                timed_out.setdefault("exitcode", -1)
                timed_out.setdefault(
                    "err-data",
                    f"Command did not complete within {timeout_seconds} seconds",
                )
                return timed_out

            await asyncio.sleep(min(poll_interval_seconds, remaining))

    async def execute_command(self, node: str, vmid: str, command: str) -> Dict[str, Any]:
        """Execute a command in a VM's console via QEMU guest agent.

        Implements a two-phase command execution process:
        1. Command Initiation:
           - Verifies VM exists and is running
           - Initiates command execution via guest agent
           - Captures command PID for tracking
        
        2. Result Collection:
           - Monitors command execution status
           - Captures command output and errors
           - Handles completion status
        
        Requirements:
        - VM must be running
        - QEMU guest agent must be installed and active
        - Command execution permissions must be enabled

        Args:
            node: Name of the node where VM is running (e.g., 'pve1')
            vmid: ID of the VM to execute command in (e.g., '100')
            command: Shell command to execute in the VM

        Returns:
            Dictionary containing command execution results:
            {
                "success": true/false,
                "output": "command output",
                "error": "error output if any",
                "exit_code": command_exit_code
            }

        Raises:
            ValueError: If:
                     - VM is not found
                     - VM is not running
                     - Guest agent is not available
            RuntimeError: If:
                       - Command execution fails
                       - Unable to get command status
                       - API communication errors occur
        """
        try:
            # Verify VM exists and is running
            vm_status = self.proxmox.nodes(node).qemu(vmid).status.current.get()
            if vm_status["status"] != "running":
                self.logger.error("Failed to execute command on VM %s: VM is not running", _log_safe(vmid))
                raise ValueError(f"VM {vmid} on node {node} is not running")

            # Get VM's console
            self.logger.info("Executing command on VM %s (node: %s)", _log_safe(vmid), _log_safe(node))
            
            # Get the API endpoint
            # Use the guest agent exec endpoint
            endpoint = self.proxmox.nodes(node).qemu(vmid).agent
            self.logger.debug("Using VM guest-agent endpoint for VM %s on node %s", _log_safe(vmid), _log_safe(node))
            
            # Check the agent capability before attempting guest-exec. Some
            # appliances expose the QEMU guest agent for inspection only.
            try:
                agent_info = endpoint("info").get()
                supported = agent_info.get("supported_commands", []) if isinstance(agent_info, dict) else []
                supported_names = {
                    item.get("name") for item in supported if isinstance(item, dict)
                }
                disabled = {
                    item.get("name") for item in supported
                    if isinstance(item, dict) and item.get("enabled") is False
                }
                if supported_names and ("guest-exec" not in supported_names or "guest-exec" in disabled):
                    raise RuntimeError(
                        "QEMU guest agent on VM "
                        f"{vmid} does not support guest-exec; install/configure a guest agent "
                        "with command execution support"
                    )
            except RuntimeError:
                raise
            except Exception as e:
                # Older Proxmox/QEMU-agent versions may not expose info; keep
                # the existing exec path in that case.
                self.logger.debug("Unable to inspect guest-agent capabilities: %s", _log_safe(e))

            # Execute the command using two-step process
            try:
                # Start command execution
                self.logger.info("Starting command execution...")
                try:
                    self.logger.debug("Executing command via guest agent for VM %s on node %s", _log_safe(vmid), _log_safe(node))
                    exec_result = endpoint("exec").post(command=command)
                    self.logger.debug("Raw exec response keys: %s", sorted(exec_result.keys()) if isinstance(exec_result, dict) else type(exec_result).__name__)
                    self.logger.info("Command started on VM %s with pid=%s", _log_safe(vmid), _log_safe(exec_result.get("pid") if isinstance(exec_result, dict) else "unknown"))
                except Exception as e:
                    self.logger.error("Failed to start command on VM %s: %s", _log_safe(vmid), _log_safe(e))
                    error_text = sanitize_string(e)
                    if "596" in error_text and "TLS negotiation" in error_text:
                        raise RuntimeError(
                            "QEMU guest agent rejected guest-exec on VM "
                            f"{vmid}; the agent is reachable but command execution is unavailable "
                            "for this guest"
                        ) from e
                    raise RuntimeError(f"Failed to start command: {error_text}") from e

                if 'pid' not in exec_result:
                    raise RuntimeError("No PID returned from command execution")

                pid = exec_result['pid']
                self.logger.info("Waiting for command completion on VM %s (pid=%s)", _log_safe(vmid), _log_safe(pid))

                console = await self._wait_for_exec_status(endpoint, pid)
                if isinstance(console, dict):
                    self.logger.info(
                        "Command completed on VM %s with exit_code=%s exited=%s timed_out=%s",
                        _log_safe(vmid),
                        _log_safe(console.get("exitcode", "unknown")),
                        _log_safe(console.get("exited", "unknown")),
                        _log_safe(console.get("timed_out", False)),
                    )
                else:
                    self.logger.info("Command completed on VM %s with non-dict status", _log_safe(vmid))
            except Exception as e:
                self.logger.error("Guest-agent API call failed on VM %s: %s", _log_safe(vmid), _log_safe(e))
                raise RuntimeError(f"API call failed: {sanitize_string(e)}") from e
            self.logger.debug("Raw API response type for VM %s: %s", _log_safe(vmid), type(console).__name__)
            
            # Handle different response structures
            if isinstance(console, dict):
                # Handle exec-status response format
                output = console.get("out-data", "")
                error = console.get("err-data", "")
                exit_code = console.get("exitcode", 0)
                exited = console.get("exited", 0)
                timed_out = bool(console.get("timed_out", False))
                
                if timed_out:
                    self.logger.warning("Command did not complete before timeout")
                elif not exited:
                    self.logger.warning("Command may not have completed")
            else:
                # Some versions might return data differently
                self.logger.debug("Unexpected command response type for VM %s: %s", _log_safe(vmid), type(console).__name__)
                output = str(console)
                error = ""
                exit_code = 0
                exited = 1
                timed_out = False
            
            self.logger.debug("Processed command output length for VM %s: %s", _log_safe(vmid), len(str(output)))
            self.logger.debug("Processed command error length for VM %s: %s", _log_safe(vmid), len(str(error)))
            self.logger.debug("Processed exit code for VM %s: %s", _log_safe(vmid), _log_safe(exit_code))
            
            self.logger.debug("Executed command on VM %s (node: %s)", _log_safe(vmid), _log_safe(node))
            try:
                exit_code_int = int(exit_code)
            except (TypeError, ValueError):
                exit_code_int = -1

            return {
                "success": bool(exited) and exit_code_int == 0 and not timed_out,
                "output": output,
                "error": error,
                "exit_code": exit_code_int,
                "exited": bool(exited),
                "timed_out": timed_out,
            }

        except ValueError:
            # Re-raise ValueError for VM not running
            raise
        except Exception as e:
            self.logger.error("Failed to execute command on VM %s: %s", _log_safe(vmid), _log_safe(e))
            if "not found" in str(e).lower():
                raise ValueError(f"VM {vmid} not found on node {node}")
            raise RuntimeError(f"Failed to execute command: {sanitize_string(e)}") from e
