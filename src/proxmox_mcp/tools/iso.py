"""ISO and template management tools for Proxmox MCP."""
from typing import List, Dict, Optional, Any
import json
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


class ISOTools(ProxmoxTool):
    """ISO and template management tools."""

    def _json_fmt(self, data: Any) -> List[Content]:
        """Return raw JSON string."""
        return [Content(type="text", text=json.dumps(data, indent=2, sort_keys=True))]

    def _err(self, action: str, e: Exception) -> List[Content]:
        """Handle errors."""
        if hasattr(self, "_handle_error"):
            self._handle_error(action, e)
        return [Content(type="text", text=f"Error: {action} - {str(e)}")]

    def _get_storage_content(
        self, content_type: str, node: Optional[str] = None, storage: Optional[str] = None
    ) -> List[Dict]:
        """Get storage content filtered by type across nodes/storages."""
        results = []
        nodes = _as_list(self.proxmox.nodes.get())

        for n in nodes:
            node_name = _get(n, "node")
            if not node_name:
                continue
            if node and node_name != node:
                continue

            storages = _as_list(self.proxmox.nodes(node_name).storage.get())
            for s in storages:
                storage_name = _get(s, "storage")
                if not storage_name:
                    continue
                if storage and storage_name != storage:
                    continue

                # Check if storage supports this content type
                content_types = _get(s, "content", "")
                if content_type not in content_types:
                    continue

                try:
                    content = _as_list(
                        self.proxmox.nodes(node_name).storage(storage_name).content.get(
                            content=content_type
                        )
                    )
                    for item in content:
                        item["_node"] = node_name
                        item["_storage"] = storage_name
                        results.append(item)
                except Exception:
                    continue

        return results

    def list_isos(
        self,
        node: Optional[str] = None,
        storage: Optional[str] = None,
    ) -> List[Content]:
        """List available ISO images.

        Parameters:
            node: Filter by node (optional)
            storage: Filter by storage pool (optional)

        Returns:
            List[Content] with ISO information
        """
        try:
            isos = self._get_storage_content("iso", node, storage)

            if not isos:
                msg = "No ISO images found"
                if node:
                    msg += f" on node {node}"
                if storage:
                    msg += f" in storage {storage}"
                return [Content(type="text", text=msg)]

            lines = ["💿 Available ISO Images", ""]

            for iso in sorted(isos, key=lambda x: _get(x, "volid", "")):
                volid = _get(iso, "volid", "unknown")
                size = _get(iso, "size", 0)
                node_name = _get(iso, "_node", "?")
                storage_name = _get(iso, "_storage", "?")

                # Extract filename from volid (format: storage:iso/filename.iso)
                filename = volid.split("/")[-1] if "/" in volid else volid

                lines.append(f"  💿 {filename}")
                lines.append(f"     Size: {_b2h(size)}")
                lines.append(f"     Storage: {storage_name} @ {node_name}")
                lines.append(f"     Volume ID: {volid}")
                lines.append("")

            return [Content(type="text", text="\n".join(lines).rstrip())]

        except Exception as e:
            return self._err("list ISOs", e)

    def list_templates(
        self,
        node: Optional[str] = None,
        storage: Optional[str] = None,
    ) -> List[Content]:
        """List available OS templates for containers.

        Parameters:
            node: Filter by node (optional)
            storage: Filter by storage pool (optional)

        Returns:
            List[Content] with template information
        """
        try:
            templates = self._get_storage_content("vztmpl", node, storage)

            if not templates:
                msg = "No OS templates found"
                if node:
                    msg += f" on node {node}"
                if storage:
                    msg += f" in storage {storage}"
                return [Content(type="text", text=msg)]

            lines = ["📦 Available OS Templates", ""]

            for tmpl in sorted(templates, key=lambda x: _get(x, "volid", "")):
                volid = _get(tmpl, "volid", "unknown")
                size = _get(tmpl, "size", 0)
                node_name = _get(tmpl, "_node", "?")
                storage_name = _get(tmpl, "_storage", "?")

                # Extract filename from volid
                filename = volid.split("/")[-1] if "/" in volid else volid

                lines.append(f"  📦 {filename}")
                lines.append(f"     Size: {_b2h(size)}")
                lines.append(f"     Storage: {storage_name} @ {node_name}")
                lines.append(f"     Volume ID: {volid}")
                lines.append("")

            lines.append("Use the Volume ID with create_container's ostemplate parameter.")

            return [Content(type="text", text="\n".join(lines).rstrip())]

        except Exception as e:
            return self._err("list templates", e)

    def download_iso(
        self,
        node: str,
        storage: str,
        url: str,
        filename: str,
        checksum: Optional[str] = None,
        checksum_algorithm: str = "sha256",
    ) -> List[Content]:
        """Download an ISO image from a URL to Proxmox storage.

        Parameters:
            node: Target node name
            storage: Target storage pool
            url: URL to download from
            filename: Target filename (e.g., 'ubuntu-22.04.iso')
            checksum: Optional checksum for verification
            checksum_algorithm: Algorithm (sha256, sha512, md5)

        Returns:
            List[Content] with download result
        """
        try:
            params: Dict[str, Any] = {
                "url": url,
                "filename": filename,
                "content": "iso",
            }

            if checksum:
                params["checksum"] = checksum
                params["checksum-algorithm"] = checksum_algorithm

            result = self.proxmox.nodes(node).storage(storage)("download-url").post(**params)

            lines = [
                "⬇️ ISO Download Started",
                "",
                f"  • Filename: {filename}",
                f"  • URL: {url}",
                f"  • Storage: {storage} @ {node}",
            ]

            if checksum:
                lines.append(f"  • Checksum: {checksum_algorithm.upper()}")

            lines.extend([
                "",
                f"Task ID: {result}",
                "",
                "The download is running in the background.",
                "Use list_isos to verify when complete.",
            ])

            return [Content(type="text", text="\n".join(lines))]

        except Exception as e:
            return self._err(f"download ISO '{filename}'", e)

    def delete_iso(
        self,
        node: str,
        storage: str,
        filename: str,
    ) -> List[Content]:
        """Delete an ISO or template from storage.

        Parameters:
            node: Node name
            storage: Storage pool name
            filename: ISO/template filename or full volume ID

        Returns:
            List[Content] with deletion result
        """
        try:
            # Construct volume ID if just filename provided
            if ":" not in filename:
                # Try to find the volume ID
                content = _as_list(
                    self.proxmox.nodes(node).storage(storage).content.get()
                )
                volid = None
                for item in content:
                    item_volid = _get(item, "volid", "")
                    if filename in item_volid:
                        volid = item_volid
                        break

                if not volid:
                    return [Content(
                        type="text",
                        text=f"Error: Could not find '{filename}' in {storage} on {node}"
                    )]
            else:
                volid = filename

            # Delete the content
            result = self.proxmox.nodes(node).storage(storage).content(volid).delete()

            lines = [
                "🗑️ ISO/Template Deleted",
                "",
                f"  • Volume: {volid}",
                f"  • Storage: {storage}",
                f"  • Node: {node}",
            ]

            if result:
                lines.extend(["", f"Task ID: {result}"])

            return [Content(type="text", text="\n".join(lines))]

        except Exception as e:
            return self._err(f"delete ISO/template '{filename}'", e)
