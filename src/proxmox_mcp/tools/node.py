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
import math
from mcp.types import TextContent as Content
from proxmox_mcp.tools.base import ProxmoxTool
from proxmox_mcp.security.resources import validate_segment

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

    def list_bridges(self, node: str) -> List[Content]:
        """Read bridge records visible to this token, including OVS and SDN."""
        try:
            return self._format_response(self.proxmox.nodes(node).network.get(type="any_bridge"))
        except Exception as error:
            self._handle_error(f"list bridges for node {node}", error)

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
        cached = self._cache_get("nodes:list")
        if cached is not None:
            return self._format_response(cached, "nodes")

        try:
            result = self._call_with_retry("get nodes", lambda: self.proxmox.nodes.get())
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
            self._cache_set("nodes:list", nodes, ttl_seconds=5)
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
            # The Proxmox /nodes/{node}/status endpoint does NOT include a
            # `status` field in its response (that field only exists in the
            # /nodes list endpoint). A successful response here is itself
            # proof the node is reachable, so we inject "online" to keep the
            # formatter from always rendering "UNKNOWN".
            if "status" not in result:
                result["status"] = "online"

            # Zero is a valid CPU sample. Only enrich a missing reading;
            # cluster resources may use a different sampling interval.
            if result.get("cpu") is None:
                try:
                    for entry in self.proxmox.cluster.resources.get(type="node"):
                        if entry.get("node") == node and isinstance(entry.get("cpu"), (int, float)):
                            result["cpu"] = entry["cpu"]
                            break
                except Exception:
                    self.logger.debug("Could not read optional cluster CPU sample")

            return self._format_response((node, result), "node_status")
        except Exception as e:
            try:
                nodes = self.proxmox.nodes.get()
            except Exception:
                self._handle_error(f"get status for node {node}", e)

            for entry in nodes:
                if entry.get("node") != node:
                    continue
                if entry.get("status") == "offline":
                    self.logger.warning(
                        "Using offline status for node %s due to status error: %s",
                        node,
                        e,
                    )
                    fallback = {
                        "status": "offline",
                        "uptime": 0,
                        "maxcpu": "N/A",
                        "memory": {
                            "used": entry.get("mem", 0),
                            "total": entry.get("maxmem", 0),
                        },
                    }
                    return self._format_response((node, fallback), "node_status")
                break

            self._handle_error(f"get status for node {node}", e)

    def get_node_time(self, node: str) -> List[Content]:
        """Read the node clock using Proxmox's read-only /nodes/{node}/time endpoint."""
        if not isinstance(node, str) or not node.strip():
            raise ValueError("node must be a non-empty name")
        validate_segment(node)
        try:
            data = self._call_with_retry(
                f"get time on node {node}",
                lambda: self.proxmox.nodes(node).time.get(),
            )
            if not isinstance(data, dict) or not isinstance(data.get("time"), int):
                raise RuntimeError("Node time response did not contain an epoch timestamp")
            return self._format_response({
                "node": node,
                "time": data["time"],
                "localtime": data.get("localtime"),
                "timezone": data.get("timezone"),
            })
        except Exception as error:
            self._handle_error(f"get time on node {node}", error)

    def get_node_diagnostics(self, node: str) -> List[Content]:
        """Read bounded node diagnostics, preserving partial results on optional API errors."""
        if not isinstance(node, str) or not node.strip():
            raise ValueError("node must be a non-empty name")
        validate_segment(node)
        try:
            status = self._call_with_retry(
                f"get diagnostics for node {node}", lambda: self.proxmox.nodes(node).status.get()
            )
            if not isinstance(status, dict):
                raise RuntimeError("Node status endpoint returned an invalid response")
            warnings = []
            storage = None
            recent_io = None
            try:
                storage = self.proxmox.nodes(node).storage.get()
                if not isinstance(storage, list):
                    raise ValueError("Unexpected storage response")
            except Exception:
                warnings.append("Node storage diagnostics unavailable")
            try:
                samples = self.proxmox.nodes(node).rrddata.get(timeframe="hour")
                if not isinstance(samples, list):
                    raise ValueError("Unexpected RRD response")
                fields = ("diskread", "diskwrite", "netin", "netout", "iowait")
                def observed(value):
                    return type(value) in (int, float) and math.isfinite(value)

                usable = [s for s in samples if isinstance(s, dict)
                          and observed(s.get("time"))
                          and any(observed(s.get(field)) for field in fields)]
                if not usable:
                    raise ValueError("No observed RRD I/O samples")
                latest = max(usable, key=lambda s: s["time"])
                recent_io = {k: latest.get(k) if observed(latest.get(k)) else None
                             for k in ("time", *fields)}
            except Exception:
                warnings.append("Node RRD I/O metrics unavailable")
            return self._format_response({
                "node": node, "uptime": status.get("uptime"),
                "cpu_fraction": status.get("cpu"),
                "io_wait_fraction": status.get("wait"),
                "load_average": status.get("loadavg"),
                "cpuinfo": status.get("cpuinfo"),
                "memory": status.get("memory"), "swap": status.get("swap"),
                "rootfs": status.get("rootfs"),
                "storage": storage, "latest_rrd_io": recent_io,
                "process_list_available": False,
                "warnings": warnings, "complete": not warnings,
            })
        except Exception as error:
            self._handle_error(f"get diagnostics for node {node}", error)
