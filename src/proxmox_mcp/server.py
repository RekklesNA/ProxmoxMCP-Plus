"""
Main server implementation for Proxmox MCP.

This module wires configuration, Proxmox connectivity, observability, policy
controls, and pluggable MCP tool registration together.
"""

from __future__ import annotations

import os
import signal
import sys
from typing import Literal, Optional, cast

from mcp.server.fastmcp import FastMCP

from proxmox_mcp.config.loader import load_config
from proxmox_mcp.core.logging import setup_logging
from proxmox_mcp.core.proxmox import ProxmoxManager
from proxmox_mcp.observability import ToolMetrics
from proxmox_mcp.security import CommandPolicyGate
from proxmox_mcp.services import JobStore, ToolRegistry
from proxmox_mcp.services.builtin_tool_plugins import (
    BackupToolsPlugin,
    ContainerToolsPlugin,
    CoreToolsPlugin,
    ImageToolsPlugin,
    JobsToolsPlugin,
    SnapshotToolsPlugin,
    VMToolsPlugin,
)
from proxmox_mcp.tools.backup import BackupTools
from proxmox_mcp.tools.cluster import ClusterTools
from proxmox_mcp.tools.containers import ContainerTools
from proxmox_mcp.tools.iso import ISOTools
from proxmox_mcp.tools.jobs import JobsTools
from proxmox_mcp.tools.node import NodeTools
from proxmox_mcp.tools.snapshots import SnapshotTools
from proxmox_mcp.tools.storage import StorageTools
from proxmox_mcp.tools.vm import VMTools


class ProxmoxMCPServer:
    """Main server class for Proxmox MCP."""

    def __init__(self, config_path: Optional[str] = None):
        self.config = load_config(config_path)
        self.logger = setup_logging(self.config.logging)

        self.proxmox_manager = ProxmoxManager(
            self.config.proxmox,
            self.config.auth,
            api_tunnel_config=self.config.api_tunnel,
            ssh_config=self.config.ssh,
        )
        self.proxmox = self.proxmox_manager.get_api()
        self.command_policy = CommandPolicyGate(self.config.command_policy)
        self.metrics = ToolMetrics()
        self.job_store = JobStore(self.proxmox, sqlite_path=self.config.jobs.sqlite_path)

        self.node_tools = NodeTools(self.proxmox, metrics=self.metrics, job_store=self.job_store)
        self.vm_tools = VMTools(
            self.proxmox,
            command_policy=self.command_policy,
            metrics=self.metrics,
            job_store=self.job_store,
        )
        self.storage_tools = StorageTools(self.proxmox, metrics=self.metrics, job_store=self.job_store)
        self.cluster_tools = ClusterTools(self.proxmox, metrics=self.metrics, job_store=self.job_store)
        self.container_tools = ContainerTools(
            self.proxmox,
            self.config.ssh,
            command_policy=self.command_policy,
            metrics=self.metrics,
            job_store=self.job_store,
        )
        self.snapshot_tools = SnapshotTools(self.proxmox, metrics=self.metrics, job_store=self.job_store)
        self.iso_tools = ISOTools(self.proxmox, metrics=self.metrics, job_store=self.job_store)
        self.backup_tools = BackupTools(self.proxmox, metrics=self.metrics, job_store=self.job_store)
        self.jobs_tools = JobsTools(self.job_store)

        self.mcp = FastMCP(
            "ProxmoxMCP",
            host=self.config.mcp.host,
            port=self.config.mcp.port,
            log_level=cast(
                Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                self.config.logging.level.upper(),
            ),
        )
        self.tool_registry = ToolRegistry()
        self._setup_tools()

    def _setup_tools(self) -> None:
        self.tool_registry.add(CoreToolsPlugin())
        self.tool_registry.add(JobsToolsPlugin())
        self.tool_registry.add(VMToolsPlugin())
        self.tool_registry.add(ContainerToolsPlugin())
        self.tool_registry.add(SnapshotToolsPlugin())
        self.tool_registry.add(ImageToolsPlugin())
        self.tool_registry.add(BackupToolsPlugin())
        self.tool_registry.register_all(self)

    def start(self) -> None:
        """Start the MCP server with the configured transport."""
        import anyio

        def signal_handler(signum: int, frame: object) -> None:
            self.logger.info("Received signal to shutdown...")
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            transport = self.config.mcp.transport
            self.logger.info("Starting Proxmox MCP Server with transport: %s", transport)

            if transport == "STDIO":
                anyio.run(self.mcp.run_stdio_async)
            elif transport == "SSE":
                anyio.run(self.mcp.run_sse_async)
            elif transport == "STREAMABLE":
                try:
                    anyio.run(self.mcp.run_streamable_http_async)
                except AttributeError:
                    anyio.run(self.mcp.run_sse_async)
            else:
                anyio.run(self.mcp.run_stdio_async)
        except Exception as e:
            self.logger.error("Server execution failed: %s", e)
            sys.exit(1)


def main() -> None:
    """CLI entrypoint for running the Proxmox MCP server."""
    config_path = os.getenv("PROXMOX_MCP_CONFIG")

    try:
        server = ProxmoxMCPServer(config_path)
        server.start()
    except KeyboardInterrupt:
        print("\nShutting down gracefully...", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        import traceback

        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        print(f"Server initialization failed: {e}", file=sys.stderr)
        sys.stderr.flush()
        sys.exit(1)


if __name__ == "__main__":
    main()
