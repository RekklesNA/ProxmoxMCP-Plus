from __future__ import annotations

import logging

from proxmox_mcp.config.models import LoggingConfig
from proxmox_mcp.core.logging import setup_logging


def _managed_handlers() -> list[logging.Handler]:
    return [
        handler
        for handler in logging.getLogger().handlers
        if getattr(handler, "_proxmox_mcp_handler", False)
    ]


def test_setup_logging_replaces_existing_managed_handlers() -> None:
    root_logger = logging.getLogger()
    external_handler = logging.NullHandler()
    root_logger.addHandler(external_handler)
    try:
        setup_logging(LoggingConfig(level="INFO"))
        first_handlers = _managed_handlers()
        setup_logging(LoggingConfig(level="DEBUG"))
        second_handlers = _managed_handlers()

        assert len(first_handlers) == 1
        assert len(second_handlers) == 1
        assert first_handlers[0] not in second_handlers
        assert external_handler in root_logger.handlers
    finally:
        for handler in _managed_handlers():
            root_logger.removeHandler(handler)
            handler.close()
        root_logger.removeHandler(external_handler)
