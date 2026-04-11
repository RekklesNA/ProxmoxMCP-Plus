"""
Logging configuration for the Proxmox MCP server.
"""

import logging
import sys
from typing import Optional

def setup_logging(
    level: str = "INFO",
    format_str: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    log_file: Optional[str] = None,
) -> logging.Logger:
    """
    Configure logging for the Proxmox MCP server.

    Args:
        level: The logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format_str: The format string for log messages
        log_file: Optional file path to write logs to

    Returns:
        logging.Logger: Configured logger instance
    """
    # Create logger
    logger = logging.getLogger("proxmox-mcp")
    logger.setLevel(getattr(logging, level.upper()))

    # Create handlers
    handlers: list[logging.Handler] = []

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(getattr(logging, level.upper()))
    handlers.append(console_handler)

    # File handler if log_file is specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(getattr(logging, level.upper()))
        handlers.append(file_handler)

    # Create formatter
    formatter = logging.Formatter(format_str)

    # Add formatter to handlers and handlers to logger
    for handler in handlers:
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
