"""
Reusable UI components for Proxmox MCP output.
"""
from typing import List, Optional
from proxmox_mcp.formatting.colors import ProxmoxColors
from proxmox_mcp.formatting.theme import ProxmoxTheme

class ProxmoxComponents:
    """Reusable UI components for formatted output."""
    
    @staticmethod
    def create_table(headers: List[str], rows: List[List[str]], title: Optional[str] = None) -> str:
        """Create an ASCII table with optional title.
        
        Args:
            headers: List of column headers
            rows: List of row data
            title: Optional table title
            
        Returns:
            Formatted table string
        """
        # Calculate column widths considering multi-line content
        widths = [len(header) for header in headers]
        for row in rows:
            for i, cell in enumerate(row):
                cell_lines = str(cell).split('\n')
                max_line_length = max(len(line) for line in cell_lines)
                widths[i] = max(widths[i], max_line_length)
        
        # Create separator line
        separator = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
        
        # Calculate total width for title
        total_width = sum(widths) + len(widths) + 1
        
        # Build table
        result = []
        
        # Add title if provided
        if title:
            # Center the title
            title_str = ProxmoxColors.colorize(title, ProxmoxColors.CYAN, ProxmoxColors.BOLD)
            padding = (total_width - len(title) - 2) // 2  # -2 for the border chars
            title_separator = "+" + "-" * (total_width - 2) + "+"
            result.extend([
                title_separator,
                "|" + " " * padding + title_str + " " * (total_width - padding - len(title) - 2) + "|",
                title_separator
            ])
        
        # Add headers
        header = "|" + "|".join(f" {ProxmoxColors.colorize(h, ProxmoxColors.CYAN):<{w}} " for w, h in zip(widths, headers)) + "|"
        result.extend([separator, header, separator])
        
        # Add rows with multi-line cell support
        for row in rows:
            # Split each cell into lines
            cell_lines = [str(cell).split('\n') for cell in row]
            max_lines = max(len(lines) for lines in cell_lines)
            
            # Pad cells with fewer lines
            padded_cells = []
            for lines in cell_lines:
                if len(lines) < max_lines:
                    lines.extend([''] * (max_lines - len(lines)))
                padded_cells.append(lines)
            
            # Create row strings for each line
            for line_idx in range(max_lines):
                line_parts = []
                for col_idx, cell_lines in enumerate(padded_cells):
                    line = cell_lines[line_idx]
                    line_parts.append(f" {line:<{widths[col_idx]}} ")
                result.append("|" + "|".join(line_parts) + "|")
            
            # Add separator after each row except the last
            if row != rows[-1]:
                result.append(separator)
        
        result.append(separator)
        return "\n".join(result)
    
    @staticmethod
    def create_progress_bar(value: float, total: float, width: int = 20) -> str:
        """Create a progress bar with percentage.
        
        Args:
            value: Current value
            total: Maximum value
            width: Width of progress bar in characters
            
        Returns:
            Formatted progress bar string
        """
        percentage = min(100, (value / total * 100) if total > 0 else 0)
        filled = int(width * percentage / 100)
        color = ProxmoxColors.metric_color(percentage)
        
        bar = "█" * filled + "░" * (width - filled)
        return f"{ProxmoxColors.colorize(bar, color)} {percentage:.1f}%"
    
    @staticmethod
    def create_resource_usage(used: float, total: float, label: str, emoji: str) -> str:
        """Create a resource usage display with progress bar.
        
        Args:
            used: Used amount
            total: Total amount
            label: Resource label
            emoji: Resource emoji
            
        Returns:
            Formatted resource usage string
        """
        from proxmox_mcp.formatting.formatters import ProxmoxFormatters
        percentage = (used / total * 100) if total > 0 else 0
        progress = ProxmoxComponents.create_progress_bar(used, total)
        
        return (
            f"{emoji} {label}:\n"
            f"  {progress}\n"
            f"  {ProxmoxFormatters.format_bytes(used)} / {ProxmoxFormatters.format_bytes(total)}"
        )
    
    @staticmethod
    def create_key_value_grid(data: dict, columns: int = 2) -> str:
        """Create a grid of key-value pairs.
        
        Args:
            data: Dictionary of key-value pairs
            columns: Number of columns in grid
            
        Returns:
            Formatted grid string
        """
        # Calculate max widths for each column
        items = list(data.items())
        rows = [items[i:i + columns] for i in range(0, len(items), columns)]
        
        key_widths = [0] * columns
        val_widths = [0] * columns
        
        for row in rows:
            for i, (key, val) in enumerate(row):
                key_widths[i] = max(key_widths[i], len(str(key)))
                val_widths[i] = max(val_widths[i], len(str(val)))
        
        # Format rows
        result = []
        for row in rows:
            formatted_items = []
            for i, (key, val) in enumerate(row):
                key_str = ProxmoxColors.colorize(f"{key}:", ProxmoxColors.CYAN)
                formatted_items.append(f"{key_str:<{key_widths[i] + 10}} {val:<{val_widths[i]}}")
            result.append("  ".join(formatted_items))
        
        return "\n".join(result)
    
    @staticmethod
    def create_status_badge(status: str) -> str:
        """Create a status badge with emoji.
        
        Args:
            status: Status string
            
        Returns:
            Formatted status badge string
        """
        status = status.lower()
        emoji = ProxmoxTheme.get_status_emoji(status)
        return f"{emoji} {status.upper()}"
