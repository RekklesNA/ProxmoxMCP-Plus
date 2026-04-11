"""
Logging configuration for the Proxmox MCP server.

This module handles logging setup and configuration:
- File and console logging handlers
- Log level management
- Format customization
- Handler lifecycle management
- Optional structured logging via structlog

The logging system supports:
- Configurable log levels
- File-based logging with path resolution
- Console logging for errors
- Custom format strings
- Multiple handler management
- Optional JSON structured logging (when structlog is available)
"""

from __future__ import annotations

import logging
import os
from typing import Any

try:
    import structlog

    STRUCTLOG_AVAILABLE = True
except ImportError:
    STRUCTLOG_AVAILABLE = False

from proxmox_mcp.config.models import LoggingConfig

def setup_logging(config: LoggingConfig, use_structured: bool = False) -> logging.Logger:
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

    - Structured Logging (optional):
      * JSON format via structlog
      * Key-value pair logging
      * Better log parsing and analysis

    Args:
        config: Logging configuration containing:
               - Log level (e.g., "INFO", "DEBUG")
               - Format string
               - Optional log file path
        use_structured: Enable structured logging via structlog
                       (requires structlog package)

    Returns:
        Configured logger instance for "proxmox-mcp"
        with appropriate handlers and formatting

    Example config:
        {
            "level": "INFO",
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            "file": "/path/to/log/file.log"  # Optional
        }

    Example structured logging:
        logger.info("tool_executed", tool_name="start_vm", vm_id=100, duration_ms=245)
    """
    # Convert relative path to absolute
    log_file = config.file
    if log_file and not os.path.isabs(log_file):
        log_file = os.path.join(os.getcwd(), log_file)

    # Create handlers
    handlers: list[logging.Handler] = []

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

    # Clear existing handlers
    root_logger.handlers.clear()

    # Add new handlers
    for handler in handlers:
        root_logger.addHandler(handler)

    # Setup structured logging if enabled and available
    if use_structured and STRUCTLOG_AVAILABLE:
        _setup_structured_logging(config.level)

    # Create and return server logger
    logger = logging.getLogger("proxmox-mcp")
    return logger


def _setup_structured_logging(log_level: str) -> None:
    """Configure structlog for structured JSON logging.

    Sets up structlog with:
    - JSON output format
    - Timestamp addition
    - Log level integration
    - Caller information (module, function)
    - Thread context support
    """
    if not STRUCTLOG_AVAILABLE:
        return

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer() if os.getenv("JSON_LOGS") else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_structured_logger(name: str = "proxmox-mcp") -> Any:
    """Get a structured logger instance.

    Returns a structlog logger if available, otherwise falls back
    to standard logging.

    Args:
        name: Logger name (default: "proxmox-mcp")

    Returns:
        Configured logger instance

    Example usage:
        logger = get_structured_logger()
        logger.info("tool_executed", tool_name="start_vm", vm_id=100, duration_ms=245)
    """
    if STRUCTLOG_AVAILABLE:
        return structlog.get_logger(name)
    return logging.getLogger(name)
