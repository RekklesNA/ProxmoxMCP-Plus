"""
Log tools for Proxmox MCP.

Provides MCP tools for reading Proxmox logs:
- Node syslog   (GET /nodes/{node}/syslog)
- Task log      (GET /nodes/{node}/tasks/{upid}/log)
- Cluster log   (GET /cluster/log)
- Node firewall log  (GET /nodes/{node}/firewall/log)
- Guest firewall log (GET /nodes/{node}/{qemu|lxc}/{vmid}/firewall/log)

API reference: https://pve.proxmox.com/pve-docs/api-viewer/
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from mcp.types import TextContent as Content

from proxmox_mcp.tools.base import ProxmoxTool


def _build_params(**kwargs: Any) -> Dict[str, Any]:
    """Return a dict of kwargs with None values removed.

    The Proxmox REST API rejects unknown/null parameters, so we only
    forward values the caller actually supplied.
    """
    return {k: v for k, v in kwargs.items() if v is not None}


class LogTools(ProxmoxTool):
    """Tools for reading Proxmox node logs and task output."""

    # ------------------------------------------------------------------
    # Syslog  —  GET /nodes/{node}/syslog
    # API params: limit (int), start (int), since (str YYYY-MM-DD[ HH:MM[:SS]]),
    #             until (str), service (str)
    # Returns: [{n: int, t: str}]
    # ------------------------------------------------------------------

    def get_node_syslog(
        self,
        node: str,
        limit: int = 100,
        start: Optional[int] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        service: Optional[str] = None,
    ) -> List[Content]:
        """Read syslog entries from a Proxmox node.

        Args:
            node:    Node name (e.g. 'pve').
            limit:   Maximum number of lines to return (default 100).
            start:   Start line for pagination (0-based).
            since:   Show entries from this date/time onward
                     (format: YYYY-MM-DD or YYYY-MM-DD HH:MM or YYYY-MM-DD HH:MM:SS).
            until:   Show entries up to this date/time (same format as since).
            service: Filter by service name (e.g. 'pvedaemon', 'pveproxy').

        Returns:
            List of MCP Content objects with plain-text log lines.
        """
        try:
            params = _build_params(
                limit=limit, start=start, since=since, until=until, service=service
            )
            raw = self.proxmox.nodes(node).syslog.get(**params)
            return [Content(type="text", text=self._format_log_entries(raw, "syslog", node))]
        except Exception as e:
            self._handle_error(f"get syslog for node {node}", e)

    # ------------------------------------------------------------------
    # Task log  —  GET /nodes/{node}/tasks/{upid}/log
    # API params: start (int, 0-based), limit (int, default 50)
    # Returns: [{n: int, t: str}]
    # ------------------------------------------------------------------

    def get_task_log(
        self,
        node: str,
        upid: str,
        start: Optional[int] = None,
        limit: int = 50,
    ) -> List[Content]:
        """Get the log output of a specific Proxmox task.

        Args:
            node:  Node that ran the task.
            upid:  Unique Process ID of the task.
            start: Start line for pagination (0-based).
            limit: Maximum number of log lines (default 50).

        Returns:
            List of MCP Content objects with plain-text task log.
        """
        try:
            params = _build_params(start=start, limit=limit)
            raw = self.proxmox.nodes(node).tasks(upid).log.get(**params)
            return [Content(type="text", text=self._format_task_log(raw, upid))]
        except Exception as e:
            self._handle_error(f"get log for task {upid} on node {node}", e)

    # ------------------------------------------------------------------
    # Cluster log  —  GET /cluster/log
    # API params: max (int, >= 1)
    # Returns: [{node, user, time (epoch), pri, tag, pid, uid, msg}]
    # ------------------------------------------------------------------

    def get_cluster_log(self, max_entries: int = 50) -> List[Content]:
        """Read recent cluster-wide log entries.

        Args:
            max_entries: Maximum number of entries to return (API param 'max').

        Returns:
            List of MCP Content objects with plain-text cluster log lines.
        """
        try:
            params = _build_params(max=max_entries)
            raw = self.proxmox.cluster.log.get(**params)
            return [Content(type="text", text=self._format_cluster_log(raw))]
        except Exception as e:
            self._handle_error("get cluster log", e)

    # ------------------------------------------------------------------
    # Node firewall log  —  GET /nodes/{node}/firewall/log
    # API params: limit (int), start (int), since (int epoch), until (int epoch)
    # Returns: [{n: int, t: str}]
    # ------------------------------------------------------------------

    def get_node_firewall_log(
        self,
        node: str,
        limit: int = 100,
        start: Optional[int] = None,
        since: Optional[int] = None,
        until: Optional[int] = None,
    ) -> List[Content]:
        """Read the host firewall log of a Proxmox node.

        Args:
            node:  Node name (e.g. 'pve').
            limit: Maximum number of log lines (default 100).
            start: Start line for pagination (0-based).
            since: Show entries since this UNIX epoch timestamp.
            until: Show entries until this UNIX epoch timestamp.

        Returns:
            List of MCP Content objects with plain-text firewall log lines.
        """
        try:
            params = _build_params(limit=limit, start=start, since=since, until=until)
            raw = self.proxmox.nodes(node).firewall.log.get(**params)
            return [Content(type="text", text=self._format_log_entries(raw, "firewall log", node))]
        except Exception as e:
            self._handle_error(f"get firewall log for node {node}", e)

    # ------------------------------------------------------------------
    # Guest firewall log
    #   GET /nodes/{node}/qemu/{vmid}/firewall/log
    #   GET /nodes/{node}/lxc/{vmid}/firewall/log
    # API params: limit (int), start (int), since (int epoch), until (int epoch)
    # Returns: [{n: int, t: str}]
    # ------------------------------------------------------------------

    def get_guest_firewall_log(
        self,
        node: str,
        vmid: int,
        vm_type: str = "qemu",
        limit: int = 100,
        start: Optional[int] = None,
        since: Optional[int] = None,
        until: Optional[int] = None,
    ) -> List[Content]:
        """Read the firewall log of a VM (qemu) or container (lxc).

        Args:
            node:    Node hosting the guest.
            vmid:    VM/container ID.
            vm_type: Guest type: 'qemu' (default) or 'lxc'.
            limit:   Maximum number of log lines (default 100).
            start:   Start line for pagination (0-based).
            since:   Show entries since this UNIX epoch timestamp.
            until:   Show entries until this UNIX epoch timestamp.

        Returns:
            List of MCP Content objects with plain-text firewall log lines.
        """
        try:
            if vm_type not in ("qemu", "lxc"):
                raise ValueError(f"Invalid vm_type '{vm_type}'. Must be 'qemu' or 'lxc'.")
            params = _build_params(limit=limit, start=start, since=since, until=until)
            guest_api = getattr(self.proxmox.nodes(node), vm_type)(vmid)
            raw = guest_api.firewall.log.get(**params)
            label = f"firewall log ({vm_type} {vmid})"
            return [Content(type="text", text=self._format_log_entries(raw, label, node))]
        except Exception as e:
            self._handle_error(f"get firewall log for {vm_type} {vmid} on node {node}", e)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _format_log_entries(self, raw: Any, log_type: str, node: str) -> str:
        """Render a log API response as readable plain text.

        Syslog and firewall log endpoints return ``[{"n": int, "t": str}]``;
        plain string lists are handled too.
        """
        if not raw:
            return f"No {log_type} entries found for node '{node}'."

        lines: list[str] = [f"=== {log_type} for node '{node}' ({len(raw)} entries) ===\n"]

        for entry in raw:
            if isinstance(entry, str):
                lines.append(entry)
            elif isinstance(entry, dict):
                # syslog: {"n": line_number, "t": "log line text"}
                text = entry.get("t") or entry.get("message") or json.dumps(entry, default=str)
                lines.append(str(text))
            else:
                lines.append(str(entry))

        return "\n".join(lines)

    def _format_cluster_log(self, raw: Any) -> str:
        """Render a cluster log API response as readable plain text.

        Entries look like ``{node, user, time (epoch), pri, tag, pid, uid, msg}``.
        """
        if not raw:
            return "No cluster log entries found."

        lines: list[str] = [f"=== cluster log ({len(raw)} entries) ===\n"]

        for entry in raw:
            if isinstance(entry, dict):
                time_val = entry.get("time")
                if isinstance(time_val, (int, float)):
                    stamp = datetime.fromtimestamp(time_val, tz=timezone.utc).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                else:
                    stamp = str(time_val or "?")
                node = entry.get("node", "?")
                user = entry.get("user", "?")
                tag = entry.get("tag", "?")
                msg = entry.get("msg", json.dumps(entry, default=str))
                lines.append(f"[{stamp}] {node} {user} {tag}: {msg}")
            else:
                lines.append(str(entry))

        return "\n".join(lines)

    def _format_task_log(self, raw: Any, upid: str) -> str:
        """Render a task log API response as readable plain text.

        The task log endpoint returns ``[{"n": int, "t": str}]``.
        """
        if not raw:
            return f"No log entries found for task '{upid}'."

        lines: list[str] = [f"=== Task log for {upid} ({len(raw)} lines) ===\n"]

        for entry in raw:
            if isinstance(entry, str):
                lines.append(entry)
            elif isinstance(entry, dict):
                lines.append(str(entry.get("t", json.dumps(entry, default=str))))
            else:
                lines.append(str(entry))

        return "\n".join(lines)
