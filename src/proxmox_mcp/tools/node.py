"""
Node-related tools for Proxmox MCP.

This module provides tools for managing and monitoring Proxmox nodes:
- Listing all nodes in the cluster with their status
- Getting detailed node information including:
  * CPU usage and configuration
  * Memory utilization
  * Uptime statistics
  * Health status

The tools handle both basic and detailed node information retrieval,
with fallback mechanisms for partial data availability.
"""
from typing import List
from mcp.types import TextContent as Content
from .base import ProxmoxTool
from .definitions import GET_NODES_DESC, GET_NODE_STATUS_DESC

class NodeTools(ProxmoxTool):
    """Tools for managing Proxmox nodes.
    
    Provides functionality for:
    - Retrieving cluster-wide node information
    - Getting detailed status for specific nodes
    - Monitoring node health and resources
    - Handling node-specific API operations
    
    Implements fallback mechanisms for scenarios where detailed
    node information might be temporarily unavailable.
    """

    def get_nodes(self) -> List[Content]:
        """List all nodes in the Proxmox cluster with detailed status.

        Retrieves comprehensive information for each node including:
        - Basic status (online/offline)
        - Uptime statistics
        - CPU configuration and count
        - Memory usage and capacity
        
        Implements a fallback mechanism that returns basic information
        if detailed status retrieval fails for any node.

        Returns:
            List of Content objects containing formatted node information:
            {
                "node": "node_name",
                "status": "online/offline",
                "uptime": seconds,
                "maxcpu": cpu_count,
                "memory": {
                    "used": bytes,
                    "total": bytes
                }
            }

        Raises:
            RuntimeError: If the cluster-wide node query fails
        """
        try:
            result = self.proxmox.nodes.get()
            nodes = []
            
            # Get detailed info for each node
            for node in result:
                node_name = node["node"]
                try:
                    # Get detailed status for each node
                    status = self.proxmox.nodes(node_name).status.get()
                    nodes.append({
                        "node": node_name,
                        "status": node["status"],
                        "uptime": status.get("uptime", 0),
                        "maxcpu": status.get("cpuinfo", {}).get("cpus", "N/A"),
                        "memory": {
                            "used": status.get("memory", {}).get("used", 0),
                            "total": status.get("memory", {}).get("total", 0)
                        }
                    })
                except Exception as node_error:
                    self.logger.warning(
                        "Using basic info for node %s due to status error: %s",
                        node_name,
                        node_error,
                    )
                    # Fallback to basic info if detailed status fails
                    nodes.append({
                        "node": node_name,
                        "status": node["status"],
                        "uptime": 0,
                        "maxcpu": "N/A",
                        "memory": {
                            # The nodes.get() API already returns memory usage
                            # in the "mem" field, so use that directly. The
                            # previous implementation subtracted this value
                            # from "maxmem" which actually produced the amount
                            # of *free* memory instead of the used memory.
                            "used": node.get("mem", 0),
                            "total": node.get("maxmem", 0)
                        }
                    })
            return self._format_response(nodes, "nodes")
        except Exception as e:
            self._handle_error("get nodes", e)

    def get_node_status(self, node: str) -> List[Content]:
        """Get detailed status information for a specific node.

        Retrieves comprehensive status information including:
        - CPU usage and configuration
        - Memory utilization details
        - Uptime and load statistics
        - Network status
        - Storage health
        - Running tasks and services

        Args:
            node: Name/ID of node to query (e.g., 'pve1', 'proxmox-node2')

        Returns:
            List of Content objects containing detailed node status:
            {
                "uptime": seconds,
                "cpu": {
                    "usage": percentage,
                    "cores": count
                },
                "memory": {
                    "used": bytes,
                    "total": bytes,
                    "free": bytes
                },
                ...additional status fields
            }

        Raises:
            ValueError: If the specified node is not found
            RuntimeError: If status retrieval fails (node offline, network issues)
        """
        try:
            result = self.proxmox.nodes(node).status.get()
            return self._format_response((node, result), "node_status")
        except Exception as e:
            self._handle_error(f"get status for node {node}", e)
