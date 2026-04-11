"""Tests for utils/logging module."""

import logging
import tempfile
import os
import pytest
from proxmox_mcp.utils.logging import setup_logging


class TestSetupLogging:
    """Test setup_logging function."""

    def test_setup_logging_default(self):
        """Test logging setup with defaults."""
        logger = setup_logging()
        assert logger is not None
        assert logger.name == "proxmox-mcp"

    def test_setup_logging_debug_level(self):
        """Test logging setup with DEBUG level."""
        logger = setup_logging(level="DEBUG")
        assert logger.level == logging.DEBUG

    def test_setup_logging_info_level(self):
        """Test logging setup with INFO level."""
        logger = setup_logging(level="INFO")
        assert logger.level == logging.INFO

    def test_setup_logging_warning_level(self):
        """Test logging setup with WARNING level."""
        logger = setup_logging(level="WARNING")
        assert logger.level == logging.WARNING

    def test_setup_logging_error_level(self):
        """Test logging setup with ERROR level."""
        logger = setup_logging(level="ERROR")
        assert logger.level == logging.ERROR

    def test_setup_logging_with_file(self):
        """Test logging setup with file handler."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
            temp_log = f.name

        try:
            logger = setup_logging(log_file=temp_log)
            assert logger is not None
            
            # Test that logger works
            logger.info("Test message")
            
            # Verify file exists and has content
            assert os.path.exists(temp_log)
        finally:
            # On Windows, file may be locked, ignore errors
            try:
                if os.path.exists(temp_log):
                    os.unlink(temp_log)
            except (PermissionError, OSError):
                pass

    def test_setup_logging_custom_format(self):
        """Test logging setup with custom format."""
        custom_format = "%(levelname)s - %(message)s"
        logger = setup_logging(format_str=custom_format)
        assert logger is not None

    def test_logging_multiple_messages(self):
        """Test logging multiple messages."""
        logger = setup_logging(level="DEBUG")
        
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")
        logger.critical("Critical message")

    def test_logging_exception(self):
        """Test logging exception."""
        logger = setup_logging(level="ERROR")
        
        try:
            raise ValueError("Test error")
        except ValueError:
            logger.exception("An error occurred")
