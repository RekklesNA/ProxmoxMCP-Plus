"""
Main server implementation for Proxmox MCP.

This module wires configuration, Proxmox connectivity, observability, policy
controls, and pluggable MCP tool registration together.
"""

from __future__ import annotations

import os
import signal
import sys
from typing import Any, Literal, NoReturn, Optional, cast
from types import SimpleNamespace

from mcp.server.fastmcp import FastMCP
from proxmox_mcp.config.loader import load_config
from proxmox_mcp.core.logging import setup_logging
from proxmox_mcp.core.proxmox import ProxmoxManager
from proxmox_mcp.core.targets import TargetRegistry
from proxmox_mcp.mcp_http_auth import MCPBearerAuthMiddleware
from proxmox_mcp.observability import ToolMetrics
from proxmox_mcp.security import CommandPolicyGate
from proxmox_mcp.services import JobStore, ToolRegistry
from proxmox_mcp.services.builtin_tool_plugins import (
    BackupToolsPlugin,
    ContainerToolsPlugin,
    CoreToolsPlugin,
    ImageToolsPlugin,
    JobsToolsPlugin,
    LogToolsPlugin,
    SnapshotToolsPlugin,
    VMToolsPlugin,
)
from proxmox_mcp.tools.backup import BackupTools
from proxmox_mcp.tools.cluster import ClusterTools
from proxmox_mcp.tools.containers import ContainerTools
from proxmox_mcp.tools.iso import ISOTools
from proxmox_mcp.tools.jobs import JobsTools
from proxmox_mcp.tools.logs import LogTools
from proxmox_mcp.tools.node import NodeTools
from proxmox_mcp.tools.snapshots import SnapshotTools
from proxmox_mcp.tools.storage import StorageTools
from proxmox_mcp.tools.vm import VMTools

TransportSecuritySettings: Any
try:
    from mcp.server.transport_security import TransportSecuritySettings
except ImportError:  # pragma: no cover - exercised only with older MCP SDKs
    TransportSecuritySettings = None


def _log_safe(value: object, max_length: int = 200) -> str:
    text = str(value).replace("\r", "").replace("\n", "")
    return text[:max_length]


def _exit_without_finalization(status: int = 0) -> NoReturn:
    """Terminate the process without running interpreter finalization.

    Raising ``SystemExit`` from a signal handler is unsafe under the stdio
    transport. The MCP SDK reads stdin from an AnyIO worker thread, using its
    own ``TextIOWrapper`` built on ``sys.stdin.buffer``
    (``mcp.server.stdio.stdio_server``). A signal arriving mid-read leaves that
    thread blocked inside ``readline()``, owning the lock of the
    ``BufferedReader`` it shares with ``sys.stdin``.

    ``SystemExit`` would then start interpreter finalization, which clears the
    ``sys`` module dict, deallocates ``sys.stdin`` and tries to close that same
    ``BufferedReader``. The lock is never released, so CPython gives up after
    its one-second grace period and calls ``Py_FatalError``::

        Fatal Python error: _enter_buffered_busy: could not acquire lock for
        <_io.BufferedReader name='<stdin>'> at interpreter shutdown, possibly
        due to daemon threads

    which aborts the process with ``SIGABRT``. ``os._exit()`` skips
    finalization entirely, so the shutdown is clean. Callers are responsible
    for releasing anything that matters before calling this.

    Standard streams are intentionally not flushed here. The SDK also writes
    stdout through an AnyIO worker thread and a second ``TextIOWrapper``. If
    that worker is blocked on a full pipe while holding the shared buffered
    writer lock, flushing from the signal handler would deadlock before
    ``os._exit()`` can run. The signal handler calls ``close()`` first to
    release application-owned resources.
    """
    os._exit(status)


class ProxmoxMCPServer:
    """Main server class for Proxmox MCP."""

    def __init__(self, config_path: Optional[str] = None):
        self.config = load_config(config_path)
        self.logger = setup_logging(self.config.logging)
        self.target_registry = TargetRegistry(self.config)
        self.proxmox_managers = {
            name: ProxmoxManager(
                target.config,
                target.auth,
                api_tunnel_config=target.api_tunnel,
                ssh_config=target.ssh,
            )
            for name in self.target_registry.names
            for target in [self.target_registry.resolve(name)]
        }
        # Tool dispatch is kept on the legacy default manager until each tool
        # receives its explicit target parameter. Multi-target callers use
        # list_targets during this incremental migration.
        self.proxmox_manager = next(iter(self.proxmox_managers.values()))
        self.proxmox = self.proxmox_manager.get_api()
        self.command_policy = CommandPolicyGate(self.config.command_policy)
        self.target_command_policies = {
            name: CommandPolicyGate(target.command_policy or self.config.command_policy)
            for name, target in ((name, self.target_registry.resolve(name)) for name in self.target_registry.names)
        }
        self.metrics = ToolMetrics()
        self.job_store = JobStore(self.proxmox, sqlite_path=self.config.jobs.sqlite_path)
        self.target_node_tools = {
            name: NodeTools(manager.get_api(), metrics=self.metrics, job_store=self.job_store)
            for name, manager in self.proxmox_managers.items()
        }
        self.target_storage_tools = {
            name: StorageTools(manager.get_api(), metrics=self.metrics, job_store=self.job_store)
            for name, manager in self.proxmox_managers.items()
        }
        self.target_cluster_tools = {
            name: ClusterTools(manager.get_api(), metrics=self.metrics, job_store=self.job_store)
            for name, manager in self.proxmox_managers.items()
        }

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
        self.log_tools = LogTools(self.proxmox, metrics=self.metrics, job_store=self.job_store)

        if self.target_registry.names == ("default",):
            self.target_node_tools["default"] = self.node_tools
            self.target_storage_tools["default"] = self.storage_tools
            self.target_cluster_tools["default"] = self.cluster_tools

        self.target_job_stores: dict[str, JobStore] = {}
        self.target_toolsets: dict[str, SimpleNamespace] = {}
        for name, manager in self.proxmox_managers.items():
            if name == "default" and self.target_registry.names == ("default",):
                self.target_job_stores[name] = self.job_store
                self.target_toolsets[name] = SimpleNamespace(
                    node_tools=self.node_tools,
                    storage_tools=self.storage_tools,
                    cluster_tools=self.cluster_tools,
                    vm_tools=self.vm_tools,
                    container_tools=self.container_tools,
                    snapshot_tools=self.snapshot_tools,
                    iso_tools=self.iso_tools,
                    backup_tools=self.backup_tools,
                    jobs_tools=self.jobs_tools,
                    log_tools=self.log_tools,
                )
                continue
            target = self.target_registry.resolve(name)
            api = manager.get_api()
            base_path = self.config.jobs.sqlite_path
            path = base_path
            if name != "default" or self.target_registry.names != ("default",):
                path = f"{base_path}-{name}"
            job_store = JobStore(api, sqlite_path=path, target_name=name)
            self.target_job_stores[name] = job_store
            self.target_toolsets[name] = SimpleNamespace(
                node_tools=NodeTools(api, metrics=self.metrics, job_store=job_store),
                storage_tools=StorageTools(api, metrics=self.metrics, job_store=job_store),
                cluster_tools=ClusterTools(api, metrics=self.metrics, job_store=job_store),
                vm_tools=VMTools(api, command_policy=self.command_policy, metrics=self.metrics, job_store=job_store),
                container_tools=ContainerTools(api, target.ssh or self.config.ssh, command_policy=self.command_policy, metrics=self.metrics, job_store=job_store),
                snapshot_tools=SnapshotTools(api, metrics=self.metrics, job_store=job_store),
                iso_tools=ISOTools(api, metrics=self.metrics, job_store=job_store),
                backup_tools=BackupTools(api, metrics=self.metrics, job_store=job_store),
                jobs_tools=JobsTools(job_store),
                log_tools=LogTools(api, metrics=self.metrics, job_store=job_store),
            )

        log_level = cast(
            Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            self.config.logging.level.upper(),
        )
        transport_security = self._build_transport_security()
        if transport_security is None:
            self.mcp = FastMCP(
                "ProxmoxMCP",
                host=self.config.mcp.host,
                port=self.config.mcp.port,
                log_level=log_level,
            )
        else:
            self.mcp = FastMCP(
                "ProxmoxMCP",
                host=self.config.mcp.host,
                port=self.config.mcp.port,
                log_level=log_level,
                transport_security=transport_security,
            )
        self.tool_registry = ToolRegistry()
        self._setup_tools()

    def _build_transport_security(self) -> Any | None:
        mcp_config = self.config.mcp
        configured = (
            mcp_config.dns_rebinding_protection is not None
            or bool(mcp_config.allowed_hosts)
            or bool(mcp_config.allowed_origins)
        )
        if not configured:
            return None
        if TransportSecuritySettings is None:
            raise RuntimeError(
                "MCP transport security settings require mcp>=1.24.0. "
                "Upgrade the mcp package or remove mcp.dns_rebinding_protection, "
                "mcp.allowed_hosts, and mcp.allowed_origins from the config."
            )

        enable_protection = mcp_config.dns_rebinding_protection
        if enable_protection is None:
            enable_protection = True

        return TransportSecuritySettings(
            enable_dns_rebinding_protection=enable_protection,
            allowed_hosts=mcp_config.allowed_hosts,
            allowed_origins=mcp_config.allowed_origins,
        )

    def _setup_tools(self) -> None:
        self.tool_registry.add(CoreToolsPlugin())
        self.tool_registry.add(JobsToolsPlugin())
        self.tool_registry.add(VMToolsPlugin())
        self.tool_registry.add(ContainerToolsPlugin())
        self.tool_registry.add(SnapshotToolsPlugin())
        self.tool_registry.add(ImageToolsPlugin())
        self.tool_registry.add(BackupToolsPlugin())
        self.tool_registry.add(LogToolsPlugin())
        self.tool_registry.register_all(self)

    def target_tools(self, requested: str | None) -> SimpleNamespace:
        name = self.target_registry.resolve(requested).name
        return self.target_toolsets[name]

    def close(self) -> None:
        self.job_store.close()
        for job_store in self.target_job_stores.values():
            if job_store is not self.job_store:
                job_store.close()
        for manager in self.proxmox_managers.values():
            manager.close()

    async def _run_streamable_http_async(self) -> None:
        """Run Streamable HTTP with optional inbound Bearer authentication."""
        import uvicorn

        app: Any = self.mcp.streamable_http_app()
        api_key = os.getenv("MCP_API_KEY")
        if api_key:
            app = MCPBearerAuthMiddleware(app, api_key=api_key)
            self.logger.info("MCP Streamable HTTP bearer authentication is enabled")
        else:
            self.logger.warning(
                "MCP Streamable HTTP is running without MCP_API_KEY; "
                "any client that can reach the endpoint may invoke MCP tools"
            )

        config = uvicorn.Config(
            app,
            host=self.mcp.settings.host,
            port=self.mcp.settings.port,
            log_level=self.mcp.settings.log_level.lower(),
        )
        await uvicorn.Server(config).serve()

    def start(self) -> None:
        """Start the MCP server with the configured transport."""
        import anyio

        transport = self.config.mcp.transport
        # Mirrors the dispatch below: anything that is not SSE or STREAMABLE
        # is served over stdio.
        uses_stdio = transport not in ("SSE", "STREAMABLE")

        def signal_handler(signum: int, frame: object) -> None:
            self.logger.info("Received signal to shutdown...")
            if uses_stdio:
                try:
                    self.close()
                finally:
                    _exit_without_finalization()
            else:
                self.close()
                sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            self.logger.info("Starting Proxmox MCP Server with transport: %s", transport)

            if transport == "STDIO":
                anyio.run(self.mcp.run_stdio_async)
            elif transport == "SSE":
                anyio.run(self.mcp.run_sse_async)
            elif transport == "STREAMABLE":
                try:
                    anyio.run(self._run_streamable_http_async)
                except AttributeError:
                    anyio.run(self.mcp.run_sse_async)
            else:
                anyio.run(self.mcp.run_stdio_async)
        except Exception as e:
            self.logger.error("Server execution failed: %s", _log_safe(e))
            sys.exit(1)
        finally:
            self.close()


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
