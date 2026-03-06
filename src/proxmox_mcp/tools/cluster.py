"""
Cluster-related tools for Proxmox MCP.

This module provides tools for monitoring and managing Proxmox clusters:
- Retrieving overall cluster health status
- Monitoring quorum status and node count
- Tracking cluster resources and configuration
- Checking cluster-wide service availability

The tools provide essential information for maintaining
cluster health and ensuring proper operation.
"""
from typing import List
from mcp.types import TextContent as Content
from proxmox_mcp.tools.base import ProxmoxTool
from proxmox_mcp.tools.definitions import GET_CLUSTER_STATUS_DESC

class ClusterTools(ProxmoxTool):
    """Tools for managing Proxmox cluster.
    
    Provides functionality for:
    - Monitoring cluster health and status
    - Tracking quorum and node membership
    - Managing cluster-wide resources
    - Verifying cluster configuration
    
    Essential for maintaining cluster health and ensuring
    proper operation of the Proxmox environment.
    """

    def get_cluster_status(self) -> List[Content]:
        """Get overall Proxmox cluster health and configuration status.

        Retrieves comprehensive cluster information including:
        - Cluster name and identity
        - Quorum status (essential for cluster operations)
        - Active node count and health
        - Resource distribution and status
        
        This information is critical for:
        - Ensuring cluster stability
        - Monitoring node membership
        - Verifying resource availability
        - Detecting potential issues

        Returns:
            List of Content objects containing formatted cluster status:
            {
                "name": "cluster-name",
                "quorum": true/false,
                "nodes": count,
                "resources": [
                    {
                        "type": "resource-type",
                        "status": "status"
                    }
                ]
            }

        Raises:
            RuntimeError: If cluster status query fails due to:
                        - Network connectivity issues
                        - Authentication problems
                        - API endpoint failures
        """
        try:
            result = self.proxmox.cluster.status.get()
        
            first_item = result[0] if result and len(result) > 0 else {}
            status = {
                "name": first_item.get("name") if first_item else None,
                "quorum": first_item.get("quorate") if first_item else None,
                "nodes": len([node for node in result if node.get("type") == "node"]) if result else 0,
                "resources": [res for res in result if res.get("type") == "resource"] if result else []
            }
            return self._format_response(status, "cluster")
        except Exception as e:
            self._handle_error("get cluster status", e)
