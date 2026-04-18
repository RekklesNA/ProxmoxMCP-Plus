"""
Proxmox MCP Server - A Model Context Protocol server for interacting with Proxmox hypervisors.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .server import ProxmoxMCPServer

__version__ = "0.2.1"
__all__ = ["ProxmoxMCPServer"]


def __getattr__(name: str):
    if name == "ProxmoxMCPServer":
        from .server import ProxmoxMCPServer

        return ProxmoxMCPServer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
