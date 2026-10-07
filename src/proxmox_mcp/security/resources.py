"""Validate resource identifiers before constructing Proxmox API paths."""

from __future__ import annotations

import re
from typing import Any


def validate_segment(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*", value):
        raise ValueError("Invalid resource path segment")
    return value


def validate_guest_id(value: Any) -> str:
    """Guest IDs are positive ASCII integers, never arbitrary URL paths."""
    text = str(value) if isinstance(value, int) else value
    if not isinstance(text, str) or not re.fullmatch(r"[0-9]+", text) or int(text) <= 0:
        raise ValueError("Guest ID must be a positive ASCII integer")
    return text


def submit_snapshot_rollback(api: Any, node: str, vmid: Any, snapname: str, vm_type: str) -> Any:
    """Check fresh snapshot dependencies on initial submission and every retry."""
    validate_segment(node)
    validate_guest_id(vmid)
    validate_segment(snapname)
    if vm_type not in {"qemu", "lxc"}:
        raise ValueError("Unsupported guest type")
    guest = getattr(api.nodes(node), vm_type)(vmid)
    inventory = guest.snapshot.get()
    if isinstance(inventory, dict):
        inventory = inventory.get("data")
    if not isinstance(inventory, list) or any(not isinstance(item, dict) for item in inventory):
        raise RuntimeError("Snapshot inventory is unavailable or incomplete")
    children = [str(item.get("name")) for item in inventory
                if item.get("name") != "current" and item.get("parent") == snapname]
    if children:
        raise ValueError(f"Refusing to rollback because snapshot '{snapname}' has newer child snapshots: {', '.join(children)}. Delete those snapshots explicitly first, then retry rollback.")
    return guest.snapshot(snapname).rollback.post()


def validate_volume(storage: str, volid: str) -> str:
    validate_segment(storage)
    if not isinstance(volid, str) or not volid.startswith(storage + ":"):
        raise ValueError("Volume must belong to the selected storage")
    path = volid.split(":", 1)[1]
    if any(ord(ch) < 32 or ord(ch) == 127 or ch in "%?#\\" for ch in path):
        raise ValueError("Invalid volume path")
    if any(part in {"", ".", ".."} for part in path.split("/")):
        raise ValueError("Invalid volume path")
    return volid


def resolve_volume(api: Any, node: str, storage: str, identifier: str, types: set[str], *, filename: bool = False) -> str:
    """Require a unique, existing, unprotected volume of an allowed type."""
    validate_segment(node)
    validate_segment(storage)
    if ":" in identifier:
        validate_volume(storage, identifier)
    elif not filename or "/" in identifier or identifier in {"", ".", ".."}:
        raise ValueError("A valid volume ID is required")
    content = api.nodes(node).storage(storage).content.get()
    if not isinstance(content, list):
        raise RuntimeError("Storage content inventory is unavailable")
    matches = [item for item in content if isinstance(item, dict)
               and item.get("content") in types
               and (item.get("volid") == identifier or (filename and ":" not in identifier
                    and str(item.get("volid", "")).rsplit("/", 1)[-1] == identifier))]
    if len(matches) != 1:
        raise ValueError("Volume not found or ambiguous within the permitted content types")
    item = matches[0]
    if item.get("protected") in {True, 1, "1"}:
        raise ValueError("Volume is protected and cannot be deleted")
    return validate_volume(storage, item["volid"])


def delete_volume(api: Any, node: str, storage: str, identifier: str, types: set[str], *, filename: bool = False) -> Any:
    volid = resolve_volume(api, node, storage, identifier, types, filename=filename)
    return api.nodes(node).storage(storage).content(volid).delete()
