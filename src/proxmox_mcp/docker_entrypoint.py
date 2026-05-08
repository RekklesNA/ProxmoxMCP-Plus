"""Docker runtime selector for OpenAPI and native MCP HTTP modes."""

from __future__ import annotations

import os
import sys
from collections.abc import MutableMapping


OPENAPI_MODES = {"openapi", "api", "rest"}
MCP_HTTP_MODES = {"mcp-http", "streamable-http", "streamable", "mcp"}


def build_command(mode: str | None = None, environ: MutableMapping[str, str] | None = None) -> list[str]:
    env = environ if environ is not None else os.environ
    selected_mode = (mode or env.get("PROXMOX_MCP_MODE", "openapi")).strip().lower()

    if selected_mode in OPENAPI_MODES:
        host = env.get("API_HOST", "0.0.0.0")
        port = env.get("API_PORT", "8811")
        return [
            sys.executable,
            "-m",
            "proxmox_mcp.openapi_proxy",
            "--host",
            host,
            "--port",
            port,
            "--",
            sys.executable,
            "-m",
            "proxmox_mcp.server",
        ]

    if selected_mode in MCP_HTTP_MODES:
        env.setdefault("MCP_HOST", "0.0.0.0")
        env.setdefault("MCP_PORT", "8000")
        env.setdefault("MCP_TRANSPORT", "STREAMABLE_HTTP")
        return [sys.executable, "-m", "proxmox_mcp.server"]

    valid_modes = ", ".join(sorted(OPENAPI_MODES | MCP_HTTP_MODES))
    raise ValueError(f"Unsupported PROXMOX_MCP_MODE={selected_mode!r}. Expected one of: {valid_modes}")


def main() -> None:
    command = build_command()
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
