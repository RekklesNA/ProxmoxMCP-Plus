"""Validation and non-destructive merging of Proxmox guest device settings."""
from __future__ import annotations

import ipaddress
import re
from typing import Any


def bridge_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,14}", value):
        raise ValueError("network_bridge must be a valid interface name")
    return value


def parse_device(value: str) -> dict[str, str]:
    parts = {}
    for field in value.split(","):
        key, sep, val = field.partition("=")
        if not sep or not key or key in parts:
            raise ValueError("Existing network configuration cannot be safely merged")
        parts[key] = val
    return parts


def container_network(existing: str | None = None, *, network_bridge: str | None = None,
                      ip: str | None = None, gw: str | None = None,
                      ip6: str | None = None, gw6: str | None = None) -> str:
    settings = parse_device(existing) if existing else {"name": "eth0", "bridge": "vmbr0", "ip": "dhcp"}
    if network_bridge is not None:
        settings["bridge"] = bridge_name(network_bridge)
    for key, value, family, dynamic in [("ip", ip, 4, {"dhcp", "manual"}), ("ip6", ip6, 6, {"auto", "dhcp", "manual"})]:
        if value is None:
            continue
        if value not in dynamic:
            if "/" not in value or ipaddress.ip_interface(value).version != family:
                raise ValueError(f"{key} must be IPv{family}/CIDR or a supported automatic mode")
        settings[key] = value
        if value in dynamic:
            settings.pop("gw" if family == 4 else "gw6", None)
    for key, value, family, address_key in [("gw", gw, 4, "ip"), ("gw6", gw6, 6, "ip6")]:
        if value is None:
            continue
        if value == "":
            settings.pop(key, None)
            continue
        if ipaddress.ip_address(value).version != family:
            raise ValueError(f"{key} must be an IPv{family} address")
        if "/" not in settings.get(address_key, ""):
            raise ValueError(f"{key} requires a static {address_key} address")
        settings[key] = value
    return ",".join(f"{key}={value}" for key, value in settings.items())


def vm_media(iso_volume: str | None, cdrom_device: str, boot_order: str | None,
             existing: dict[str, Any] | None = None) -> dict[str, str]:
    payload = {}
    if iso_volume is not None:
        if not re.fullmatch(r"(?:ide[0-3]|sata[0-5]|scsi(?:[0-9]|[12][0-9]|30))", cdrom_device):
            raise ValueError("cdrom_device must be a valid IDE, SATA or SCSI device")
        if iso_volume != "none" and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*:iso/[^,\s/\\]+\.iso", iso_volume, flags=re.IGNORECASE):
            raise ValueError("iso_volume must be a storage ISO volume ID or 'none' to eject")
        current = (existing or {}).get(cdrom_device)
        if current and ("media=cdrom" not in current.split(",") or "cloudinit" in current):
            raise ValueError("Refusing to replace an existing disk or cloud-init drive; choose another cdrom_device")
        payload[cdrom_device] = f"{iso_volume},media=cdrom"
    if boot_order is not None:
        if not re.fullmatch(r"(?:ide[0-3]|sata[0-5]|scsi(?:[0-9]|[12][0-9]|30)|virtio(?:[0-9]|1[0-5])|net[0-9])(?:;(?:ide[0-3]|sata[0-5]|scsi(?:[0-9]|[12][0-9]|30)|virtio(?:[0-9]|1[0-5])|net[0-9]))*", boot_order):
            raise ValueError("boot_order must be semicolon-separated VM device names")
        if len(set(boot_order.split(";"))) != len(boot_order.split(";")):
            raise ValueError("boot_order must not contain duplicate devices")
        payload["boot"] = f"order={boot_order}"
    return payload
