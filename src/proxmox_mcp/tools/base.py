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
        self.metrics = metrics
        self.job_store = job_store

    def _cache_get(self, key: str) -> Any:
        entry = self._cache.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if time.time() >= expires_at:
            self._cache.pop(key, None)
            return None
        return value

    def _cache_set(self, key: str, value: Any, ttl_seconds: int = 5) -> None:
        self._cache[key] = (time.time() + ttl_seconds, value)

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
        error_msg = str(error)
        self.logger.error(f"Failed to {operation}: {error_msg}")

        if "not found" in error_msg.lower():
            raise ValueError(f"Resource not found: {error_msg}")
        if "permission denied" in error_msg.lower():
            raise ValueError(f"Permission denied: {error_msg}")
        if "invalid" in error_msg.lower():
            raise ValueError(f"Invalid input: {error_msg}")
        
        raise RuntimeError(f"Failed to {operation}: {error_msg}")

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
