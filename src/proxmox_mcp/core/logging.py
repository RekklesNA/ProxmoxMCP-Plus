"""
Logging configuration for the Proxmox MCP server.
"""
import logging
import os
from typing import Optional
from ..config.models import LoggingConfig

def setup_logging(config: LoggingConfig) -> logging.Logger:
    """Configure logging based on settings.

    Args:
        config: Logging configuration

    Returns:
        Configured logger instance
    """
    # Convert relative path to absolute
    log_file = config.file
    if log_file and not os.path.isabs(log_file):
        log_file = os.path.join(os.getcwd(), log_file)
        
    # Create handlers
    handlers = []
    
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(getattr(logging, config.level.upper()))
        handlers.append(file_handler)
    
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
    
    # Remove any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Add new handlers
    for handler in handlers:
        root_logger.addHandler(handler)
    
    # Create and return server logger
    logger = logging.getLogger("proxmox-mcp")
    return logger
