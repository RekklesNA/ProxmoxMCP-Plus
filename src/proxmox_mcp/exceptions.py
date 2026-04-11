"""
Custom exception hierarchy for ProxmoxMCP-Plus.

Provides structured error handling with specific exception types
for different failure scenarios.
"""

from __future__ import annotations

from typing import Any


class ProxmoxMCPError(Exception):
    """Base exception for all ProxmoxMCP errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for logging/API responses."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            **self.details,
        }


class ProxmoxConnectionError(ProxmoxMCPError):
    """Raised when connection to Proxmox API fails."""

    pass


class ProxmoxAuthError(ProxmoxMCPError):
    """Raised when authentication or authorization fails."""

    pass


class ProxmoxNotFoundError(ProxmoxMCPError):
    """Raised when a requested resource is not found."""

    pass


class ProxmoxPermissionError(ProxmoxMCPError):
    """Raised when the user lacks permissions for an operation."""

    pass


class ProxmoxValidationError(ProxmoxMCPError):
    """Raised when input validation fails."""

    pass


class ProxmoxOperationError(ProxmoxMCPError):
    """Raised when a Proxmox operation fails (e.g., VM start/stop)."""

    pass


class ProxmoxTimeoutError(ProxmoxMCPError):
    """Raised when an operation times out."""

    pass


class ProxmoxConfigError(ProxmoxMCPError):
    """Raised when configuration is invalid or missing."""

    pass


class CommandPolicyError(ProxmoxMCPError):
    """Raised when a command violates security policy."""

    pass


class ConsoleError(ProxmoxMCPError):
    """Raised when console/SSH operations fail."""

    pass


class BackupError(ProxmoxMCPError):
    """Raised when backup operations fail."""

    pass


class SnapshotError(ProxmoxMCPError):
    """Raised when snapshot operations fail."""

    pass


class StorageError(ProxmoxMCPError):
    """Raised when storage operations fail."""

    pass


class NetworkError(ProxmoxMCPError):
    """Raised when network configuration operations fail."""

    pass
