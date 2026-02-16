"""
Logging configuration for the Proxmox MCP server.

This module handles logging setup and configuration:
- File and console logging handlers
- Log level management
- Format customization
- Handler lifecycle management

The logging system supports:
- Configurable log levels
- File-based logging with path resolution
- Console logging for errors
- Custom format strings
- Multiple handler management
"""
import logging
import os
from typing import Optional
from proxmox_mcp.config.models import LoggingConfig

def setup_logging(config: LoggingConfig) -> logging.Logger:
    """Configure and initialize logging system.

    Sets up a comprehensive logging system with:
    - File logging (if configured):
      * Handles relative/absolute paths
      * Uses configured log level
      * Applies custom format
    
    - Console logging:
      * Always enabled for errors
      * Ensures critical issues are visible
    
    - Handler Management:
      * Removes existing handlers
      * Configures new handlers
      * Sets up formatters
    
    Args:
        config: Logging configuration containing:
               - Log level (e.g., "INFO", "DEBUG")
               - Format string
               - Optional log file path

    Returns:
        Configured logger instance for "proxmox-mcp"
        with appropriate handlers and formatting

    Example config:
        {
            "level": "INFO",
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            "file": "/path/to/log/file.log"  # Optional
        }
    """
    # Convert relative path to absolute
    log_file = config.file
    if log_file and not os.path.isabs(log_file):
        log_file = os.path.join(os.getcwd(), log_file)
        
    # Create handlers
    handlers = []
    
    if log_file:
        try:
            # Ensure directory exists
            log_dir = os.path.dirname(log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)
                
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(getattr(logging, config.level.upper()))
            handlers.append(file_handler)
        except Exception:
            # Fallback for restricted environments
            pass
    
    # Console handler for errors only
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.ERROR)
    handlers.append(console_handler)
    
    # Configure formatters
    formatter = logging.Formatter(config.format)
    for handler in handlers:
        handler.setFormatter(formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, config.level.upper()))
    
    # Add new handlers
    for handler in handlers:
        root_logger.addHandler(handler)
    
    # Create and return server logger
    logger = logging.getLogger("proxmox-mcp")
    return logger
