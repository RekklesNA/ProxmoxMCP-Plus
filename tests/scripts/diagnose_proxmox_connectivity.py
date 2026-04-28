"""Diagnose whether this machine can reach the configured Proxmox environment."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
DEFAULT_CONFIG_PATH = ROOT / "proxmox-config" / "config.json"
DEFAULT_LIVE_CONFIG_PATH = ROOT / "proxmox-config" / "config.live.json"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def tcp_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def ssh_effective_config(alias: str) -> dict[str, str] | None:
    try:
        result = subprocess.run(
            ["ssh", "-G", alias],
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    parsed: dict[str, str] = {}
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            parsed[parts[0]] = parts[1]
    return parsed


def resolve_diagnostic_config_path() -> Path:
    explicit_e2e = os.getenv("PROXMOX_MCP_E2E_CONFIG")
    if explicit_e2e:
        return Path(explicit_e2e)
    if DEFAULT_LIVE_CONFIG_PATH.exists():
        return DEFAULT_LIVE_CONFIG_PATH
    explicit_runtime = os.getenv("PROXMOX_MCP_CONFIG")
    if explicit_runtime:
        return Path(explicit_runtime)
    return DEFAULT_CONFIG_PATH


def main() -> int:
    from proxmox_mcp.config.loader import load_config

    config_path = resolve_diagnostic_config_path()
    config = load_config(str(config_path))

    report: dict[str, Any] = {
        "config_path": str(config_path),
        "config_role": "live" if config_path == DEFAULT_LIVE_CONFIG_PATH or os.getenv("PROXMOX_MCP_E2E_CONFIG") else "runtime",
        "proxmox": {
            "host": config.proxmox.host,
            "port": config.proxmox.port,
            "reachable": tcp_reachable(str(config.proxmox.host), int(config.proxmox.port)),
        },
        "ssh": None,
        "ssh_aliases": {},
    }

    if config.ssh is not None:
        report["ssh"] = {
            "port": config.ssh.port,
            "host_overrides": config.ssh.host_overrides,
            "override_reachability": {
                alias: tcp_reachable(str(host), int(config.ssh.port))
                for alias, host in sorted((config.ssh.host_overrides or {}).items())
            },
        }

    aliases_to_check: set[str] = set()
    ssh_config_path = Path.home() / ".ssh" / "config"
    if ssh_config_path.exists():
        for line in ssh_config_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if not stripped.lower().startswith("host "):
                continue
            for token in stripped.split()[1:]:
                if "*" in token or "?" in token:
                    continue
                aliases_to_check.add(token)

    for alias in sorted(aliases_to_check):
        effective = ssh_effective_config(alias)
        if effective is None:
            continue
        hostname = effective.get("hostname", alias)
        port = int(effective.get("port", "22"))
        report["ssh_aliases"][alias] = {
            "hostname": hostname,
            "port": port,
            "proxyjump": effective.get("proxyjump"),
            "reachable": tcp_reachable(hostname, port),
        }

    proxmox_host = str(config.proxmox.host)
    if (
        config_path == DEFAULT_CONFIG_PATH
        and proxmox_host in {"localhost", "127.0.0.1", "::1"}
    ):
        report["recommendation"] = (
            "This is the default runtime config and it still points at a local-only Proxmox API target. "
            "Create proxmox-config/config.live.json for real e2e runs or set PROXMOX_MCP_E2E_CONFIG."
        )

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
