"""
Color utilities for Proxmox MCP output styling.
"""
from typing import Optional
from proxmox_mcp.formatting.theme import ProxmoxTheme

class ProxmoxColors:
    """ANSI color definitions and utilities for terminal output."""
    
    # Foreground colors
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    
    # Background colors
    BG_BLACK = '\033[40m'
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    BG_YELLOW = '\033[43m'
    BG_BLUE = '\033[44m'
    BG_MAGENTA = '\033[45m'
    BG_CYAN = '\033[46m'
    BG_WHITE = '\033[47m'
    
    # Styles
    BOLD = '\033[1m'
    DIM = '\033[2m'
    ITALIC = '\033[3m'
    UNDERLINE = '\033[4m'
    BLINK = '\033[5m'
    REVERSE = '\033[7m'
    HIDDEN = '\033[8m'
    STRIKE = '\033[9m'
    
    # Reset
    RESET = '\033[0m'
    
    @classmethod
    def colorize(cls, text: str, color: str, style: Optional[str] = None) -> str:
        """Add color and optional style to text with theme awareness.
        
        Args:
            text: Text to colorize
            color: ANSI color code
            style: Optional ANSI style code
            
        Returns:
            Formatted text string
        """
        if not ProxmoxTheme.USE_COLORS:
            return text
            
        if style:
            return f"{style}{color}{text}{cls.RESET}"
        return f"{color}{text}{cls.RESET}"
    
    @classmethod
    def status_color(cls, status: str) -> str:
        """Get appropriate color for a status value.
        
        Args:
            status: Status string to get color for
            
        Returns:
            ANSI color code
        """
        status = status.lower()
        if status in ['online', 'running', 'success']:
            return cls.GREEN
        elif status in ['offline', 'stopped', 'error']:
            return cls.RED
        elif status in ['pending', 'warning']:
            return cls.YELLOW
        return cls.BLUE
    
    @classmethod
    def resource_color(cls, resource_type: str) -> str:
        """Get appropriate color for a resource type.
        
        Args:
            resource_type: Resource type to get color for
            
        Returns:
            ANSI color code
        """
        resource_type = resource_type.lower()
        if resource_type in ['node', 'vm', 'container']:
            return cls.CYAN
        elif resource_type in ['cpu', 'memory', 'network']:
            return cls.YELLOW
        elif resource_type in ['storage', 'disk']:
            return cls.MAGENTA
        return cls.BLUE
    
    @classmethod
    def metric_color(cls, value: float, warning: float = 80.0, critical: float = 90.0) -> str:
        """Get appropriate color for a metric value based on thresholds.
        
        Args:
            value: Metric value (typically percentage)
            warning: Warning threshold
            critical: Critical threshold
            
        Returns:
            ANSI color code
        """
        if value >= critical:
            return cls.RED
        elif value >= warning:
            return cls.YELLOW
        return cls.GREEN
