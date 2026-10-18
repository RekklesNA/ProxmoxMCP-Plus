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
from typing import Any, List
from mcp.types import TextContent as Content
from proxmox_mcp.tools.base import ProxmoxTool

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
                "clustered": true/false/null,
                "quorum": true/false/null,
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
        cached = self._cache_get("cluster:status")
        if cached is not None:
            return self._format_response(cached, "cluster")

        try:
            result = self._call_with_retry(
                "get cluster status", lambda: self.proxmox.cluster.status.get()
            )
        
            records = result or []
            cluster_record = next(
                (item for item in records if item.get("type") == "cluster"), None
            )
            nodes = [item for item in records if item.get("type") == "node"]
            # A node-only response denotes standalone PVE. No records provide
            # no evidence of cluster membership, so leave that state unknown.
            clustered = True if cluster_record is not None else (False if nodes else None)
            quorate = cluster_record.get("quorate") if cluster_record is not None else None
            status = {
                "name": cluster_record.get("name") if cluster_record is not None else None,
                "clustered": clustered,
                "quorum": bool(quorate) if quorate is not None else None,
                "nodes": len(nodes),
                "resources": [res for res in records if res.get("type") == "resource"]
            }
            self._cache_set("cluster:status", status, ttl_seconds=5)
            return self._format_response(status, "cluster")
        except Exception as e:
            self._handle_error("get cluster status", e)

    def get_cluster_join_info(self) -> List[Content]:
        """Return documented join metadata; unknown fields never enter agent context."""
        try:
            info = self._call_with_retry(
                "get cluster join info", lambda: self.proxmox.cluster.config.join.get()
            )
            if not isinstance(info, dict):
                raise RuntimeError("Unexpected cluster join information response")
            public: dict[str, Any] = {}
            for key in ("preferred_node", "config_digest", "fingerprint"):
                if isinstance(info.get(key), str):
                    public[key] = info[key]
            if "nodelist" in info:
                if not isinstance(info["nodelist"], list):
                    raise RuntimeError("Unexpected cluster join node list")
                fields = {"name", "nodeid", "quorum_votes", "pve_addr", "pve_fp"}
                fields.update(f"ring{index}_addr" for index in range(8))
                public["nodelist"] = [
                    {key: value for key, value in node.items()
                     if key in fields and type(value) in (str, int)}
                    for node in info["nodelist"] if isinstance(node, dict)
                ]
            # Corosync's public transport settings are useful for joining. Do not
            # pass arbitrary totem extensions or credential-shaped nested objects.
            if isinstance(info.get("totem"), dict):
                fields = {"cluster_name", "config_version", "ip_version", "secauth", "version",
                          "transport", "link_mode"}
                public["totem"] = {key: value for key, value in info["totem"].items()
                                   if key in fields and type(value) in (str, int)}
            return self._format_response(public)
        except Exception as error:
            self._handle_error("get cluster join info", error)
