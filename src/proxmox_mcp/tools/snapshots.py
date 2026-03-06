"""Snapshot management tools for Proxmox MCP."""
from typing import List, Dict, Optional, Any
import json
from mcp.types import TextContent as Content
from proxmox_mcp.tools.base import ProxmoxTool


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


class SnapshotTools(ProxmoxTool):
    """Snapshot management tools for VMs and containers."""

    def _json_fmt(self, data: Any) -> List[Content]:
        """Return raw JSON string."""
        return [Content(type="text", text=json.dumps(data, indent=2, sort_keys=True))]

    def _err(self, action: str, e: Exception) -> List[Content]:
        """Handle errors."""
        if hasattr(self, "_handle_error"):
            self._handle_error(action, e)
        return [Content(type="text", text=f"Error: {action} - {str(e)}")]

    def list_snapshots(
        self,
        node: str,
        vmid: str,
        vm_type: str = "qemu",
    ) -> List[Content]:
        """List all snapshots for a VM or container.

        Parameters:
            node: Host node name (e.g., 'pve')
            vmid: VM or container ID
            vm_type: 'qemu' for VMs, 'lxc' for containers

        Returns:
            List[Content] with snapshot information
        """
        try:
            if vm_type == "lxc":
                snapshots = _as_list(
                    self.proxmox.nodes(node).lxc(vmid).snapshot.get()
                )
            else:
                snapshots = _as_list(
                    self.proxmox.nodes(node).qemu(vmid).snapshot.get()
                )

            if not snapshots:
                return [Content(
                    type="text",
                    text=f"No snapshots found for {vm_type.upper()} {vmid} on node {node}"
                )]

            lines = [
                f"📸 Snapshots for {vm_type.upper()} {vmid} on {node}",
                ""
            ]

            for snap in snapshots:
                name = _get(snap, "name", "unknown")
                description = _get(snap, "description", "")
                snaptime = _get(snap, "snaptime")
                parent = _get(snap, "parent", "")
                vmstate = _get(snap, "vmstate", False)

                # Skip 'current' pseudo-snapshot
                if name == "current":
                    continue

                lines.append(f"  📷 {name}")
                if description:
                    lines.append(f"     Description: {description}")
                if snaptime:
                    from datetime import datetime
                    try:
                        dt = datetime.fromtimestamp(snaptime)
                        lines.append(f"     Created: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
                    except Exception:
                        lines.append(f"     Created: {snaptime}")
                if parent:
                    lines.append(f"     Parent: {parent}")
                if vmstate:
                    lines.append(f"     RAM State: Included")
                lines.append("")

            return [Content(type="text", text="\n".join(lines).rstrip())]

        except Exception as e:
            return self._err(f"list snapshots for {vm_type} {vmid}", e)

    def create_snapshot(
        self,
        node: str,
        vmid: str,
        snapname: str,
        description: Optional[str] = None,
        vmstate: bool = False,
        vm_type: str = "qemu",
    ) -> List[Content]:
        """Create a snapshot of a VM or container.

        Parameters:
            node: Host node name
            vmid: VM or container ID
            snapname: Snapshot name (no spaces)
            description: Optional description
            vmstate: Include RAM state (VMs only)
            vm_type: 'qemu' for VMs, 'lxc' for containers

        Returns:
            List[Content] with creation result
        """
        try:
            params: Dict[str, Any] = {"snapname": snapname}

            if description:
                params["description"] = description

            if vm_type == "lxc":
                result = self.proxmox.nodes(node).lxc(vmid).snapshot.post(**params)
            else:
                if vmstate:
                    params["vmstate"] = 1
                result = self.proxmox.nodes(node).qemu(vmid).snapshot.post(**params)

            lines = [
                "📸 Snapshot Created Successfully",
                "",
                f"  • Name: {snapname}",
                f"  • {vm_type.upper()} ID: {vmid}",
                f"  • Node: {node}",
            ]
            if description:
                lines.append(f"  • Description: {description}")
            if vmstate and vm_type == "qemu":
                lines.append(f"  • RAM State: Included")

            lines.extend([
                "",
                f"Task ID: {result}",
                "",
                "Next steps:",
                f"  • List snapshots: list_snapshots node='{node}' vmid='{vmid}' vm_type='{vm_type}'",
                f"  • Rollback: rollback_snapshot node='{node}' vmid='{vmid}' snapname='{snapname}' vm_type='{vm_type}'",
            ])

            return [Content(type="text", text="\n".join(lines))]

        except Exception as e:
            return self._err(f"create snapshot '{snapname}' for {vm_type} {vmid}", e)

    def delete_snapshot(
        self,
        node: str,
        vmid: str,
        snapname: str,
        vm_type: str = "qemu",
    ) -> List[Content]:
        """Delete a snapshot.

        Parameters:
            node: Host node name
            vmid: VM or container ID
            snapname: Snapshot name to delete
            vm_type: 'qemu' for VMs, 'lxc' for containers

        Returns:
            List[Content] with deletion result
        """
        try:
            if vm_type == "lxc":
                result = self.proxmox.nodes(node).lxc(vmid).snapshot(snapname).delete()
            else:
                result = self.proxmox.nodes(node).qemu(vmid).snapshot(snapname).delete()

            lines = [
                "🗑️ Snapshot Deleted",
                "",
                f"  • Name: {snapname}",
                f"  • {vm_type.upper()} ID: {vmid}",
                f"  • Node: {node}",
                "",
                f"Task ID: {result}",
            ]

            return [Content(type="text", text="\n".join(lines))]

        except Exception as e:
            return self._err(f"delete snapshot '{snapname}' for {vm_type} {vmid}", e)

    def rollback_snapshot(
        self,
        node: str,
        vmid: str,
        snapname: str,
        vm_type: str = "qemu",
    ) -> List[Content]:
        """Rollback to a snapshot.

        WARNING: This will stop the VM/container and restore to the snapshot state!
        NOTE: For ZFS storage, this will delete any snapshots newer than the target.

        Parameters:
            node: Host node name
            vmid: VM or container ID
            snapname: Snapshot name to restore
            vm_type: 'qemu' for VMs, 'lxc' for containers

        Returns:
            List[Content] with rollback result
        """
        try:
            # For ZFS-based storage, we may need to delete newer snapshots first
            # Get current snapshots to check if target is most recent
            if vm_type == "lxc":
                snapshots = _as_list(self.proxmox.nodes(node).lxc(vmid).snapshot.get())
            else:
                snapshots = _as_list(self.proxmox.nodes(node).qemu(vmid).snapshot.get())

            # Find snapshots that are children of our target (newer snapshots)
            # These need to be deleted for ZFS rollback to work
            deleted_snaps = []
            for snap in snapshots:
                parent = _get(snap, "parent", "")
                snap_name = _get(snap, "name", "")
                if snap_name != "current" and parent == snapname:
                    # This snapshot is a child of our target, delete it
                    try:
                        if vm_type == "lxc":
                            self.proxmox.nodes(node).lxc(vmid).snapshot(snap_name).delete()
                        else:
                            self.proxmox.nodes(node).qemu(vmid).snapshot(snap_name).delete()
                        deleted_snaps.append(snap_name)
                    except Exception:
                        pass

            # Now perform the rollback
            if vm_type == "lxc":
                result = self.proxmox.nodes(node).lxc(vmid).snapshot(snapname).rollback.post()
            else:
                result = self.proxmox.nodes(node).qemu(vmid).snapshot(snapname).rollback.post()

            lines = [
                "⏪ Snapshot Rollback Initiated",
                "",
                f"  • Restoring to: {snapname}",
                f"  • {vm_type.upper()} ID: {vmid}",
                f"  • Node: {node}",
            ]

            if deleted_snaps:
                lines.append(f"  • Deleted newer snapshots: {', '.join(deleted_snaps)}")

            lines.extend([
                "",
                "⚠️  WARNING: VM/container will be stopped during rollback!",
                "",
                f"Task ID: {result}",
                "",
                "The VM/container will be restored to its state at the time of the snapshot.",
            ])

            return [Content(type="text", text="\n".join(lines))]

        except Exception as e:
            return self._err(f"rollback to snapshot '{snapname}' for {vm_type} {vmid}", e)
