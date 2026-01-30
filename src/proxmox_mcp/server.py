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
from typing import Optional, List, Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools import Tool
from mcp.types import TextContent as Content
from pydantic import Field, BaseModel
from fastapi import Body

from .config.loader import load_config
from .core.logging import setup_logging
from .core.proxmox import ProxmoxManager
from .tools.node import NodeTools
from .tools.vm import VMTools
from .tools.storage import StorageTools
from .tools.cluster import ClusterTools
from .tools.containers import ContainerTools
from .tools.snapshots import SnapshotTools
from .tools.iso import ISOTools
from .tools.backup import BackupTools
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
    UPDATE_CONTAINER_RESOURCES_DESC,
    CREATE_CONTAINER_DESC,
    DELETE_CONTAINER_DESC,
    GET_STORAGE_DESC,
    GET_CLUSTER_STATUS_DESC,
    # Snapshot tools
    LIST_SNAPSHOTS_DESC,
    CREATE_SNAPSHOT_DESC,
    DELETE_SNAPSHOT_DESC,
    ROLLBACK_SNAPSHOT_DESC,
    # ISO tools
    LIST_ISOS_DESC,
    LIST_TEMPLATES_DESC,
    DOWNLOAD_ISO_DESC,
    DELETE_ISO_DESC,
    # Backup tools
    LIST_BACKUPS_DESC,
    CREATE_BACKUP_DESC,
    RESTORE_BACKUP_DESC,
    DELETE_BACKUP_DESC,
)

class ProxmoxMCPServer:
    """Main server class for Proxmox MCP."""

    def __init__(self, config_path: Optional[str] = None):
        """Initialize the server.

        Args:
            config_path: Path to configuration file
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
        self.snapshot_tools = SnapshotTools(self.proxmox)
        self.iso_tools = ISOTools(self.proxmox)
        self.backup_tools = BackupTools(self.proxmox)

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
            return self.cluster_tools.get_cluster_status()

        # Containers (LXC)
        class GetContainersPayload(BaseModel):
            node: Optional[str] = Field(None, description="Optional node name (e.g. 'pve1')")
            include_stats: bool = Field(True, description="Include live stats and fallbacks")
            include_raw: bool = Field(False, description="Include raw status/config")
            format_style: Literal["pretty", "json"] = Field(
                "pretty", description="'pretty' or 'json'"
            )

        @self.mcp.tool(description=GET_CONTAINERS_DESC)
        def get_containers(
            payload: GetContainersPayload = Body(..., embed=True, description="Container query options")
        ):
            return self.container_tools.get_containers(
                node=payload.node,
                include_stats=payload.include_stats,
                include_raw=payload.include_raw,
                format_style=payload.format_style,
            )

        # Container controls
        @self.mcp.tool(description=START_CONTAINER_DESC)
        def start_container(
            selector: Annotated[str, Field(description="CT selector: '123' | 'pve1:123' | 'pve1/name' | 'name' | comma list")],
            format_style: Annotated[str, Field(description="'pretty' or 'json'", pattern="^(pretty|json)$")] = "pretty",
        ):
            return self.container_tools.start_container(selector=selector, format_style=format_style)

        @self.mcp.tool(description=STOP_CONTAINER_DESC)
        def stop_container(
            selector: Annotated[str, Field(description="CT selector (see start_container)")],
            graceful: Annotated[bool, Field(description="Graceful shutdown (True) or forced stop (False)", default=True)] = True,
            timeout_seconds: Annotated[int, Field(description="Timeout for stop/shutdown", ge=1, le=600)] = 10,
            format_style: Annotated[Literal["pretty","json"], Field(description="Output format")] = "pretty",
        ):
            return self.container_tools.stop_container(
               selector=selector, graceful=graceful, timeout_seconds=timeout_seconds, format_style=format_style
            )
        @self.mcp.tool(description=RESTART_CONTAINER_DESC)
        def restart_container(
            selector: Annotated[str, Field(description="CT selector (see start_container)")],
            timeout_seconds: Annotated[int, Field(description="Timeout for reboot", ge=1, le=600)] = 10,
            format_style: Annotated[str, Field(description="'pretty' or 'json'", pattern="^(pretty|json)$")] = "pretty",
        ):
            return self.container_tools.restart_container(
               selector=selector, timeout_seconds=timeout_seconds, format_style=format_style
            )

        @self.mcp.tool(description=UPDATE_CONTAINER_RESOURCES_DESC)
        def update_container_resources(
            selector: Annotated[str, Field(description="CT selector (see start_container)")],
            cores: Annotated[Optional[int], Field(description="New CPU core count", ge=1)] = None,
            memory: Annotated[Optional[int], Field(description="New memory limit in MiB", ge=16)] = None,
            swap: Annotated[Optional[int], Field(description="New swap limit in MiB", ge=0)] = None,
            disk_gb: Annotated[Optional[int], Field(description="Additional disk size in GiB", ge=1)] = None,
            disk: Annotated[str, Field(description="Disk to resize", default="rootfs")] = "rootfs",
            format_style: Annotated[Literal["pretty","json"], Field(description="Output format")] = "pretty",
        ):
            return self.container_tools.update_container_resources(
                selector=selector,
                cores=cores,
                memory=memory,
                swap=swap,
                disk_gb=disk_gb,
                disk=disk,
                format_style=format_style,
            )

        @self.mcp.tool(description=CREATE_CONTAINER_DESC)
        def create_container(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="Container ID number (e.g. '200')")],
            ostemplate: Annotated[str, Field(description="OS template path (e.g. 'local:vztmpl/alpine-3.19-default_20240207_amd64.tar.xz')")],
            hostname: Annotated[Optional[str], Field(description="Container hostname", default=None)] = None,
            cores: Annotated[int, Field(description="Number of CPU cores", ge=1, default=1)] = 1,
            memory: Annotated[int, Field(description="Memory size in MiB", ge=16, default=512)] = 512,
            swap: Annotated[int, Field(description="Swap size in MiB", ge=0, default=512)] = 512,
            disk_size: Annotated[int, Field(description="Root disk size in GB", ge=1, default=8)] = 8,
            storage: Annotated[Optional[str], Field(description="Storage pool (auto-detect if not specified)", default=None)] = None,
            password: Annotated[Optional[str], Field(description="Root password", default=None)] = None,
            ssh_public_keys: Annotated[Optional[str], Field(description="SSH public keys for root", default=None)] = None,
            network_bridge: Annotated[str, Field(description="Network bridge", default="vmbr0")] = "vmbr0",
            start_after_create: Annotated[bool, Field(description="Start container after creation", default=False)] = False,
            unprivileged: Annotated[bool, Field(description="Create unprivileged container", default=True)] = True,
        ):
            return self.container_tools.create_container(
                node=node, vmid=vmid, ostemplate=ostemplate, hostname=hostname,
                cores=cores, memory=memory, swap=swap, disk_size=disk_size,
                storage=storage, password=password, ssh_public_keys=ssh_public_keys,
                network_bridge=network_bridge, start_after_create=start_after_create,
                unprivileged=unprivileged,
            )

        @self.mcp.tool(description=DELETE_CONTAINER_DESC)
        def delete_container(
            selector: Annotated[str, Field(description="CT selector: '123' | 'pve1:123' | 'pve1/name' | 'name' | comma list")],
            force: Annotated[bool, Field(description="Force deletion even if running", default=False)] = False,
            format_style: Annotated[Literal["pretty","json"], Field(description="Output format")] = "pretty",
        ):
            return self.container_tools.delete_container(
                selector=selector, force=force, format_style=format_style
            )

        # Snapshot tools
        @self.mcp.tool(description=LIST_SNAPSHOTS_DESC)
        def list_snapshots(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="VM or container ID (e.g. '100')")],
            vm_type: Annotated[str, Field(description="Type: 'qemu' for VMs, 'lxc' for containers", default="qemu")] = "qemu",
        ):
            return self.snapshot_tools.list_snapshots(node=node, vmid=vmid, vm_type=vm_type)

        @self.mcp.tool(description=CREATE_SNAPSHOT_DESC)
        def create_snapshot(
            node: Annotated[str, Field(description="Host node name")],
            vmid: Annotated[str, Field(description="VM or container ID")],
            snapname: Annotated[str, Field(description="Snapshot name (no spaces)")],
            description: Annotated[Optional[str], Field(description="Optional description", default=None)] = None,
            vmstate: Annotated[bool, Field(description="Include memory state (VMs only)", default=False)] = False,
            vm_type: Annotated[str, Field(description="Type: 'qemu' or 'lxc'", default="qemu")] = "qemu",
        ):
            return self.snapshot_tools.create_snapshot(
                node=node, vmid=vmid, snapname=snapname,
                description=description, vmstate=vmstate, vm_type=vm_type
            )

        @self.mcp.tool(description=DELETE_SNAPSHOT_DESC)
        def delete_snapshot(
            node: Annotated[str, Field(description="Host node name")],
            vmid: Annotated[str, Field(description="VM or container ID")],
            snapname: Annotated[str, Field(description="Snapshot name to delete")],
            vm_type: Annotated[str, Field(description="Type: 'qemu' or 'lxc'", default="qemu")] = "qemu",
        ):
            return self.snapshot_tools.delete_snapshot(
                node=node, vmid=vmid, snapname=snapname, vm_type=vm_type
            )

        @self.mcp.tool(description=ROLLBACK_SNAPSHOT_DESC)
        def rollback_snapshot(
            node: Annotated[str, Field(description="Host node name")],
            vmid: Annotated[str, Field(description="VM or container ID")],
            snapname: Annotated[str, Field(description="Snapshot name to restore")],
            vm_type: Annotated[str, Field(description="Type: 'qemu' or 'lxc'", default="qemu")] = "qemu",
        ):
            return self.snapshot_tools.rollback_snapshot(
                node=node, vmid=vmid, snapname=snapname, vm_type=vm_type
            )

        # ISO and Template tools
        @self.mcp.tool(description=LIST_ISOS_DESC)
        def list_isos(
            node: Annotated[Optional[str], Field(description="Filter by node (optional)", default=None)] = None,
            storage: Annotated[Optional[str], Field(description="Filter by storage pool (optional)", default=None)] = None,
        ):
            return self.iso_tools.list_isos(node=node, storage=storage)

        @self.mcp.tool(description=LIST_TEMPLATES_DESC)
        def list_templates(
            node: Annotated[Optional[str], Field(description="Filter by node (optional)", default=None)] = None,
            storage: Annotated[Optional[str], Field(description="Filter by storage pool (optional)", default=None)] = None,
        ):
            return self.iso_tools.list_templates(node=node, storage=storage)

        @self.mcp.tool(description=DOWNLOAD_ISO_DESC)
        def download_iso(
            node: Annotated[str, Field(description="Target node name")],
            storage: Annotated[str, Field(description="Target storage pool")],
            url: Annotated[str, Field(description="URL to download from")],
            filename: Annotated[str, Field(description="Target filename (e.g. 'ubuntu-22.04.iso')")],
            checksum: Annotated[Optional[str], Field(description="Optional checksum", default=None)] = None,
            checksum_algorithm: Annotated[str, Field(description="Algorithm: sha256, sha512, md5", default="sha256")] = "sha256",
        ):
            return self.iso_tools.download_iso(
                node=node, storage=storage, url=url, filename=filename,
                checksum=checksum, checksum_algorithm=checksum_algorithm
            )

        @self.mcp.tool(description=DELETE_ISO_DESC)
        def delete_iso(
            node: Annotated[str, Field(description="Node name")],
            storage: Annotated[str, Field(description="Storage pool name")],
            filename: Annotated[str, Field(description="ISO/template filename to delete")],
        ):
            return self.iso_tools.delete_iso(node=node, storage=storage, filename=filename)

        # Backup and Restore tools
        @self.mcp.tool(description=LIST_BACKUPS_DESC)
        def list_backups(
            node: Annotated[Optional[str], Field(description="Filter by node (optional)", default=None)] = None,
            storage: Annotated[Optional[str], Field(description="Filter by storage pool (optional)", default=None)] = None,
            vmid: Annotated[Optional[str], Field(description="Filter by VM/container ID (optional)", default=None)] = None,
        ):
            return self.backup_tools.list_backups(node=node, storage=storage, vmid=vmid)

        @self.mcp.tool(description=CREATE_BACKUP_DESC)
        def create_backup(
            node: Annotated[str, Field(description="Node where VM/container runs")],
            vmid: Annotated[str, Field(description="VM or container ID to backup")],
            storage: Annotated[str, Field(description="Target backup storage")],
            compress: Annotated[str, Field(description="Compression: 0, gzip, lz4, zstd", default="zstd")] = "zstd",
            mode: Annotated[str, Field(description="Mode: snapshot, suspend, stop", default="snapshot")] = "snapshot",
            notes: Annotated[Optional[str], Field(description="Optional notes", default=None)] = None,
        ):
            return self.backup_tools.create_backup(
                node=node, vmid=vmid, storage=storage,
                compress=compress, mode=mode, notes=notes
            )

        @self.mcp.tool(description=RESTORE_BACKUP_DESC)
        def restore_backup(
            node: Annotated[str, Field(description="Target node for restore")],
            archive: Annotated[str, Field(description="Backup volume ID from list_backups")],
            vmid: Annotated[str, Field(description="New VM/container ID")],
            storage: Annotated[Optional[str], Field(description="Target storage (optional)", default=None)] = None,
            unique: Annotated[bool, Field(description="Generate unique MAC addresses", default=True)] = True,
        ):
            return self.backup_tools.restore_backup(
                node=node, archive=archive, vmid=vmid,
                storage=storage, unique=unique
            )

        @self.mcp.tool(description=DELETE_BACKUP_DESC)
        def delete_backup(
            node: Annotated[str, Field(description="Node name")],
            storage: Annotated[str, Field(description="Storage pool name")],
            volid: Annotated[str, Field(description="Backup volume ID to delete")],
        ):
            return self.backup_tools.delete_backup(node=node, storage=storage, volid=volid)


    def start(self) -> None:
        """Start the MCP server.
        
        Initializes the server with:
        - Signal handlers for graceful shutdown (SIGINT, SIGTERM)
        - Async runtime for handling concurrent requests
        - Error handling and logging
        
        The server runs until terminated by a signal or fatal error.
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
        print("PROXMOX_MCP_CONFIG environment variable must be set", file=sys.stderr)
        sys.exit(1)
    
    try:
        server = ProxmoxMCPServer(config_path)
        server.start()
    except KeyboardInterrupt:
        print("\nShutting down gracefully...", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
