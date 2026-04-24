"""Built-in MCP tool registration plugins."""

from __future__ import annotations

import time
from typing import Annotated, Any, Awaitable, Callable, Literal, Optional

from fastapi import Body
from pydantic import BaseModel, Field

from proxmox_mcp.tools.definitions import (
    CANCEL_JOB_DESC,
    CREATE_BACKUP_DESC,
    CREATE_CONTAINER_DESC,
    CREATE_SNAPSHOT_DESC,
    CREATE_VM_DESC,
    DELETE_BACKUP_DESC,
    DELETE_CONTAINER_DESC,
    DELETE_ISO_DESC,
    DELETE_SNAPSHOT_DESC,
    DELETE_VM_DESC,
    DOWNLOAD_ISO_DESC,
    EXECUTE_CONTAINER_COMMAND_DESC,
    EXECUTE_VM_COMMAND_DESC,
    GET_JOB_DESC,
    GET_CLUSTER_STATUS_DESC,
    GET_CONTAINER_CONFIG_DESC,
    GET_CONTAINER_IP_DESC,
    GET_CONTAINERS_DESC,
    GET_NODES_DESC,
    GET_NODE_STATUS_DESC,
    GET_STORAGE_DESC,
    GET_VMS_DESC,
    LIST_JOBS_DESC,
    LIST_BACKUPS_DESC,
    LIST_ISOS_DESC,
    LIST_SNAPSHOTS_DESC,
    LIST_TEMPLATES_DESC,
    POLL_JOB_DESC,
    RESET_VM_DESC,
    RESTART_CONTAINER_DESC,
    RESTORE_BACKUP_DESC,
    RETRY_JOB_DESC,
    ROLLBACK_SNAPSHOT_DESC,
    SHUTDOWN_VM_DESC,
    START_CONTAINER_DESC,
    START_VM_DESC,
    STOP_CONTAINER_DESC,
    STOP_VM_DESC,
    UPDATE_CONTAINER_RESOURCES_DESC,
    UPDATE_CONTAINER_SSH_KEYS_DESC,
)
from proxmox_mcp.services.tool_registry import ToolRegistryPlugin


class GetContainersPayload(BaseModel):
    node: Optional[str] = Field(None, description="Optional node name (e.g. 'pve1')")
    include_stats: bool = Field(True, description="Include live stats and fallbacks")
    include_raw: bool = Field(False, description="Include raw status/config")
    format_style: Literal["pretty", "json"] = Field("pretty", description="'pretty' or 'json'")


class RegistryPluginBase(ToolRegistryPlugin):
    """Shared wrappers for metrics and operation policy."""

    def _enforce_operation_policy(
        self,
        server: Any,
        tool_name: str,
        approval_token: str | None,
        *,
        high_risk: bool,
    ) -> None:
        if not high_risk:
            return
        decision = server.command_policy.evaluate_operation(
            tool_name,
            approval_token=approval_token,
        )
        if decision.code == "OP_POLICY_AUDIT_ALLOW":
            server.logger.warning("High-risk tool invoked in audit-only mode: %s", tool_name)
        if not decision.allowed:
            raise ValueError(decision.message)

    def _wrap_sync(
        self,
        server: Any,
        tool_name: str,
        handler: Callable[..., Any],
        *,
        high_risk: bool = False,
    ) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            success = False
            approval_token = kwargs.get("approval_token")
            try:
                self._enforce_operation_policy(
                    server,
                    tool_name,
                    approval_token if isinstance(approval_token, str) else None,
                    high_risk=high_risk,
                )
                result = handler(*args, **kwargs)
                success = True
                return result
            finally:
                latency_ms = (time.perf_counter() - start) * 1000.0
                server.metrics.observe(tool_name, latency_ms=latency_ms, success=success)

        return wrapped

    def _wrap_async(
        self,
        server: Any,
        tool_name: str,
        handler: Callable[..., Awaitable[Any]],
        *,
        high_risk: bool = False,
    ) -> Callable[..., Awaitable[Any]]:
        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            success = False
            approval_token = kwargs.get("approval_token")
            try:
                self._enforce_operation_policy(
                    server,
                    tool_name,
                    approval_token if isinstance(approval_token, str) else None,
                    high_risk=high_risk,
                )
                result = await handler(*args, **kwargs)
                success = True
                return result
            finally:
                latency_ms = (time.perf_counter() - start) * 1000.0
                server.metrics.observe(tool_name, latency_ms=latency_ms, success=success)

        return wrapped


class CoreToolsPlugin(RegistryPluginBase):
    def register(self, server: Any) -> None:
        @server.mcp.tool(description=GET_NODES_DESC)
        def get_nodes() -> Any:
            return self._wrap_sync(server, "get_nodes", server.node_tools.get_nodes)()

        @server.mcp.tool(description=GET_NODE_STATUS_DESC)
        def get_node_status(
            node: Annotated[str, Field(description="Name/ID of node to query (e.g. 'pve1', 'proxmox-node2')")]
        ) -> Any:
            return self._wrap_sync(server, "get_node_status", server.node_tools.get_node_status)(node)

        @server.mcp.tool(description=GET_STORAGE_DESC)
        def get_storage() -> Any:
            return self._wrap_sync(server, "get_storage", server.storage_tools.get_storage)()

        @server.mcp.tool(description=GET_CLUSTER_STATUS_DESC)
        def get_cluster_status() -> Any:
            return self._wrap_sync(server, "get_cluster_status", server.cluster_tools.get_cluster_status)()


class JobsToolsPlugin(RegistryPluginBase):
    def register(self, server: Any) -> None:
        @server.mcp.tool(description=LIST_JOBS_DESC)
        def list_jobs(
            status: Annotated[Optional[str], Field(description="Optional status filter", default=None)] = None,
            tool_name: Annotated[Optional[str], Field(description="Optional originating tool filter", default=None)] = None,
            limit: Annotated[int, Field(description="Maximum jobs to return", ge=1, le=500, default=100)] = 100,
        ) -> Any:
            return self._wrap_sync(server, "list_jobs", server.jobs_tools.list_jobs)(
                status=status,
                tool_name=tool_name,
                limit=limit,
            )

        @server.mcp.tool(description=GET_JOB_DESC)
        def get_job(
            job_id: Annotated[str, Field(description="Stable job identifier")],
            refresh: Annotated[bool, Field(description="Poll Proxmox before returning", default=False)] = False,
        ) -> Any:
            return self._wrap_sync(server, "get_job", server.jobs_tools.get_job)(
                job_id=job_id,
                refresh=refresh,
            )

        @server.mcp.tool(description=POLL_JOB_DESC)
        def poll_job(
            job_id: Annotated[str, Field(description="Stable job identifier")],
        ) -> Any:
            return self._wrap_sync(server, "poll_job", server.jobs_tools.poll_job)(job_id=job_id)

        @server.mcp.tool(description=CANCEL_JOB_DESC)
        def cancel_job(
            job_id: Annotated[str, Field(description="Stable job identifier")],
        ) -> Any:
            return self._wrap_sync(server, "cancel_job", server.jobs_tools.cancel_job)(job_id=job_id)

        @server.mcp.tool(description=RETRY_JOB_DESC)
        def retry_job(
            job_id: Annotated[str, Field(description="Stable job identifier")],
        ) -> Any:
            return self._wrap_sync(server, "retry_job", server.jobs_tools.retry_job)(job_id=job_id)


class VMToolsPlugin(RegistryPluginBase):
    def register(self, server: Any) -> None:
        @server.mcp.tool(description=GET_VMS_DESC)
        def get_vms() -> Any:
            return self._wrap_sync(server, "get_vms", server.vm_tools.get_vms)()

        @server.mcp.tool(description=CREATE_VM_DESC)
        def create_vm(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="New VM ID number (e.g. '200', '300')")],
            name: Annotated[str, Field(description="VM name (e.g. 'my-new-vm', 'web-server')")],
            cpus: Annotated[int, Field(description="Number of CPU cores (e.g. 1, 2, 4)", ge=1, le=32)],
            memory: Annotated[int, Field(description="Memory size in MB (e.g. 2048 for 2GB)", ge=512, le=131072)],
            disk_size: Annotated[int, Field(description="Disk size in GB (e.g. 10, 20, 50)", ge=5, le=1000)],
            storage: Annotated[Optional[str], Field(description="Storage name (optional, will auto-detect)", default=None)] = None,
            ostype: Annotated[Optional[str], Field(description="OS type (optional, default: 'l26' for Linux)", default=None)] = None,
            network_bridge: Annotated[Optional[str], Field(description="Network bridge name (optional, default: 'vmbr0')", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "create_vm", server.vm_tools.create_vm)(
                node,
                vmid,
                name,
                cpus,
                memory,
                disk_size,
                storage,
                ostype,
                network_bridge,
            )

        @server.mcp.tool(description=EXECUTE_VM_COMMAND_DESC)
        async def execute_vm_command(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve1', 'proxmox-node2')")],
            vmid: Annotated[str, Field(description="VM ID number (e.g. '100', '101')")],
            command: Annotated[str, Field(description="Shell command to run (e.g. 'uname -a', 'systemctl status nginx')")],
            approval_token: Annotated[Optional[str], Field(description="Optional approval token if command policy requires it", default=None)] = None,
        ) -> Any:
            return await self._wrap_async(server, "execute_vm_command", server.vm_tools.execute_command)(
                node,
                vmid,
                command,
                approval_token,
            )

        @server.mcp.tool(description=START_VM_DESC)
        def start_vm(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="VM ID number (e.g. '101')")],
        ) -> Any:
            return self._wrap_sync(server, "start_vm", server.vm_tools.start_vm)(node, vmid)

        @server.mcp.tool(description=STOP_VM_DESC)
        def stop_vm(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="VM ID number (e.g. '101')")],
        ) -> Any:
            return self._wrap_sync(server, "stop_vm", server.vm_tools.stop_vm)(node, vmid)

        @server.mcp.tool(description=SHUTDOWN_VM_DESC)
        def shutdown_vm(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="VM ID number (e.g. '101')")],
        ) -> Any:
            return self._wrap_sync(server, "shutdown_vm", server.vm_tools.shutdown_vm)(node, vmid)

        @server.mcp.tool(description=RESET_VM_DESC)
        def reset_vm(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="VM ID number (e.g. '101')")],
        ) -> Any:
            return self._wrap_sync(server, "reset_vm", server.vm_tools.reset_vm)(node, vmid)

        @server.mcp.tool(description=DELETE_VM_DESC)
        def delete_vm(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="VM ID number (e.g. '998')")],
            force: Annotated[bool, Field(description="Force deletion even if VM is running", default=False)] = False,
            approval_token: Annotated[Optional[str], Field(description="Optional approval token for high-risk operations", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "delete_vm", server.vm_tools.delete_vm, high_risk=True)(
                node,
                vmid,
                force,
                approval_token=approval_token,
            )


class ContainerToolsPlugin(RegistryPluginBase):
    def register(self, server: Any) -> None:
        @server.mcp.tool(description=GET_CONTAINERS_DESC)
        def get_containers(
            payload: GetContainersPayload = Body(..., embed=True, description="Container query options")
        ) -> Any:
            return self._wrap_sync(server, "get_containers", server.container_tools.get_containers)(
                node=payload.node,
                include_stats=payload.include_stats,
                include_raw=payload.include_raw,
                format_style=payload.format_style,
            )

        @server.mcp.tool(description=START_CONTAINER_DESC)
        def start_container(
            selector: Annotated[str, Field(description="CT selector: '123' | 'pve1:123' | 'pve1/name' | 'name' | comma list")],
            format_style: Annotated[str, Field(description="'pretty' or 'json'", pattern="^(pretty|json)$")] = "pretty",
        ) -> Any:
            return self._wrap_sync(server, "start_container", server.container_tools.start_container)(
                selector=selector,
                format_style=format_style,
            )

        @server.mcp.tool(description=STOP_CONTAINER_DESC)
        def stop_container(
            selector: Annotated[str, Field(description="CT selector (see start_container)")],
            graceful: Annotated[bool, Field(description="Graceful shutdown (True) or forced stop (False)", default=True)] = True,
            timeout_seconds: Annotated[int, Field(description="Timeout for stop/shutdown", ge=1, le=600)] = 10,
            format_style: Annotated[Literal["pretty", "json"], Field(description="Output format")] = "pretty",
        ) -> Any:
            return self._wrap_sync(server, "stop_container", server.container_tools.stop_container)(
                selector=selector,
                graceful=graceful,
                timeout_seconds=timeout_seconds,
                format_style=format_style,
            )

        @server.mcp.tool(description=RESTART_CONTAINER_DESC)
        def restart_container(
            selector: Annotated[str, Field(description="CT selector (see start_container)")],
            timeout_seconds: Annotated[int, Field(description="Timeout for reboot", ge=1, le=600)] = 10,
            format_style: Annotated[str, Field(description="'pretty' or 'json'", pattern="^(pretty|json)$")] = "pretty",
        ) -> Any:
            return self._wrap_sync(server, "restart_container", server.container_tools.restart_container)(
                selector=selector,
                timeout_seconds=timeout_seconds,
                format_style=format_style,
            )

        @server.mcp.tool(description=UPDATE_CONTAINER_RESOURCES_DESC)
        def update_container_resources(
            selector: Annotated[str, Field(description="CT selector (see start_container)")],
            cores: Annotated[Optional[int], Field(description="New CPU core count", ge=1)] = None,
            memory: Annotated[Optional[int], Field(description="New memory limit in MiB", ge=16)] = None,
            swap: Annotated[Optional[int], Field(description="New swap limit in MiB", ge=0)] = None,
            disk_gb: Annotated[Optional[int], Field(description="Additional disk size in GiB", ge=1)] = None,
            disk: Annotated[str, Field(description="Disk to resize", default="rootfs")] = "rootfs",
            format_style: Annotated[Literal["pretty", "json"], Field(description="Output format")] = "pretty",
        ) -> Any:
            return self._wrap_sync(server, "update_container_resources", server.container_tools.update_container_resources)(
                selector=selector,
                cores=cores,
                memory=memory,
                swap=swap,
                disk_gb=disk_gb,
                disk=disk,
                format_style=format_style,
            )

        @server.mcp.tool(description=CREATE_CONTAINER_DESC)
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
            onboot: Annotated[bool, Field(description="Start container automatically when node boots", default=False)] = False,
            nesting: Annotated[bool, Field(description="Enable LXC nesting (features: nesting=1)", default=False)] = False,
            unprivileged: Annotated[bool, Field(description="Create unprivileged container", default=True)] = True,
        ) -> Any:
            return self._wrap_sync(server, "create_container", server.container_tools.create_container)(
                node=node,
                vmid=vmid,
                ostemplate=ostemplate,
                hostname=hostname,
                cores=cores,
                memory=memory,
                swap=swap,
                disk_size=disk_size,
                storage=storage,
                password=password,
                ssh_public_keys=ssh_public_keys,
                network_bridge=network_bridge,
                start_after_create=start_after_create,
                onboot=onboot,
                nesting=nesting,
                unprivileged=unprivileged,
            )

        @server.mcp.tool(description=DELETE_CONTAINER_DESC)
        def delete_container(
            selector: Annotated[str, Field(description="CT selector: '123' | 'pve1:123' | 'pve1/name' | 'name' | comma list")],
            force: Annotated[bool, Field(description="Force deletion even if running", default=False)] = False,
            format_style: Annotated[Literal["pretty", "json"], Field(description="Output format")] = "pretty",
            approval_token: Annotated[Optional[str], Field(description="Optional approval token for high-risk operations", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "delete_container", server.container_tools.delete_container, high_risk=True)(
                selector=selector,
                force=force,
                format_style=format_style,
                approval_token=approval_token,
            )

        if server.config.ssh is not None:
            server.logger.info(
                "Container command execution enabled (SSH configured for user '%s')",
                server.config.ssh.user,
            )

            @server.mcp.tool(description=EXECUTE_CONTAINER_COMMAND_DESC)
            def execute_container_command(
                selector: Annotated[str, Field(description="Container selector: '123', 'pve1:123', 'pve1/name', or 'name'")],
                command: Annotated[str, Field(description="Shell command to run (e.g. 'uname -a', 'df -h')")],
                approval_token: Annotated[Optional[str], Field(description="Optional approval token if command policy requires it", default=None)] = None,
            ) -> Any:
                return self._wrap_sync(server, "execute_container_command", server.container_tools.execute_command)(
                    selector=selector,
                    command=command,
                    approval_token=approval_token,
                )

            @server.mcp.tool(description=UPDATE_CONTAINER_SSH_KEYS_DESC)
            def update_container_ssh_keys(
                node: Annotated[str, Field(description="Proxmox node name (e.g. 'pve')")],
                vmid: Annotated[str, Field(description="Container ID (e.g. '101')")],
                public_keys: Annotated[str, Field(description="Newline-separated SSH public key(s) to authorize")],
                mode: Annotated[str, Field(description="'append' (default) or 'replace'", pattern="^(append|replace)$", default="append")] = "append",
            ) -> Any:
                return self._wrap_sync(server, "update_container_ssh_keys", server.container_tools.update_container_ssh_keys)(
                    node=node,
                    vmid=vmid,
                    public_keys=public_keys,
                    mode=mode,
                )
        else:
            server.logger.info("Container command execution disabled (no [ssh] section in config)")

        @server.mcp.tool(description=GET_CONTAINER_CONFIG_DESC)
        def get_container_config(
            node: Annotated[str, Field(description="Proxmox node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="Container ID (e.g. '101')")],
        ) -> Any:
            return self._wrap_sync(server, "get_container_config", server.container_tools.get_container_config)(
                node=node,
                vmid=vmid,
            )

        @server.mcp.tool(description=GET_CONTAINER_IP_DESC)
        def get_container_ip(
            node: Annotated[str, Field(description="Proxmox node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="Container ID (e.g. '101')")],
        ) -> Any:
            return self._wrap_sync(server, "get_container_ip", server.container_tools.get_container_ip)(
                node=node,
                vmid=vmid,
            )


class SnapshotToolsPlugin(RegistryPluginBase):
    def register(self, server: Any) -> None:
        @server.mcp.tool(description=LIST_SNAPSHOTS_DESC)
        def list_snapshots(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="VM or container ID (e.g. '100')")],
            vm_type: Annotated[str, Field(description="Type: 'qemu' for VMs, 'lxc' for containers", default="qemu")] = "qemu",
        ) -> Any:
            return self._wrap_sync(server, "list_snapshots", server.snapshot_tools.list_snapshots)(
                node=node,
                vmid=vmid,
                vm_type=vm_type,
            )

        @server.mcp.tool(description=CREATE_SNAPSHOT_DESC)
        def create_snapshot(
            node: Annotated[str, Field(description="Host node name")],
            vmid: Annotated[str, Field(description="VM or container ID")],
            snapname: Annotated[str, Field(description="Snapshot name (no spaces)")],
            description: Annotated[Optional[str], Field(description="Optional description", default=None)] = None,
            vmstate: Annotated[bool, Field(description="Include memory state (VMs only)", default=False)] = False,
            vm_type: Annotated[str, Field(description="Type: 'qemu' or 'lxc'", default="qemu")] = "qemu",
        ) -> Any:
            return self._wrap_sync(server, "create_snapshot", server.snapshot_tools.create_snapshot)(
                node=node,
                vmid=vmid,
                snapname=snapname,
                description=description,
                vmstate=vmstate,
                vm_type=vm_type,
            )

        @server.mcp.tool(description=DELETE_SNAPSHOT_DESC)
        def delete_snapshot(
            node: Annotated[str, Field(description="Host node name")],
            vmid: Annotated[str, Field(description="VM or container ID")],
            snapname: Annotated[str, Field(description="Snapshot name to delete")],
            vm_type: Annotated[str, Field(description="Type: 'qemu' or 'lxc'", default="qemu")] = "qemu",
            approval_token: Annotated[Optional[str], Field(description="Optional approval token for high-risk operations", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "delete_snapshot", server.snapshot_tools.delete_snapshot, high_risk=True)(
                node=node,
                vmid=vmid,
                snapname=snapname,
                vm_type=vm_type,
                approval_token=approval_token,
            )

        @server.mcp.tool(description=ROLLBACK_SNAPSHOT_DESC)
        def rollback_snapshot(
            node: Annotated[str, Field(description="Host node name")],
            vmid: Annotated[str, Field(description="VM or container ID")],
            snapname: Annotated[str, Field(description="Snapshot name to restore")],
            vm_type: Annotated[str, Field(description="Type: 'qemu' or 'lxc'", default="qemu")] = "qemu",
            approval_token: Annotated[Optional[str], Field(description="Optional approval token for high-risk operations", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "rollback_snapshot", server.snapshot_tools.rollback_snapshot, high_risk=True)(
                node=node,
                vmid=vmid,
                snapname=snapname,
                vm_type=vm_type,
                approval_token=approval_token,
            )


class ImageToolsPlugin(RegistryPluginBase):
    def register(self, server: Any) -> None:
        @server.mcp.tool(description=LIST_ISOS_DESC)
        def list_isos(
            node: Annotated[Optional[str], Field(description="Filter by node (optional)", default=None)] = None,
            storage: Annotated[Optional[str], Field(description="Filter by storage pool (optional)", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "list_isos", server.iso_tools.list_isos)(node=node, storage=storage)

        @server.mcp.tool(description=LIST_TEMPLATES_DESC)
        def list_templates(
            node: Annotated[Optional[str], Field(description="Filter by node (optional)", default=None)] = None,
            storage: Annotated[Optional[str], Field(description="Filter by storage pool (optional)", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "list_templates", server.iso_tools.list_templates)(node=node, storage=storage)

        @server.mcp.tool(description=DOWNLOAD_ISO_DESC)
        def download_iso(
            node: Annotated[str, Field(description="Target node name")],
            storage: Annotated[str, Field(description="Target storage pool")],
            url: Annotated[str, Field(description="URL to download from")],
            filename: Annotated[str, Field(description="Target filename (e.g. 'ubuntu-22.04.iso')")],
            checksum: Annotated[Optional[str], Field(description="Optional checksum", default=None)] = None,
            checksum_algorithm: Annotated[str, Field(description="Algorithm: sha256, sha512, md5", default="sha256")] = "sha256",
        ) -> Any:
            return self._wrap_sync(server, "download_iso", server.iso_tools.download_iso)(
                node=node,
                storage=storage,
                url=url,
                filename=filename,
                checksum=checksum,
                checksum_algorithm=checksum_algorithm,
            )

        @server.mcp.tool(description=DELETE_ISO_DESC)
        def delete_iso(
            node: Annotated[str, Field(description="Node name")],
            storage: Annotated[str, Field(description="Storage pool name")],
            filename: Annotated[str, Field(description="ISO/template filename to delete")],
            approval_token: Annotated[Optional[str], Field(description="Optional approval token for high-risk operations", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "delete_iso", server.iso_tools.delete_iso, high_risk=True)(
                node=node,
                storage=storage,
                filename=filename,
                approval_token=approval_token,
            )


class BackupToolsPlugin(RegistryPluginBase):
    def register(self, server: Any) -> None:
        @server.mcp.tool(description=LIST_BACKUPS_DESC)
        def list_backups(
            node: Annotated[Optional[str], Field(description="Filter by node (optional)", default=None)] = None,
            storage: Annotated[Optional[str], Field(description="Filter by storage pool (optional)", default=None)] = None,
            vmid: Annotated[Optional[str], Field(description="Filter by VM/container ID (optional)", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "list_backups", server.backup_tools.list_backups)(
                node=node,
                storage=storage,
                vmid=vmid,
            )

        @server.mcp.tool(description=CREATE_BACKUP_DESC)
        def create_backup(
            node: Annotated[str, Field(description="Node where VM/container runs")],
            vmid: Annotated[str, Field(description="VM or container ID to backup")],
            storage: Annotated[str, Field(description="Target backup storage")],
            compress: Annotated[str, Field(description="Compression: 0, gzip, lz4, zstd", default="zstd")] = "zstd",
            mode: Annotated[str, Field(description="Mode: snapshot, suspend, stop", default="snapshot")] = "snapshot",
            notes: Annotated[Optional[str], Field(description="Optional notes", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "create_backup", server.backup_tools.create_backup)(
                node=node,
                vmid=vmid,
                storage=storage,
                compress=compress,
                mode=mode,
                notes=notes,
            )

        @server.mcp.tool(description=RESTORE_BACKUP_DESC)
        def restore_backup(
            node: Annotated[str, Field(description="Target node for restore")],
            archive: Annotated[str, Field(description="Backup volume ID from list_backups")],
            vmid: Annotated[str, Field(description="New VM/container ID")],
            storage: Annotated[Optional[str], Field(description="Target storage (optional)", default=None)] = None,
            unique: Annotated[bool, Field(description="Generate unique MAC addresses", default=True)] = True,
            approval_token: Annotated[Optional[str], Field(description="Optional approval token for high-risk operations", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "restore_backup", server.backup_tools.restore_backup, high_risk=True)(
                node=node,
                archive=archive,
                vmid=vmid,
                storage=storage,
                unique=unique,
                approval_token=approval_token,
            )

        @server.mcp.tool(description=DELETE_BACKUP_DESC)
        def delete_backup(
            node: Annotated[str, Field(description="Node name")],
            storage: Annotated[str, Field(description="Storage pool name")],
            volid: Annotated[str, Field(description="Backup volume ID to delete")],
            approval_token: Annotated[Optional[str], Field(description="Optional approval token for high-risk operations", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "delete_backup", server.backup_tools.delete_backup, high_risk=True)(
                node=node,
                storage=storage,
                volid=volid,
                approval_token=approval_token,
            )
