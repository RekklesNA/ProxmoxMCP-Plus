"""
Main server implementation for Proxmox MCP.

This module implements the core MCP server for Proxmox integration, providing:
- Configuration loading and validation
- Logging setup
- Proxmox API connection management
- MCP tool registration and routing
- Signal handling for graceful shutdown

The server exposes a set of tools for managing Proxmox resources including:
- Node management
- VM operations
- Storage management
- Cluster status monitoring
"""
import logging
import os
import sys
import signal
from typing import Optional, List, Annotated

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools import Tool
from mcp.types import TextContent as Content
from pydantic import Field

from .config.loader import load_config
from .core.logging import setup_logging
from .core.proxmox import ProxmoxManager
from .tools.node import NodeTools
from .tools.vm import VMTools
from .tools.storage import StorageTools
from .tools.cluster import ClusterTools
from .tools.containers import ContainerTools
from .tools.definitions import (
    GET_NODES_DESC,
    GET_NODE_STATUS_DESC,
    GET_VMS_DESC,
    CREATE_VM_DESC,
    EXECUTE_VM_COMMAND_DESC,
    START_VM_DESC,
    STOP_VM_DESC,
    SHUTDOWN_VM_DESC,
    RESET_VM_DESC,
    DELETE_VM_DESC,
    GET_CONTAINERS_DESC,
    START_CONTAINER_DESC,
    STOP_CONTAINER_DESC,
    RESTART_CONTAINER_DESC,
    GET_STORAGE_DESC,
    GET_CLUSTER_STATUS_DESC
)

class ProxmoxMCPServer:
    """Main server class for Proxmox MCP."""

    def __init__(self, config_path: Optional[str] = None):
        """
        Create and configure a Proxmox MCP server instance.
        
        Loads configuration from the given path (or default), sets up logging, initializes the Proxmox API manager and API handle, constructs tool layers for nodes, VMs, storage, cluster, and containers, creates the MCP server instance named "ProxmoxMCP", and registers MCP tools.
        
        Parameters:
            config_path (Optional[str]): Path to the configuration file. If None, a default config location is used.
        """
        self.config = load_config(config_path)
        self.logger = setup_logging(self.config.logging)
        
        # Initialize core components
        self.proxmox_manager = ProxmoxManager(self.config.proxmox, self.config.auth)
        self.proxmox = self.proxmox_manager.get_api()
        
        # Initialize tools
        self.node_tools = NodeTools(self.proxmox)
        self.vm_tools = VMTools(self.proxmox)
        self.storage_tools = StorageTools(self.proxmox)
        self.cluster_tools = ClusterTools(self.proxmox)
        self.container_tools = ContainerTools(self.proxmox)

        
        # Initialize MCP server
        self.mcp = FastMCP("ProxmoxMCP")
        self._setup_tools()

    def _setup_tools(self) -> None:
        """Register MCP tools with the server.
        
        Initializes and registers all available tools with the MCP server:
        - Node management tools (list nodes, get status)
        - VM operation tools (list VMs, execute commands, power management)
        - Storage management tools (list storage)
        - Cluster tools (get cluster status)
        
        Each tool is registered with appropriate descriptions and parameter
        validation using Pydantic models.
        """
        
        # Node tools
        @self.mcp.tool(description=GET_NODES_DESC)
        def get_nodes():
            return self.node_tools.get_nodes()

        @self.mcp.tool(description=GET_NODE_STATUS_DESC)
        def get_node_status(
            node: Annotated[str, Field(description="Name/ID of node to query (e.g. 'pve1', 'proxmox-node2')")]
        ):
            return self.node_tools.get_node_status(node)

        # VM tools
        @self.mcp.tool(description=GET_VMS_DESC)
        def get_vms():
            return self.vm_tools.get_vms()

        @self.mcp.tool(description=CREATE_VM_DESC)
        def create_vm(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="New VM ID number (e.g. '200', '300')")],
            name: Annotated[str, Field(description="VM name (e.g. 'my-new-vm', 'web-server')")],
            cpus: Annotated[int, Field(description="Number of CPU cores (e.g. 1, 2, 4)", ge=1, le=32)],
            memory: Annotated[int, Field(description="Memory size in MB (e.g. 2048 for 2GB)", ge=512, le=131072)],
            disk_size: Annotated[int, Field(description="Disk size in GB (e.g. 10, 20, 50)", ge=5, le=1000)],
            storage: Annotated[Optional[str], Field(description="Storage name (optional, will auto-detect)", default=None)] = None,
            ostype: Annotated[Optional[str], Field(description="OS type (optional, default: 'l26' for Linux)", default=None)] = None
        ):
            return self.vm_tools.create_vm(node, vmid, name, cpus, memory, disk_size, storage, ostype)

        @self.mcp.tool(description=EXECUTE_VM_COMMAND_DESC)
        async def execute_vm_command(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve1', 'proxmox-node2')")],
            vmid: Annotated[str, Field(description="VM ID number (e.g. '100', '101')")],
            command: Annotated[str, Field(description="Shell command to run (e.g. 'uname -a', 'systemctl status nginx')")]
        ):
            return await self.vm_tools.execute_command(node, vmid, command)

        # VM Power Management tools
        @self.mcp.tool(description=START_VM_DESC)
        def start_vm(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="VM ID number (e.g. '101')")]
        ):
            return self.vm_tools.start_vm(node, vmid)

        @self.mcp.tool(description=STOP_VM_DESC)
        def stop_vm(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="VM ID number (e.g. '101')")]
        ):
            return self.vm_tools.stop_vm(node, vmid)

        @self.mcp.tool(description=SHUTDOWN_VM_DESC)
        def shutdown_vm(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="VM ID number (e.g. '101')")]
        ):
            return self.vm_tools.shutdown_vm(node, vmid)

        @self.mcp.tool(description=RESET_VM_DESC)
        def reset_vm(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="VM ID number (e.g. '101')")]
        ):
            return self.vm_tools.reset_vm(node, vmid)

        @self.mcp.tool(description=DELETE_VM_DESC)
        def delete_vm(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="VM ID number (e.g. '998')")],
            force: Annotated[bool, Field(description="Force deletion even if VM is running", default=False)] = False
        ):
            return self.vm_tools.delete_vm(node, vmid, force)

        # Storage tools
        @self.mcp.tool(description=GET_STORAGE_DESC)
        def get_storage():
            return self.storage_tools.get_storage()

        # Cluster tools
        @self.mcp.tool(description=GET_CLUSTER_STATUS_DESC)
        def get_cluster_status():
            """
            Return the current cluster status.
            
            Returns:
                The cluster status information as provided by the ClusterTools layer (structure depends on ClusterTools.get_cluster_status).
            """
            return self.cluster_tools.get_cluster_status()

        # Containers (LXC)
        @self.mcp.tool(description=GET_CONTAINERS_DESC)
        def get_containers(
            node: Annotated[Optional[str], Field(description="Optional node name (e.g. 'pve1')")] = None,
            include_stats: Annotated[bool, Field(description="Include live stats and fallbacks", default=True)] = True,
            include_raw: Annotated[bool, Field(description="Include raw status/config", default=False)] = False,
            format_style: Annotated[str, Field(description="'pretty' or 'json'", pattern="^(pretty|json)$")] = "pretty",
        ):
            """
            Return information about LXC containers.
            
            Filters by optional node and can include live stats and/or raw status/config data. The output is formatted according to `format_style` ('pretty' or 'json').
            
            Parameters:
                node: Optional node name to limit results (e.g. "pve1").
                include_stats: If True, include live statistics with fallbacks.
                include_raw: If True, include raw status/config fields in the output.
                format_style: Output format, either "pretty" or "json".
            
            Returns:
                Container information formatted according to `format_style`.
            """
            return self.container_tools.get_containers(
                node=node, include_stats=include_stats, include_raw=include_raw, format_style=format_style
            )

        # Container controls
        @self.mcp.tool(description=START_CONTAINER_DESC)
        def start_container(
            selector: Annotated[str, Field(description="CT selector: '123' | 'pve1:123' | 'pve1/name' | 'name' | comma list")],
            format_style: Annotated[str, Field(description="'pretty' or 'json'", pattern="^(pretty|json)$")] = "pretty",
        ):
            """
            Start one or more LXC containers matching the given selector.
            
            Delegates to the ContainerTools implementation to start containers identified by
            selector (allowed forms: "123", "pve1:123", "pve1/name", "name", or a comma-separated list).
            The response is formatted according to format_style.
            
            Parameters:
                selector (str): Container selector(s); supports node-qualified and comma-separated forms.
                format_style (str): Output format, either "pretty" or "json" (default "pretty").
            
            Returns:
                The result of the start operation formatted per `format_style` (a human-readable string for
                "pretty" or a JSON-serializable object for "json").
            """
            return self.container_tools.start_container(selector=selector, format_style=format_style)

        @self.mcp.tool(description=STOP_CONTAINER_DESC)
        def stop_container(
            selector: Annotated[str, Field(description="CT selector (see start_container)")],
            graceful: Annotated[bool, Field(description="Graceful shutdown (True) or forced stop (False)", default=False)] = False,
            timeout_seconds: Annotated[int, Field(description="Timeout for stop/shutdown", ge=1, le=600)] = 10,
            format_style: Annotated[str, Field(description="'pretty' or 'json'", pattern="^(pretty|json)$")] = "pretty",
        ):
            """
            Stop one or more LXC containers matching the given selector.
            
            Stops containers either gracefully (attempt clean shutdown) or forcefully, with a configurable timeout. The selector accepts the same formats as `start_container` (e.g. "123", "pve1:123", "pve1/name", "name", or a comma-separated list).
            
            Parameters:
                selector: Container selector string identifying one or more containers.
                graceful: If True, attempt a graceful shutdown; if False, perform a forced stop.
                timeout_seconds: Maximum seconds to wait for shutdown/restart (1–600).
                format_style: Output format, either "pretty" or "json".
            
            Returns:
                The stop operation result formatted according to `format_style`.
            """
            return self.container_tools.stop_container(
               selector=selector, graceful=graceful, timeout_seconds=timeout_seconds, format_style=format_style
            )

        @self.mcp.tool(description=RESTART_CONTAINER_DESC)
        def restart_container(
            selector: Annotated[str, Field(description="CT selector (see start_container)")],
            timeout_seconds: Annotated[int, Field(description="Timeout for reboot", ge=1, le=600)] = 10,
            format_style: Annotated[str, Field(description="'pretty' or 'json'", pattern="^(pretty|json)$")] = "pretty",
        ):
            """
            Restart one or more LXC containers matching the given selector.
            
            Performs a container reboot (stop then start) using the ContainerTools layer and returns the result formatted according to format_style.
            
            Parameters:
                selector (str): Container selector. Accepts numeric VMID, qualified forms like "node:vmid", "node/name", plain name, or a comma-separated list of selectors.
                timeout_seconds (int): Maximum seconds to wait for the container to stop/reboot (1–600). Defaults to 10.
                format_style (str): Output format, either "pretty" or "json". Defaults to "pretty".
            
            Returns:
                The formatted result produced by ContainerTools.restart_container (structure depends on format_style).
            """
            return self.container_tools.restart_container(
               selector=selector, timeout_seconds=timeout_seconds, format_style=format_style
            )


    def start(self) -> None:
        """
        Start and run the MCP server, blocking until shutdown.
        
        Runs the MCP main loop using anyio and installs handlers for SIGINT and SIGTERM to perform a graceful shutdown. Exits the process with a nonzero status on unexpected fatal errors.
        """
        import anyio

        def signal_handler(signum, frame):
            self.logger.info("Received signal to shutdown...")
            sys.exit(0)

        # Set up signal handlers
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            self.logger.info("Starting MCP server...")
            anyio.run(self.mcp.run_stdio_async)
        except Exception as e:
            self.logger.error(f"Server error: {e}")
            sys.exit(1)

if __name__ == "__main__":
    config_path = os.getenv("PROXMOX_MCP_CONFIG")
    if not config_path:
        print("PROXMOX_MCP_CONFIG environment variable must be set")
        sys.exit(1)
    
    try:
        server = ProxmoxMCPServer(config_path)
        server.start()
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
