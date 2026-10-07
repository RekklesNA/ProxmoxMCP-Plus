"""Select node-local storage by content, availability and known capacity."""

from typing import Any
from proxmox_mcp.security.resources import validate_segment


def select_storage(api: Any, node: str, content: str, requested: str | None, disk_gib: int) -> dict[str, Any]:
    validate_segment(node)
    if disk_gib <= 0:
        raise ValueError("Disk size must be positive")
    if requested is not None:
        validate_segment(requested)
    inventory = api.nodes(node).storage.get()
    if not isinstance(inventory, list):
        raise RuntimeError("Node storage inventory is unavailable")
    candidates = []
    for item in inventory:
        if not isinstance(item, dict) or not item.get("storage"):
            continue
        if requested is not None and item["storage"] != requested:
            continue
        types = item.get("content", [])
        types = types.split(",") if isinstance(types, str) else types
        if content not in types or not item.get("active", True) or not item.get("enabled", True):
            continue
        available = item.get("avail")
        if available is not None and int(available) < disk_gib * 1024**3:
            continue
        candidates.append(item)
    if not candidates:
        raise ValueError("No available node storage supports the requested content and disk size")
    preferred = {"local-lvm": 0, "vm-storage": 1}
    return min(candidates, key=lambda item: (preferred.get(item["storage"], 2), item["storage"]))
