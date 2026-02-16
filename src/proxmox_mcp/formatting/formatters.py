"""
Core formatting functions for Proxmox MCP output.
"""
from typing import List, Union, Dict, Any
from proxmox_mcp.formatting.theme import ProxmoxTheme
from proxmox_mcp.formatting.colors import ProxmoxColors

class ProxmoxFormatters:
    """Core formatting functions for Proxmox data."""
    
    @staticmethod
    def format_bytes(bytes_value: int) -> str:
        """Format bytes with proper units.
        
        Args:
            bytes_value: Number of bytes
            
        Returns:
            Formatted string with appropriate unit
        """
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_value < 1024:
                return f"{bytes_value:.2f} {unit}"
            bytes_value /= 1024
        return f"{bytes_value:.2f} TB"
    
    @staticmethod
    def format_uptime(seconds: int) -> str:
        """Format uptime in seconds to human readable format.
        
        Args:
            seconds: Uptime in seconds
            
        Returns:
            Formatted uptime string
        """
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        minutes = (seconds % 3600) // 60
        
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
            
        return f"{ProxmoxTheme.METRICS['uptime']} " + " ".join(parts) if parts else "0m"
    
    @staticmethod
    def format_percentage(value: float, warning: float = 80.0, critical: float = 90.0) -> str:
        """Format percentage with color based on thresholds.
        
        Args:
            value: Percentage value
            warning: Warning threshold
            critical: Critical threshold
            
        Returns:
            Formatted percentage string
        """
        color = ProxmoxColors.metric_color(value, warning, critical)
        return ProxmoxColors.colorize(f"{value:.1f}%", color)
    
    @staticmethod
    def format_status(status: str) -> str:
        """Format status with emoji and color.
        
        Args:
            status: Status string
            
        Returns:
            Formatted status string
        """
        status = status.lower()
        emoji = ProxmoxTheme.get_status_emoji(status)
        color = ProxmoxColors.status_color(status)
        return f"{emoji} {ProxmoxColors.colorize(status.upper(), color)}"
    
    @staticmethod
    def format_resource_header(resource_type: str, name: str) -> str:
        """Format resource header with emoji and styling.
        
        Args:
            resource_type: Type of resource
            name: Resource name
            
        Returns:
            Formatted header string
        """
        emoji = ProxmoxTheme.get_resource_emoji(resource_type)
        color = ProxmoxColors.resource_color(resource_type)
        return f"\n{emoji} {ProxmoxColors.colorize(name, color, ProxmoxColors.BOLD)}"
    
    @staticmethod
    def format_section_header(title: str, section_type: str = 'header') -> str:
        """Format section header with emoji and border.
        
        Args:
            title: Section title
            section_type: Type of section for emoji selection
            
        Returns:
            Formatted section header
        """
        emoji = ProxmoxTheme.get_section_emoji(section_type)
        header = f"{emoji} {title}"
        border = "═" * len(header)
        return f"\n{header}\n{border}\n"
    
    @staticmethod
    def format_key_value(key: str, value: str, emoji: str = "") -> str:
        """Format key-value pair with optional emoji.
        
        Args:
            key: Label/key
            value: Value to display
            emoji: Optional emoji prefix
            
        Returns:
            Formatted key-value string
        """
        key_str = ProxmoxColors.colorize(key, ProxmoxColors.CYAN)
        prefix = f"{emoji} " if emoji else ""
        return f"{prefix}{key_str}: {value}"
    
    @staticmethod
    def format_command_output(success: bool, command: str, output: str, error: str = None) -> str:
        """Format command execution output.
        
        Args:
            success: Whether command succeeded
            command: The command that was executed
            output: Command output
            error: Optional error message
            
        Returns:
            Formatted command output string
        """
        result = [
            f"{ProxmoxTheme.ACTIONS['command']} Console Command Result",
            f"  • Status: {'SUCCESS' if success else 'FAILED'}",
            f"  • Command: {command}",
            "",
            "Output:",
            output.strip()
        ]
        
        if error:
            result.extend([
                "",
                "Error:",
                error.strip()
            ])
            
        return "\n".join(result)
