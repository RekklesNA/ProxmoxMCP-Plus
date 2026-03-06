"""
Storage-related tools for Proxmox MCP.

This module provides tools for managing and monitoring Proxmox storage:
- Listing all storage pools across the cluster
- Retrieving detailed storage information including:
  * Storage type and content types
  * Usage statistics and capacity
  * Availability status
  * Node assignments

The tools implement fallback mechanisms for scenarios where
detailed storage information might be temporarily unavailable.
"""
from typing import List
from mcp.types import TextContent as Content
from proxmox_mcp.tools.base import ProxmoxTool
from proxmox_mcp.tools.definitions import GET_STORAGE_DESC

class StorageTools(ProxmoxTool):
    """Tools for managing Proxmox storage.
    
    Provides functionality for:
    - Retrieving cluster-wide storage information
    - Monitoring storage pool status and health
    - Tracking storage utilization and capacity
    - Managing storage content types
    
    Implements fallback mechanisms for scenarios where detailed
    storage information might be temporarily unavailable.
    """

    def get_storage(self) -> List[Content]:
        """List storage pools across the cluster with detailed status.

        Retrieves comprehensive information for each storage pool including:
        - Basic identification (name, type)
        - Content types supported (VM disks, backups, ISO images, etc.)
        - Availability status (online/offline)
        - Usage statistics:
          * Used space
          * Total capacity
          * Available space
        
        Implements a fallback mechanism that returns basic information
        if detailed status retrieval fails for any storage pool.

        Returns:
            List of Content objects containing formatted storage information:
            {
                "storage": "storage-name",
                "type": "storage-type",
                "content": ["content-types"],
                "status": "online/offline",
                "used": bytes,
                "total": bytes,
                "available": bytes
            }

        Raises:
            RuntimeError: If the cluster-wide storage query fails
        """
        try:
            result = self.proxmox.storage.get()
            storage = []
            
            for store in result:
                # Get detailed storage info including usage
                try:
                    status = self.proxmox.nodes(store.get("node", "localhost")).storage(store["storage"]).status.get()
                    storage.append({
                        "storage": store["storage"],
                        "type": store["type"],
                        "content": store.get("content", []),
                        "status": "online" if store.get("enabled", True) else "offline",
                        "used": status.get("used", 0),
                        "total": status.get("total", 0),
                        "available": status.get("avail", 0)
                    })
                except Exception as store_error:
                    self.logger.warning(
                        "Using basic info for storage %s due to status error: %s",
                        store.get("storage"),
                        store_error,
                    )
                    # If detailed status fails, add basic info
                    storage.append({
                        "storage": store["storage"],
                        "type": store["type"],
                        "content": store.get("content", []),
                        "status": "online" if store.get("enabled", True) else "offline",
                        "used": 0,
                        "total": 0,
                        "available": 0
                    })
                    
            return self._format_response(storage, "storage")
        except Exception as e:
            self._handle_error("get storage", e)
