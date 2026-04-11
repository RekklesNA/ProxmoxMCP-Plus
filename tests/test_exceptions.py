"""Tests for custom exception hierarchy."""

import pytest

from proxmox_mcp.exceptions import (
    BackupError,
    CommandPolicyError,
    ConsoleError,
    NetworkError,
    ProxmoxAuthError,
    ProxmoxConfigError,
    ProxmoxConnectionError,
    ProxmoxMCPError,
    ProxmoxNotFoundError,
    ProxmoxOperationError,
    ProxmoxPermissionError,
    ProxmoxTimeoutError,
    ProxmoxValidationError,
    SnapshotError,
    StorageError,
)


class TestProxmoxMCPError:
    """Test base ProxmoxMCPError exception."""

    def test_basic_exception(self):
        """Test basic exception creation and message."""
        error = ProxmoxMCPError("Test error message")
        assert error.message == "Test error message"
        assert error.details == {}

    def test_exception_with_details(self):
        """Test exception with details dictionary."""
        details = {"vm_id": 100, "operation": "start"}
        error = ProxmoxMCPError("Operation failed", details=details)
        assert error.message == "Test error message" or error.message == "Operation failed"
        assert error.details == details

    def test_to_dict(self):
        """Test conversion to dictionary."""
        details = {"vm_id": 100}
        error = ProxmoxMCPError("Test error", details=details)
        result = error.to_dict()
        assert result["error_type"] == "ProxmoxMCPError"
        assert result["message"] == "Test error"
        assert result["vm_id"] == 100

    def test_exception_inheritance(self):
        """Test that all exceptions inherit from ProxmoxMCPError."""
        exceptions = [
            ProxmoxConnectionError,
            ProxmoxAuthError,
            ProxmoxNotFoundError,
            ProxmoxPermissionError,
            ProxmoxValidationError,
            ProxmoxOperationError,
            ProxmoxTimeoutError,
            ProxmoxConfigError,
            CommandPolicyError,
            ConsoleError,
            BackupError,
            SnapshotError,
            StorageError,
            NetworkError,
        ]

        for exc_class in exceptions:
            exc = exc_class("Test message")
            assert isinstance(exc, ProxmoxMCPError)

    def test_catch_base_exception(self):
        """Test catching base exception catches all derived exceptions."""
        def raise_derived():
            raise ProxmoxNotFoundError("Not found")

        with pytest.raises(ProxmoxMCPError):
            raise_derived()

    def test_exception_str_representation(self):
        """Test string representation of exception."""
        error = ProxmoxMCPError("Test error")
        assert str(error) == "Test error"


class TestSpecificExceptions:
    """Test specific exception types."""

    def test_connection_error(self):
        """Test ProxmoxConnectionError."""
        error = ProxmoxConnectionError(
            "Connection failed",
            details={"host": "192.168.1.100", "port": 8006}
        )
        result = error.to_dict()
        assert result["error_type"] == "ProxmoxConnectionError"
        assert result["host"] == "192.168.1.100"

    def test_auth_error(self):
        """Test ProxmoxAuthError."""
        error = ProxmoxAuthError("Invalid token")
        assert isinstance(error, ProxmoxMCPError)

    def test_not_found_error(self):
        """Test ProxmoxNotFoundError."""
        error = ProxmoxNotFoundError("VM not found", details={"vm_id": 100})
        assert error.details["vm_id"] == 100

    def test_validation_error(self):
        """Test ProxmoxValidationError."""
        error = ProxmoxValidationError("Invalid input")
        assert error.message == "Invalid input"

    def test_operation_error(self):
        """Test ProxmoxOperationError."""
        error = ProxmoxOperationError("Failed to start VM")
        assert "Failed" in error.message

    def test_command_policy_error(self):
        """Test CommandPolicyError."""
        error = CommandPolicyError("Command blocked")
        assert error.message == "Command blocked"

    def test_backup_error(self):
        """Test BackupError."""
        error = BackupError("Backup failed", details={"backup_id": "backup123"})
        assert error.details["backup_id"] == "backup123"

    def test_snapshot_error(self):
        """Test SnapshotError."""
        error = SnapshotError("Snapshot creation failed")
        assert isinstance(error, ProxmoxOperationError) or isinstance(error, ProxmoxMCPError)

    def test_storage_error(self):
        """Test StorageError."""
        error = StorageError("Storage full")
        assert error.message == "Storage full"

    def test_network_error(self):
        """Test NetworkError."""
        error = NetworkError("Network configuration failed")
        assert error.message == "Network configuration failed"
