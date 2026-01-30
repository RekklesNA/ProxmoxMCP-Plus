"""Backup and restore tools for Proxmox MCP."""
from typing import List, Dict, Optional, Any
import json
from datetime import datetime
from mcp.types import TextContent as Content
from .base import ProxmoxTool


def _as_list(maybe: Any) -> List:
    """Return list; unwrap {'data': list}; else []."""
    if isinstance(maybe, list):
        return maybe
    if isinstance(maybe, dict):
        data = maybe.get("data")
        if isinstance(data, list):
            return data
    return []


def _get(d: Any, key: str, default: Any = None) -> Any:
    """dict.get with None guard."""
    if isinstance(d, dict):
        return d.get(key, default)
    return default


def _b2h(n: Any) -> str:
    """bytes -> human readable."""
    try:
        n = float(n)
    except Exception:
        return "0 B"
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    i = 0
    while n >= 1024.0 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    return f"{n:.2f} {units[i]}"


class BackupTools(ProxmoxTool):
    """Backup and restore tools for VMs and containers."""

    def _json_fmt(self, data: Any) -> List[Content]:
        """Return raw JSON string."""
        return [Content(type="text", text=json.dumps(data, indent=2, sort_keys=True))]

    def _err(self, action: str, e: Exception) -> List[Content]:
        """Handle errors."""
        if hasattr(self, "_handle_error"):
            self._handle_error(action, e)
        return [Content(type="text", text=f"Error: {action} - {str(e)}")]

    def list_backups(
        self,
        node: Optional[str] = None,
        storage: Optional[str] = None,
        vmid: Optional[str] = None,
    ) -> List[Content]:
        """List available backups across the cluster.

        Parameters:
            node: Filter by node (optional)
            storage: Filter by storage pool (optional)
            vmid: Filter by VM/container ID (optional)

        Returns:
            List[Content] with backup information
        """
        try:
            results = []
            try:
                nodes = _as_list(self.proxmox.nodes.get())
            except Exception as e:
                self._handle_error("list nodes", e)

            for n in nodes:
                node_name = _get(n, "node")
                if not node_name:
                    continue
                if node and node_name != node:
                    continue

                try:
                    storages = _as_list(self.proxmox.nodes(node_name).storage.get())
                except Exception as node_error:
                    self.logger.warning(
                        "Skipping node %s while listing backups: %s",
                        node_name,
                        node_error,
                    )
                    continue
                for s in storages:
                    storage_name = _get(s, "storage")
                    if not storage_name:
                        continue
                    if storage and storage_name != storage:
                        continue

                    # Check if storage supports backups
                    content_types = _get(s, "content", "")
                    if "backup" not in content_types:
                        continue

                    try:
                        params: Dict[str, Any] = {"content": "backup"}
                        if vmid:
                            params["vmid"] = int(vmid)

                        content = _as_list(
                            self.proxmox.nodes(node_name).storage(storage_name).content.get(**params)
                        )
                        for item in content:
                            item["_node"] = node_name
                            item["_storage"] = storage_name
                            results.append(item)
                    except Exception:
                        continue

            if not results:
                msg = "No backups found"
                if node:
                    msg += f" on node {node}"
                if storage:
                    msg += f" in storage {storage}"
                if vmid:
                    msg += f" for VM/CT {vmid}"
                return [Content(type="text", text=msg)]

            # Sort by creation time (newest first)
            results.sort(key=lambda x: _get(x, "ctime", 0), reverse=True)

            lines = ["💾 Available Backups", ""]

            for backup in results:
                volid = _get(backup, "volid", "unknown")
                size = _get(backup, "size", 0)
                ctime = _get(backup, "ctime")
                backup_vmid = _get(backup, "vmid", "?")
                notes = _get(backup, "notes", "")
                protected = _get(backup, "protected", False)
                node_name = _get(backup, "_node", "?")
                storage_name = _get(backup, "_storage", "?")
                fmt = _get(backup, "format", "")

                # Parse timestamp
                time_str = "Unknown"
                if ctime:
                    try:
                        dt = datetime.fromtimestamp(ctime)
                        time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        time_str = str(ctime)

                lines.append(f"  💾 VM/CT {backup_vmid} - {time_str}")
                lines.append(f"     Size: {_b2h(size)}")
                lines.append(f"     Format: {fmt}")
                lines.append(f"     Storage: {storage_name} @ {node_name}")
                lines.append(f"     Volume ID: {volid}")
                if notes:
                    lines.append(f"     Notes: {notes}")
                if protected:
                    lines.append(f"     🔒 Protected")
                lines.append("")

            lines.append("Use the Volume ID with restore_backup to restore.")

            return [Content(type="text", text="\n".join(lines).rstrip())]

        except Exception as e:
            return self._err("list backups", e)

    def create_backup(
        self,
        node: str,
        vmid: str,
        storage: str,
        compress: str = "zstd",
        mode: str = "snapshot",
        notes: Optional[str] = None,
    ) -> List[Content]:
        """Create a backup of a VM or container.

        Parameters:
            node: Node where VM/container runs
            vmid: VM or container ID to backup
            storage: Target backup storage
            compress: Compression (0, gzip, lz4, zstd)
            mode: Backup mode (snapshot, suspend, stop)
            notes: Optional notes/description

        Returns:
            List[Content] with backup result
        """
        try:
            params: Dict[str, Any] = {
                "vmid": vmid,
                "storage": storage,
                "compress": compress,
                "mode": mode,
            }

            if notes:
                params["notes-template"] = notes

            result = self.proxmox.nodes(node).vzdump.post(**params)

            lines = [
                "💾 Backup Started",
                "",
                f"  • VM/CT ID: {vmid}",
                f"  • Node: {node}",
                f"  • Storage: {storage}",
                f"  • Compression: {compress}",
                f"  • Mode: {mode}",
            ]

            if notes:
                lines.append(f"  • Notes: {notes}")

            lines.extend([
                "",
                f"Task ID: {result}",
                "",
                "The backup is running in the background.",
                "Use list_backups to verify when complete.",
            ])

            return [Content(type="text", text="\n".join(lines))]

        except Exception as e:
            return self._err(f"create backup for {vmid}", e)

    def restore_backup(
        self,
        node: str,
        archive: str,
        vmid: str,
        storage: Optional[str] = None,
        unique: bool = True,
    ) -> List[Content]:
        """Restore a VM or container from a backup.

        Parameters:
            node: Target node for restore
            archive: Backup volume ID (from list_backups)
            vmid: New VM/container ID for the restored machine
            storage: Target storage for disks (optional)
            unique: Generate unique MAC addresses (default: true)

        Returns:
            List[Content] with restore result
        """
        try:
            # Determine if this is a VM or container backup
            is_lxc = "/ct/" in archive.lower() or "vzdump-lxc" in archive.lower()

            params: Dict[str, Any] = {
                "archive": archive,
                "vmid": int(vmid),
            }

            if storage:
                params["storage"] = storage

            if unique:
                params["unique"] = 1

            if is_lxc:
                result = self.proxmox.nodes(node).lxc.post(**params)
                vm_type = "Container"
            else:
                result = self.proxmox.nodes(node).qemu.post(**params)
                vm_type = "VM"

            lines = [
                f"♻️ {vm_type} Restore Started",
                "",
                f"  • New ID: {vmid}",
                f"  • From: {archive}",
                f"  • Target Node: {node}",
            ]

            if storage:
                lines.append(f"  • Target Storage: {storage}")

            lines.append(f"  • Unique MACs: {'Yes' if unique else 'No'}")

            lines.extend([
                "",
                f"Task ID: {result}",
                "",
                "The restore is running in the background.",
                f"The {vm_type.lower()} will be available once the task completes.",
            ])

            return [Content(type="text", text="\n".join(lines))]

        except Exception as e:
            return self._err(f"restore backup to {vmid}", e)

    def delete_backup(
        self,
        node: str,
        storage: str,
        volid: str,
    ) -> List[Content]:
        """Delete a backup file from storage.

        Parameters:
            node: Node name
            storage: Storage pool name
            volid: Backup volume ID to delete

        Returns:
            List[Content] with deletion result
        """
        try:
            # Check if backup is protected
            content = _as_list(
                self.proxmox.nodes(node).storage(storage).content.get(content="backup")
            )

            backup_info = None
            for item in content:
                if _get(item, "volid") == volid:
                    backup_info = item
                    break

            if backup_info and _get(backup_info, "protected"):
                return [Content(
                    type="text",
                    text=f"Error: Backup '{volid}' is protected and cannot be deleted.\n"
                         f"Remove protection first if you want to delete it."
                )]

            result = self.proxmox.nodes(node).storage(storage).content(volid).delete()

            lines = [
                "🗑️ Backup Deleted",
                "",
                f"  • Volume: {volid}",
                f"  • Storage: {storage}",
                f"  • Node: {node}",
            ]

            if result:
                lines.extend(["", f"Task ID: {result}"])

            return [Content(type="text", text="\n".join(lines))]

        except Exception as e:
            return self._err(f"delete backup '{volid}'", e)
