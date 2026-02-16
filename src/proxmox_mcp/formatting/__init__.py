"""
Proxmox MCP formatting package for styled output.
"""

from proxmox_mcp.formatting.theme import ProxmoxTheme
from proxmox_mcp.formatting.colors import ProxmoxColors
from proxmox_mcp.formatting.formatters import ProxmoxFormatters
from proxmox_mcp.formatting.templates import ProxmoxTemplates
from proxmox_mcp.formatting.components import ProxmoxComponents

__all__ = [
    'ProxmoxTheme',
    'ProxmoxColors',
    'ProxmoxFormatters',
    'ProxmoxTemplates',
    'ProxmoxComponents'
]
