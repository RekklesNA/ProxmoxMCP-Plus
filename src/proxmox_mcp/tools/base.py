"""
Base classes and utilities for Proxmox MCP tools.

This module provides the foundation for all Proxmox MCP tools, including:
- Base tool class with common functionality
- Response formatting utilities
- Error handling mechanisms
- Logging setup

All tool implementations inherit from the ProxmoxTool base class to ensure
consistent behavior and error handling across the MCP server.
"""
import logging
import time
from typing import Any, Callable, Dict, List, NoReturn, Optional
from mcp.types import TextContent as Content
from proxmoxer import ProxmoxAPI
from proxmox_mcp.formatting import ProxmoxTemplates
from proxmox_mcp.observability import ToolMetrics
from proxmox_mcp.security.sanitization import sanitize_string
import json
from threading import RLock


class InventoryList(list):
    """Carry completeness metadata without breaking legacy list consumers."""

    def __init__(self) -> None:
        super().__init__()
        self.warnings: list[str] = []


def completeness_content(warnings: list[str]) -> list[Content]:
    if not warnings:
        return []
    return [Content(type="text", text=json.dumps({"success": False, "code": "INCOMPLETE_INVENTORY", "warnings": warnings}))]

def _log_safe(value: object, max_length: int = 200) -> str:
    return sanitize_string(value, max_length=max_length)


class ProxmoxTool:
    """Base class for Proxmox MCP tools.
    
    This class provides common functionality used by all Proxmox tool implementations:
    - Proxmox API access
    - Standardized logging
    - Response formatting
    - Error handling
    
    All tool classes should inherit from this base class to ensure consistent
    behavior and error handling across the MCP server.
    """

    def __init__(
        self,
        proxmox_api: ProxmoxAPI,
        metrics: Optional[ToolMetrics] = None,
        job_store: Optional[Any] = None,
    ):
        """Initialize the tool.

        Args:
            proxmox_api: Initialized ProxmoxAPI instance
        """
        self.proxmox = proxmox_api
        self.logger = logging.getLogger(f"proxmox-mcp.{self.__class__.__name__.lower()}")
        self._cache: Dict[str, tuple[float, Any]] = {}
        self._cache_locks = [RLock() for _ in range(32)]
        self.metrics = metrics
        self.job_store = job_store

    def _cache_get(self, key: str) -> Any:
        entry = self._cache.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            self._cache.pop(key, None)
            return None
        return value

    def _cache_set(self, key: str, value: Any, ttl_seconds: int = 5) -> None:
        if len(self._cache) >= 500:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = (time.monotonic() + ttl_seconds, value)

    def _cached_read(self, key: str, read: Callable[[], Any], ttl_seconds: int = 5) -> Any:
        """Coalesce concurrent read requests using a bounded stripe lock table."""
        with self._cache_locks[hash(key) % len(self._cache_locks)]:
            cached = self._cache_get(key)
            if cached is not None:
                return cached
            value = read()
            self._cache_set(key, value, ttl_seconds)
            return value

    def _wait_for_task(self, node: str, upid: str, timeout_seconds: float = 30) -> None:
        """Wait for a prerequisite task without hiding failed or unknown outcomes."""
        deadline = time.monotonic() + timeout_seconds
        while True:
            status = self.proxmox.nodes(node).tasks(upid).status.get()
            if not isinstance(status, dict):
                raise RuntimeError("Prerequisite task returned an invalid status")
            if status.get("status") == "stopped":
                if status.get("exitstatus") != "OK":
                    raise RuntimeError("Prerequisite task failed: " + _log_safe(status.get("exitstatus")))
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("Prerequisite task is still running; no dependent operation was submitted")
            time.sleep(0.1)

    def _call_with_retry(
        self,
        operation: str,
        fn: Callable[[], Any],
        retries: int = 2,
        backoff_seconds: float = 0.2,
    ) -> Any:
        attempt = 0
        while True:
            try:
                return fn()
            except Exception as error:
                attempt += 1
                if attempt > retries:
                    self._handle_error(operation, error)
                time.sleep(backoff_seconds * attempt)

    def _format_response(self, data: Any, resource_type: Optional[str] = None) -> List[Content]:
        """Format response data into MCP content using templates.

        This method handles formatting of various Proxmox resource types into
        consistent MCP content responses. It uses specialized templates for
        different resource types (nodes, VMs, storage, etc.) and falls back
        to JSON formatting for unknown types.

        Args:
            data: Raw data from Proxmox API to format
            resource_type: Type of resource for template selection. Valid types:
                         'nodes', 'node_status', 'vms', 'storage', 'containers', 'cluster'

        Returns:
            List of Content objects formatted according to resource type
        """
        if resource_type == "nodes":
            formatted = ProxmoxTemplates.node_list(data)
        elif resource_type == "node_status":
            # For node_status, data should be a tuple of (node_name, status_dict)
            if isinstance(data, tuple) and len(data) == 2:
                formatted = ProxmoxTemplates.node_status(data[0], data[1])
            else:
                formatted = ProxmoxTemplates.node_status("unknown", data)
        elif resource_type == "vms":
            formatted = ProxmoxTemplates.vm_list(data)
        elif resource_type == "storage":
            formatted = ProxmoxTemplates.storage_list(data)
        elif resource_type == "containers":
            formatted = ProxmoxTemplates.container_list(data)
        elif resource_type == "cluster":
            formatted = ProxmoxTemplates.cluster_status(data)
        else:
            # Fallback to JSON formatting for unknown types
            import json
            formatted = json.dumps(data, indent=2)

        return [Content(type="text", text=formatted)]

    def _handle_error(self, operation: str, error: Exception) -> NoReturn:
        """Handle and log errors from Proxmox operations.

        Provides standardized error handling across all tools by:
        - Logging errors with appropriate context
        - Categorizing errors into specific exception types
        - Converting Proxmox-specific errors into standard Python exceptions

        Args:
            operation: Description of the operation that failed (e.g., "get node status")
            error: The exception that occurred during the operation

        Raises:
            ValueError: For invalid input, missing resources, or permission issues
            RuntimeError: For unexpected errors or API failures
        """
        raw_error_msg = str(error)
        error_msg = _log_safe(raw_error_msg)
        self.logger.error("Failed to %s: %s", _log_safe(operation), _log_safe(error_msg))

        if isinstance(error, ValueError):
            raise ValueError(error_msg) from error

        if "not found" in raw_error_msg.lower():
            raise ValueError(f"Resource not found: {error_msg}")
        if "permission denied" in raw_error_msg.lower():
            raise ValueError(f"Permission denied: {error_msg}")
        if "invalid" in raw_error_msg.lower():
            raise ValueError(f"Invalid input: {error_msg}")
        
        raise RuntimeError(f"Failed to {operation}: {error_msg}")

    def _submission_content(self, job: Optional[Dict[str, Any]], upid: Optional[Any]) -> List[Content]:
        """Report submission separately from eventual task completion."""
        if upid is None:
            return []
        import json

        return [Content(type="text", text=json.dumps({
            "success": True,
            "status": "submitted",
            "task_id": str(upid),
            "job_id": job["job_id"] if job else None,
        }))]

    def _register_background_job(
        self,
        *,
        tool_name: str,
        summary: str,
        node: Optional[str],
        upid: Optional[Any],
        metadata: Optional[Dict[str, Any]] = None,
        retry_spec: Optional[Dict[str, Any]] = None,
        retry_factory: Optional[Callable[[], Any]] = None,
        cancel_factory: Optional[Callable[[str], Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        if self.job_store is None:
            return None
        if upid is None:
            return None
        return self.job_store.register_task(
            tool_name=tool_name,
            summary=summary,
            node=node,
            upid=str(upid),
            metadata=metadata,
            retry_spec=retry_spec,
            retry_factory=retry_factory,
            cancel_factory=cancel_factory,
        )
