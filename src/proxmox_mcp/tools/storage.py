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


def _as_list(maybe):
    """Return list; unwrap {'data': list}; else []."""
    if isinstance(maybe, list):
        return maybe
    if isinstance(maybe, dict):
        data = maybe.get("data")
        if isinstance(data, list):
            return data
    return []


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

    def _node_names(self) -> List[str]:
        nodes = _as_list(self._call_with_retry("get nodes", lambda: self.proxmox.nodes.get()))
        online = [
            str(node["node"])
            for node in nodes
            if isinstance(node, dict) and node.get("node") and node.get("status") != "offline"
        ]
        if online:
            return online
        return [str(node["node"]) for node in nodes if isinstance(node, dict) and node.get("node")]

    def _candidate_nodes_for_storage(self, store: dict, node_names: List[str]) -> List[str]:
        raw_nodes = store.get("nodes")
        if isinstance(raw_nodes, str) and raw_nodes.strip():
            restricted = [item.strip() for item in raw_nodes.split(",") if item.strip()]
        elif isinstance(raw_nodes, list):
            restricted = [str(item) for item in raw_nodes if str(item).strip()]
        else:
            restricted = []

        if restricted:
            preferred = [node for node in node_names if node in set(restricted)]
            return preferred or restricted
        return list(node_names)

    def _storage_status(self, store: dict, node_names: List[str]) -> dict | None:
        storage_name = store.get("storage")
        if not storage_name:
            return None

        last_error = None
        for node_name in self._candidate_nodes_for_storage(store, node_names):
            try:
                return self.proxmox.nodes(node_name).storage(storage_name).status.get()
            except Exception as error:
                last_error = error
                self.logger.debug(
                    "Storage status lookup failed for %s on node %s: %s",
                    storage_name,
                    node_name,
                    error,
                )

        if last_error is not None:
            self.logger.warning(
                "Using basic info for storage %s due to status error: %s",
                storage_name,
                last_error,
            )
        return None

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
        cached = self._cache_get("storage:list")
        if cached is not None:
            return self._format_response(cached, "storage")

        try:
            result = self._call_with_retry("get storage", lambda: self.proxmox.storage.get())
            node_names = self._node_names()
            storage = []
            
            for store in result:
                status = self._storage_status(store, node_names)
                if status is not None:
                    storage.append({
                        "storage": store["storage"],
                        "type": store["type"],
                        "content": store.get("content", []),
                        "status": "online" if store.get("enabled", True) else "offline",
                        "used": status.get("used", 0),
                        "total": status.get("total", 0),
                        "available": status.get("avail", 0)
                    })
                else:
                    storage.append({
                        "storage": store["storage"],
                        "type": store["type"],
                        "content": store.get("content", []),
                        "status": "online" if store.get("enabled", True) else "offline",
                        "used": 0,
                        "total": 0,
                        "available": 0
                    })
                    
            self._cache_set("storage:list", storage, ttl_seconds=10)
            return self._format_response(storage, "storage")
        except Exception as e:
            self._handle_error("get storage", e)
