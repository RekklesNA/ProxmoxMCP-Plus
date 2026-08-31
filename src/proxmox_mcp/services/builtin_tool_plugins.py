"""Built-in MCP tool registration plugins."""

from __future__ import annotations

import time
from typing import Annotated, Any, Awaitable, Callable, Literal, Optional

from pydantic import BaseModel, Field

from proxmox_mcp.tools.definitions import (
    CANCEL_JOB_DESC,
    CLONE_VM_DESC,
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
    GET_CLUSTER_LOG_DESC,
    GET_CLUSTER_STATUS_DESC,
    GET_CONTAINER_CONFIG_DESC,
    GET_CONTAINER_IP_DESC,
    GET_CONTAINERS_DESC,
    GET_GUEST_FIREWALL_LOG_DESC,
    GET_NODE_FIREWALL_LOG_DESC,
    GET_NODES_DESC,
    GET_NODE_STATUS_DESC,
    GET_NODE_SYSLOG_DESC,
    GET_STORAGE_DESC,
    GET_TASK_LOG_DESC,
    GET_VMS_DESC,
    GET_VM_CONFIG_DESC,
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
    SET_CONTAINER_DESCRIPTION_DESC,
    SET_VM_DESCRIPTION_DESC,
    SHUTDOWN_VM_DESC,
    START_CONTAINER_DESC,
    START_VM_DESC,
    STOP_CONTAINER_DESC,
    STOP_VM_DESC,
    UPDATE_CONTAINER_RESOURCES_DESC,
    UPDATE_CONTAINER_SSH_KEYS_DESC,
)
from proxmox_mcp.services.tool_registry import ToolRegistryPlugin


def _log_safe(value: object, max_length: int = 200) -> str:
    text = str(value).replace("\r", "").replace("\n", "")
    return text[:max_length]


_READ_ONLY_TOOLS = {
    "list_targets", "get_nodes", "get_node_status", "get_storage", "get_cluster_status",
    "list_jobs", "get_job", "poll_job", "get_vms", "get_vm_config", "get_containers",
    "get_container_config", "get_container_ip", "list_snapshots", "list_isos", "list_templates",
    "list_backups", "get_node_syslog", "get_task_log", "get_cluster_log", "get_node_firewall_log",
    "get_guest_firewall_log",
}


class GetContainersPayload(BaseModel):
    node: Optional[str] = Field(None, description="Optional node name (e.g. 'pve1')")
    include_stats: bool = Field(False, description="Fetch per-container live stats and fallbacks")
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
        resolved_target: Any,
    ) -> None:
        if not high_risk:
            return
        policy = server.target_command_policies[resolved_target.name]
        decision = policy.evaluate_operation(
            tool_name,
            approval_token=approval_token,
        )
        if decision.code == "OP_POLICY_AUDIT_ALLOW":
            server.logger.warning("High-risk tool invoked in audit-only mode: %s", _log_safe(tool_name))
        if not decision.allowed:
            raise ValueError(decision.message)

    def _enforce_job_retry_policy(
        self,
        server: Any,
        job_id: str,
        approval_token: str | None,
        *,
        resolved_target: Any,
    ) -> None:
        # Use target-isolated job store; provably same target as readonly/policy check.
        job_store = server.target_job_stores[resolved_target.name]
        job = job_store.get_job(job_id)
        operation_name = str(job.get("tool_name") or "")
        policy = server.target_command_policies[resolved_target.name]
        decision = policy.evaluate_operation(
            operation_name,
            approval_token=approval_token,
        )
        if decision.code == "OP_POLICY_AUDIT_ALLOW":
            safe_job_id = _log_safe(job_id)
            safe_operation_name = _log_safe(operation_name)
            server.logger.warning(
                "Retrying high-risk job in audit-only mode: %s (%s)",
                safe_job_id,
                safe_operation_name,
            )
        if not decision.allowed:
            raise ValueError(decision.message)

    def _wrap_sync(
        self,
        server: Any,
        tool_name: str,
        handler_factory: Callable[[Any], Callable[..., Any]],
        *,
        high_risk: bool = False,
    ) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            success = False
            target = kwargs.pop("target", None)
            approval_token = kwargs.get("approval_token")
            resolved_target = None
            try:
                resolved_target = server.target_registry.resolve(target)
                if resolved_target.readonly and tool_name not in _READ_ONLY_TOOLS:
                    raise ValueError(
                        f"Target '{resolved_target.name}' is configured read-only; "
                        f"tool '{tool_name}' is not permitted"
                    )
                self._enforce_operation_policy(
                    server,
                    tool_name,
                    approval_token if isinstance(approval_token, str) else None,
                    high_risk=high_risk,
                    resolved_target=resolved_target,
                )
                if tool_name == "retry_job":
                    # Enforce retry policy using SAME resolved target before dispatch.
                    job_id = kwargs.get("job_id")
                    if job_id is None and args:
                        job_id = args[0]
                    self._enforce_job_retry_policy(
                        server,
                        str(job_id) if job_id is not None else "",
                        approval_token if isinstance(approval_token, str) else None,
                        resolved_target=resolved_target,
                    )
                toolset = server.target_tools(resolved_target.name)
                handler = handler_factory(toolset)
                if tool_name == "retry_job":
                    kwargs.pop("approval_token", None)
                result = handler(*args, **kwargs)
                success = True
                return result
            finally:
                latency_ms = (time.perf_counter() - start) * 1000.0
                server.metrics.observe(tool_name, latency_ms=latency_ms, success=success, target=resolved_target.name if resolved_target is not None else "unresolved")

        return wrapped

    def _wrap_async(
        self,
        server: Any,
        tool_name: str,
        handler_factory: Callable[[Any], Callable[..., Awaitable[Any]]],
        *,
        high_risk: bool = False,
    ) -> Callable[..., Awaitable[Any]]:
        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            success = False
            target = kwargs.pop("target", None)
            approval_token = kwargs.get("approval_token")
            resolved_target = None
            try:
                resolved_target = server.target_registry.resolve(target)
                if resolved_target.readonly and tool_name not in _READ_ONLY_TOOLS:
                    raise ValueError(
                        f"Target '{resolved_target.name}' is configured read-only; "
                        f"tool '{tool_name}' is not permitted"
                    )
                self._enforce_operation_policy(
                    server,
                    tool_name,
                    approval_token if isinstance(approval_token, str) else None,
                    high_risk=high_risk,
                    resolved_target=resolved_target,
                )
                toolset = server.target_tools(resolved_target.name)
                handler = handler_factory(toolset)
                result = await handler(*args, **kwargs)
                success = True
                return result
            finally:
                latency_ms = (time.perf_counter() - start) * 1000.0
                server.metrics.observe(tool_name, latency_ms=latency_ms, success=success, target=resolved_target.name if resolved_target is not None else "unresolved")

        return wrapped


class CoreToolsPlugin(RegistryPluginBase):
    def register(self, server: Any) -> None:
        @server.mcp.tool(
            description="List configured Proxmox targets without exposing credentials. "
            "A target name is required for other tools when multiple targets are configured."
        )
        def list_targets() -> Any:
            start = time.perf_counter()
            try:
                def discover(target: Any) -> dict[str, Any]:
                    nodes = server.proxmox_managers[target.name].get_api().nodes.get()
                    return {
                        "reachable": True,
                        "nodes": [
                            str(node["node"])
                            for node in nodes
                            if isinstance(node, dict) and "node" in node
                        ],
                    }

                result = server.target_registry.describe(discover=discover)
                server.metrics.observe("list_targets", (time.perf_counter() - start) * 1000.0, True, target="all")
                return result
            except Exception:
                server.metrics.observe("list_targets", (time.perf_counter() - start) * 1000.0, False, target="all")
                raise

        @server.mcp.tool(description=GET_NODES_DESC)
        def get_nodes(
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "get_nodes", lambda ts: ts.node_tools.get_nodes)(target=target)

        @server.mcp.tool(description=GET_NODE_STATUS_DESC)
        def get_node_status(
            node: Annotated[str, Field(description="Name/ID of node to query (e.g. 'pve1', 'proxmox-node2')")],
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "get_node_status", lambda ts: ts.node_tools.get_node_status)(
                node, target=target
            )

        @server.mcp.tool(description=GET_STORAGE_DESC)
        def get_storage(
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "get_storage", lambda ts: ts.storage_tools.get_storage)(target=target)

        @server.mcp.tool(description=GET_CLUSTER_STATUS_DESC)
        def get_cluster_status(
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "get_cluster_status", lambda ts: ts.cluster_tools.get_cluster_status)(
                target=target
            )


class JobsToolsPlugin(RegistryPluginBase):
    def register(self, server: Any) -> None:
        @server.mcp.tool(description=LIST_JOBS_DESC)
        def list_jobs(
            status: Annotated[Optional[str], Field(description="Optional status filter", default=None)] = None,
            tool_name: Annotated[Optional[str], Field(description="Optional originating tool filter", default=None)] = None,
            limit: Annotated[int, Field(description="Maximum jobs to return", ge=1, le=500, default=100)] = 100,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "list_jobs", lambda ts: ts.jobs_tools.list_jobs)(
                status=status,
                tool_name=tool_name,
                limit=limit,
                target=target,
            )

        @server.mcp.tool(description=GET_JOB_DESC)
        def get_job(
            job_id: Annotated[str, Field(description="Stable job identifier")],
            refresh: Annotated[bool, Field(description="Poll Proxmox before returning", default=False)] = False,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "get_job", lambda ts: ts.jobs_tools.get_job)(
                job_id=job_id,
                refresh=refresh,
                target=target,
            )

        @server.mcp.tool(description=POLL_JOB_DESC)
        def poll_job(
            job_id: Annotated[str, Field(description="Stable job identifier")],
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "poll_job", lambda ts: ts.jobs_tools.poll_job)(job_id=job_id, target=target)

        @server.mcp.tool(description=CANCEL_JOB_DESC)
        def cancel_job(
            job_id: Annotated[str, Field(description="Stable job identifier")],
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "cancel_job", lambda ts: ts.jobs_tools.cancel_job)(job_id=job_id, target=target)

        @server.mcp.tool(description=RETRY_JOB_DESC)
        def retry_job(
            job_id: Annotated[str, Field(description="Stable job identifier")],
            approval_token: Annotated[Optional[str], Field(description="Optional approval token for high-risk job retries", default=None)] = None,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "retry_job", lambda ts: ts.jobs_tools.retry_job)(
                job_id=job_id, approval_token=approval_token, target=target
            )


class VMToolsPlugin(RegistryPluginBase):
    def register(self, server: Any) -> None:
        @server.mcp.tool(description=GET_VMS_DESC)
        def get_vms(
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None
        ) -> Any:
            return self._wrap_sync(server, "get_vms", lambda ts: ts.vm_tools.get_vms)(target=target)

        @server.mcp.tool(description=GET_VM_CONFIG_DESC)
        def get_vm_config(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="VM ID number (e.g. '100')")],
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "get_vm_config", lambda ts: ts.vm_tools.get_vm_config)(
                node=node,
                vmid=vmid,
                target=target,
            )

        @server.mcp.tool(description=SET_VM_DESCRIPTION_DESC)
        def set_vm_description(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="VM ID number (e.g. '100')")],
            description: Annotated[str, Field(description="New notes text (replaces any existing notes)")],
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "set_vm_description", lambda ts: ts.vm_tools.set_vm_description)(
                node=node,
                vmid=vmid,
                description=description,
                target=target,
            )

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
            pool: Annotated[Optional[str], Field(description="Target Proxmox resource pool (optional)", default=None)] = None,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "create_vm", lambda ts: ts.vm_tools.create_vm)(
                node,
                vmid,
                name,
                cpus,
                memory,
                disk_size,
                storage,
                ostype,
                network_bridge,
                pool,
                target=target,
            )

        @server.mcp.tool(description=CLONE_VM_DESC)
        def clone_vm(
            node: Annotated[str, Field(description="Source host node name (e.g. 'pve')")],
            source_vmid: Annotated[str, Field(description="Source VM ID number (e.g. '9000')", pattern=r"^\d+$")],
            target_vmid: Annotated[str, Field(description="New VM ID number for the clone (e.g. '201')", pattern=r"^\d+$")],
            name: Annotated[Optional[str], Field(description="New VM name (optional)", default=None)] = None,
            target_node: Annotated[Optional[str], Field(description="Destination node name (optional)", default=None)] = None,
            full: Annotated[bool, Field(description="Create full clone (True) or linked clone (False)", default=True)] = True,
            storage: Annotated[Optional[str], Field(description="Target storage (optional)", default=None)] = None,
            pool: Annotated[Optional[str], Field(description="Target resource pool (optional)", default=None)] = None,
            snapname: Annotated[Optional[str], Field(description="Snapshot name to clone from (optional)", default=None)] = None,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "clone_vm", lambda ts: ts.vm_tools.clone_vm)(
                node=node,
                source_vmid=source_vmid,
                target_vmid=target_vmid,
                name=name,
                target_node=target_node,
                full=full,
                storage=storage,
                pool=pool,
                snapname=snapname,
                target=target,
            )

        @server.mcp.tool(description=EXECUTE_VM_COMMAND_DESC)
        async def execute_vm_command(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve1', 'proxmox-node2')")],
            vmid: Annotated[str, Field(description="VM ID number (e.g. '100', '101')")],
            command: Annotated[str, Field(description="Shell command to run (e.g. 'uname -a', 'systemctl status nginx')")],
            approval_token: Annotated[Optional[str], Field(description="Optional approval token if command policy requires it", default=None)] = None,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return await self._wrap_async(server, "execute_vm_command", lambda ts: ts.vm_tools.execute_command)(
                node,
                vmid,
                command,
                approval_token,
                target=target,
            )

        @server.mcp.tool(description=START_VM_DESC)
        def start_vm(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="VM ID number (e.g. '101')")],
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "start_vm", lambda ts: ts.vm_tools.start_vm)(node, vmid, target=target)

        @server.mcp.tool(description=STOP_VM_DESC)
        def stop_vm(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="VM ID number (e.g. '101')")],
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "stop_vm", lambda ts: ts.vm_tools.stop_vm)(node, vmid, target=target)

        @server.mcp.tool(description=SHUTDOWN_VM_DESC)
        def shutdown_vm(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="VM ID number (e.g. '101')")],
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "shutdown_vm", lambda ts: ts.vm_tools.shutdown_vm)(node, vmid, target=target)

        @server.mcp.tool(description=RESET_VM_DESC)
        def reset_vm(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="VM ID number (e.g. '101')")],
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "reset_vm", lambda ts: ts.vm_tools.reset_vm)(node, vmid, target=target)

        @server.mcp.tool(description=DELETE_VM_DESC)
        def delete_vm(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="VM ID number (e.g. '998')")],
            force: Annotated[bool, Field(description="Force deletion even if VM is running", default=False)] = False,
            approval_token: Annotated[Optional[str], Field(description="Optional approval token for high-risk operations", default=None)] = None,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "delete_vm", lambda ts: ts.vm_tools.delete_vm, high_risk=True)(
                node,
                vmid,
                force,
                approval_token=approval_token,
                target=target,
            )


class ContainerToolsPlugin(RegistryPluginBase):
    def register(self, server: Any) -> None:
        @server.mcp.tool(description=GET_CONTAINERS_DESC)
        def get_containers(
            node: Annotated[Optional[str], Field(description="Optional node name (e.g. 'pve1')")] = None,
            include_stats: Annotated[bool, Field(description="Fetch per-container live stats and fallbacks")] = False,
            include_raw: Annotated[bool, Field(description="Include raw status/config")] = False,
            format_style: Annotated[Literal["pretty", "json"], Field(description="'pretty' or 'json'")] = "pretty",
            payload: Annotated[Optional[dict[str, Any]], Field(description="Legacy container query options")] = None,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            if payload is not None:
                legacy_payload = GetContainersPayload.model_validate(payload)
                if "node" in legacy_payload.model_fields_set:
                    node = legacy_payload.node
                if "include_stats" in legacy_payload.model_fields_set:
                    include_stats = legacy_payload.include_stats
                if "include_raw" in legacy_payload.model_fields_set:
                    include_raw = legacy_payload.include_raw
                if "format_style" in legacy_payload.model_fields_set:
                    format_style = legacy_payload.format_style

            return self._wrap_sync(server, "get_containers", lambda ts: ts.container_tools.get_containers)(
                node=node,
                include_stats=include_stats,
                include_raw=include_raw,
                format_style=format_style,
                target=target,
            )

        @server.mcp.tool(description=START_CONTAINER_DESC)
        def start_container(
            selector: Annotated[str, Field(description="CT selector: '123' | 'pve1:123' | 'pve1/name' | 'name' | comma list")],
            format_style: Annotated[str, Field(description="'pretty' or 'json'", pattern="^(pretty|json)$")] = "pretty",
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "start_container", lambda ts: ts.container_tools.start_container)(
                selector=selector,
                format_style=format_style,
                target=target,
            )

        @server.mcp.tool(description=STOP_CONTAINER_DESC)
        def stop_container(
            selector: Annotated[str, Field(description="CT selector (see start_container)")],
            graceful: Annotated[bool, Field(description="Graceful shutdown (True) or forced stop (False)", default=True)] = True,
            timeout_seconds: Annotated[int, Field(description="Timeout for stop/shutdown", ge=1, le=600)] = 10,
            format_style: Annotated[Literal["pretty", "json"], Field(description="Output format")] = "pretty",
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "stop_container", lambda ts: ts.container_tools.stop_container)(
                selector=selector,
                graceful=graceful,
                timeout_seconds=timeout_seconds,
                format_style=format_style,
                target=target,
            )

        @server.mcp.tool(description=RESTART_CONTAINER_DESC)
        def restart_container(
            selector: Annotated[str, Field(description="CT selector (see start_container)")],
            timeout_seconds: Annotated[int, Field(description="Timeout for reboot", ge=1, le=600)] = 10,
            format_style: Annotated[str, Field(description="'pretty' or 'json'", pattern="^(pretty|json)$")] = "pretty",
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "restart_container", lambda ts: ts.container_tools.restart_container)(
                selector=selector,
                timeout_seconds=timeout_seconds,
                format_style=format_style,
                target=target,
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
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "update_container_resources", lambda ts: ts.container_tools.update_container_resources)(
                selector=selector,
                cores=cores,
                memory=memory,
                swap=swap,
                disk_gb=disk_gb,
                disk=disk,
                format_style=format_style,
                target=target,
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
            pool: Annotated[Optional[str], Field(description="Target Proxmox resource pool (optional)", default=None)] = None,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "create_container", lambda ts: ts.container_tools.create_container)(
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
                pool=pool,
                target=target,
            )

        @server.mcp.tool(description=DELETE_CONTAINER_DESC)
        def delete_container(
            selector: Annotated[str, Field(description="CT selector: '123' | 'pve1:123' | 'pve1/name' | 'name' | comma list")],
            force: Annotated[bool, Field(description="Force deletion even if running", default=False)] = False,
            format_style: Annotated[Literal["pretty", "json"], Field(description="Output format")] = "pretty",
            approval_token: Annotated[Optional[str], Field(description="Optional approval token for high-risk operations", default=None)] = None,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "delete_container", lambda ts: ts.container_tools.delete_container, high_risk=True)(
                selector=selector,
                force=force,
                format_style=format_style,
                approval_token=approval_token,
                target=target,
            )

        target_registry = getattr(server, "target_registry", None)
        target_names = target_registry.names if target_registry is not None else ("default",)
        has_target_ssh_names = tuple(
            name for name in target_names
            if target_registry is not None and server.target_registry.resolve(name).ssh is not None
        )
        has_target_ssh = bool(has_target_ssh_names) or (
            target_names == ("default",) and bool(server.config.ssh)
        )
        if has_target_ssh:
            configured_names = (
                ("default",) if server.config.ssh and target_names == ("default",)
                else has_target_ssh_names
            )
            server.logger.info(
                "Container command execution enabled (SSH configured for targets: %s)",
                ", ".join(configured_names),
            )

            @server.mcp.tool(description=EXECUTE_CONTAINER_COMMAND_DESC)
            def execute_container_command(
                selector: Annotated[str, Field(description="Container selector: '123', 'pve1:123', 'pve1/name', or 'name'")],
                command: Annotated[str, Field(description="Shell command to run (e.g. 'uname -a', 'df -h')")],
                approval_token: Annotated[Optional[str], Field(description="Optional approval token if command policy requires it", default=None)] = None,
                target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
            ) -> Any:
                return self._wrap_sync(server, "execute_container_command", lambda ts: ts.container_tools.execute_command)(
                    selector=selector,
                    command=command,
                    approval_token=approval_token,
                    target=target,
                )

            @server.mcp.tool(description=UPDATE_CONTAINER_SSH_KEYS_DESC)
            def update_container_ssh_keys(
                node: Annotated[str, Field(description="Proxmox node name (e.g. 'pve')")],
                vmid: Annotated[str, Field(description="Container ID (e.g. '101')")],
                public_keys: Annotated[str, Field(description="Newline-separated SSH public key(s) to authorize")],
                mode: Annotated[str, Field(description="'append' (default) or 'replace'", pattern="^(append|replace)$", default="append")] = "append",
                approval_token: Annotated[Optional[str], Field(description="Optional approval token for high-risk operations", default=None)] = None,
                target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
            ) -> Any:
                return self._wrap_sync(
                    server,
                    "update_container_ssh_keys",
                    lambda ts: ts.container_tools.update_container_ssh_keys,
                    high_risk=True,
                )(
                    node=node,
                    vmid=vmid,
                    public_keys=public_keys,
                    mode=mode,
                    approval_token=approval_token,
                    target=target,
                )
        else:
            server.logger.info("Container command execution disabled (no [ssh] section in config)")

        @server.mcp.tool(description=GET_CONTAINER_CONFIG_DESC)
        def get_container_config(
            node: Annotated[str, Field(description="Proxmox node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="Container ID (e.g. '101')")],
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "get_container_config", lambda ts: ts.container_tools.get_container_config)(
                node=node,
                vmid=vmid,
                target=target,
            )

        @server.mcp.tool(description=SET_CONTAINER_DESCRIPTION_DESC)
        def set_container_description(
            node: Annotated[str, Field(description="Proxmox node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="Container ID (e.g. '101')")],
            description: Annotated[str, Field(description="New notes text (replaces any existing notes)")],
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(
                server, "set_container_description", lambda ts: ts.container_tools.set_container_description
            )(
                node=node,
                vmid=vmid,
                description=description,
                target=target,
            )

        @server.mcp.tool(description=GET_CONTAINER_IP_DESC)
        def get_container_ip(
            node: Annotated[str, Field(description="Proxmox node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="Container ID (e.g. '101')")],
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "get_container_ip", lambda ts: ts.container_tools.get_container_ip)(
                node=node,
                vmid=vmid,
                target=target,
            )


class SnapshotToolsPlugin(RegistryPluginBase):
    def register(self, server: Any) -> None:
        @server.mcp.tool(description=LIST_SNAPSHOTS_DESC)
        def list_snapshots(
            node: Annotated[str, Field(description="Host node name (e.g. 'pve')")],
            vmid: Annotated[str, Field(description="VM or container ID (e.g. '100')")],
            vm_type: Annotated[str, Field(description="Type: 'qemu' for VMs, 'lxc' for containers", default="qemu")] = "qemu",
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "list_snapshots", lambda ts: ts.snapshot_tools.list_snapshots)(
                node=node,
                vmid=vmid,
                vm_type=vm_type,
                target=target,
            )

        @server.mcp.tool(description=CREATE_SNAPSHOT_DESC)
        def create_snapshot(
            node: Annotated[str, Field(description="Host node name")],
            vmid: Annotated[str, Field(description="VM or container ID")],
            snapname: Annotated[str, Field(description="Snapshot name (no spaces)")],
            description: Annotated[Optional[str], Field(description="Optional description", default=None)] = None,
            vmstate: Annotated[bool, Field(description="Include memory state (VMs only)", default=False)] = False,
            vm_type: Annotated[str, Field(description="Type: 'qemu' or 'lxc'", default="qemu")] = "qemu",
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "create_snapshot", lambda ts: ts.snapshot_tools.create_snapshot)(
                node=node,
                vmid=vmid,
                snapname=snapname,
                description=description,
                vmstate=vmstate,
                vm_type=vm_type,
                target=target,
            )

        @server.mcp.tool(description=DELETE_SNAPSHOT_DESC)
        def delete_snapshot(
            node: Annotated[str, Field(description="Host node name")],
            vmid: Annotated[str, Field(description="VM or container ID")],
            snapname: Annotated[str, Field(description="Snapshot name to delete")],
            vm_type: Annotated[str, Field(description="Type: 'qemu' or 'lxc'", default="qemu")] = "qemu",
            approval_token: Annotated[Optional[str], Field(description="Optional approval token for high-risk operations", default=None)] = None,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "delete_snapshot", lambda ts: ts.snapshot_tools.delete_snapshot, high_risk=True)(
                node=node,
                vmid=vmid,
                snapname=snapname,
                vm_type=vm_type,
                approval_token=approval_token,
                target=target,
            )

        @server.mcp.tool(description=ROLLBACK_SNAPSHOT_DESC)
        def rollback_snapshot(
            node: Annotated[str, Field(description="Host node name")],
            vmid: Annotated[str, Field(description="VM or container ID")],
            snapname: Annotated[str, Field(description="Snapshot name to restore")],
            vm_type: Annotated[str, Field(description="Type: 'qemu' or 'lxc'", default="qemu")] = "qemu",
            approval_token: Annotated[Optional[str], Field(description="Optional approval token for high-risk operations", default=None)] = None,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "rollback_snapshot", lambda ts: ts.snapshot_tools.rollback_snapshot, high_risk=True)(
                node=node,
                vmid=vmid,
                snapname=snapname,
                vm_type=vm_type,
                approval_token=approval_token,
                target=target,
            )


class ImageToolsPlugin(RegistryPluginBase):
    def register(self, server: Any) -> None:
        @server.mcp.tool(description=LIST_ISOS_DESC)
        def list_isos(
            node: Annotated[Optional[str], Field(description="Filter by node (optional)", default=None)] = None,
            storage: Annotated[Optional[str], Field(description="Filter by storage pool (optional)", default=None)] = None,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "list_isos", lambda ts: ts.iso_tools.list_isos)(node=node, storage=storage, target=target)

        @server.mcp.tool(description=LIST_TEMPLATES_DESC)
        def list_templates(
            node: Annotated[Optional[str], Field(description="Filter by node (optional)", default=None)] = None,
            storage: Annotated[Optional[str], Field(description="Filter by storage pool (optional)", default=None)] = None,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "list_templates", lambda ts: ts.iso_tools.list_templates)(
                node=node, storage=storage, target=target
            )

        @server.mcp.tool(description=DOWNLOAD_ISO_DESC)
        def download_iso(
            node: Annotated[str, Field(description="Target node name")],
            storage: Annotated[str, Field(description="Target storage pool")],
            url: Annotated[str, Field(description="URL to download from")],
            filename: Annotated[str, Field(description="Target filename (e.g. 'ubuntu-22.04.iso')")],
            checksum: Annotated[Optional[str], Field(description="Optional checksum", default=None)] = None,
            checksum_algorithm: Annotated[str, Field(description="Algorithm: sha256, sha512, md5", default="sha256")] = "sha256",
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "download_iso", lambda ts: ts.iso_tools.download_iso)(
                node=node,
                storage=storage,
                url=url,
                filename=filename,
                checksum=checksum,
                checksum_algorithm=checksum_algorithm,
                target=target,
            )

        @server.mcp.tool(description=DELETE_ISO_DESC)
        def delete_iso(
            node: Annotated[str, Field(description="Node name")],
            storage: Annotated[str, Field(description="Storage pool name")],
            filename: Annotated[str, Field(description="ISO/template filename to delete")],
            approval_token: Annotated[Optional[str], Field(description="Optional approval token for high-risk operations", default=None)] = None,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "delete_iso", lambda ts: ts.iso_tools.delete_iso, high_risk=True)(
                node=node,
                storage=storage,
                filename=filename,
                approval_token=approval_token,
                target=target,
            )


class BackupToolsPlugin(RegistryPluginBase):
    def register(self, server: Any) -> None:
        @server.mcp.tool(description=LIST_BACKUPS_DESC)
        def list_backups(
            node: Annotated[Optional[str], Field(description="Filter by node (optional)", default=None)] = None,
            storage: Annotated[Optional[str], Field(description="Filter by storage pool (optional)", default=None)] = None,
            vmid: Annotated[Optional[str], Field(description="Filter by VM/container ID (optional)", default=None)] = None,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "list_backups", lambda ts: ts.backup_tools.list_backups)(
                node=node,
                storage=storage,
                vmid=vmid,
                target=target,
            )

        @server.mcp.tool(description=CREATE_BACKUP_DESC)
        def create_backup(
            node: Annotated[str, Field(description="Node where VM/container runs")],
            vmid: Annotated[str, Field(description="VM or container ID to backup")],
            storage: Annotated[str, Field(description="Target backup storage")],
            compress: Annotated[str, Field(description="Compression: 0, gzip, lz4, zstd", default="zstd")] = "zstd",
            mode: Annotated[str, Field(description="Mode: snapshot, suspend, stop", default="snapshot")] = "snapshot",
            notes: Annotated[Optional[str], Field(description="Optional notes", default=None)] = None,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "create_backup", lambda ts: ts.backup_tools.create_backup)(
                node=node,
                vmid=vmid,
                storage=storage,
                compress=compress,
                mode=mode,
                notes=notes,
                target=target,
            )

        @server.mcp.tool(description=RESTORE_BACKUP_DESC)
        def restore_backup(
            node: Annotated[str, Field(description="Target node for restore")],
            archive: Annotated[str, Field(description="Backup volume ID from list_backups")],
            vmid: Annotated[str, Field(description="New VM/container ID")],
            storage: Annotated[Optional[str], Field(description="Target storage (optional)", default=None)] = None,
            unique: Annotated[bool, Field(description="Generate unique MAC addresses", default=True)] = True,
            approval_token: Annotated[Optional[str], Field(description="Optional approval token for high-risk operations", default=None)] = None,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "restore_backup", lambda ts: ts.backup_tools.restore_backup, high_risk=True)(
                node=node,
                archive=archive,
                vmid=vmid,
                storage=storage,
                unique=unique,
                approval_token=approval_token,
                target=target,
            )

        @server.mcp.tool(description=DELETE_BACKUP_DESC)
        def delete_backup(
            node: Annotated[str, Field(description="Node name")],
            storage: Annotated[str, Field(description="Storage pool name")],
            volid: Annotated[str, Field(description="Backup volume ID to delete")],
            approval_token: Annotated[Optional[str], Field(description="Optional approval token for high-risk operations", default=None)] = None,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "delete_backup", lambda ts: ts.backup_tools.delete_backup, high_risk=True)(
                node=node,
                storage=storage,
                volid=volid,
                approval_token=approval_token,
                target=target,
            )


class LogToolsPlugin(RegistryPluginBase):
    """Registers read-only log tools: node syslog, task log, cluster log,
    and node/guest firewall logs."""

    def register(self, server: Any) -> None:
        @server.mcp.tool(description=GET_NODE_SYSLOG_DESC)
        def get_node_syslog(
            node: Annotated[str, Field(description="Node name (e.g. 'pve', 'pve1')")],
            limit: Annotated[
                int,
                Field(description="Maximum number of log lines to return", ge=1, le=1000, default=100),
            ] = 100,
            start: Annotated[
                Optional[int],
                Field(description="Start line for pagination (0-based)", ge=0, default=None),
            ] = None,
            since: Annotated[
                Optional[str],
                Field(
                    description="Show entries from this date/time onward "
                    "(YYYY-MM-DD or YYYY-MM-DD HH:MM or YYYY-MM-DD HH:MM:SS)",
                    default=None,
                ),
            ] = None,
            until: Annotated[
                Optional[str],
                Field(
                    description="Show entries up to this date/time (same format as since)",
                    default=None,
                ),
            ] = None,
            service: Annotated[
                Optional[str],
                Field(description="Filter by service name (e.g. 'pvedaemon', 'pveproxy')", default=None),
            ] = None,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "get_node_syslog", lambda ts: ts.log_tools.get_node_syslog)(
                node=node, limit=limit, start=start, since=since, until=until, service=service, target=target
            )

        @server.mcp.tool(description=GET_TASK_LOG_DESC)
        def get_task_log(
            node: Annotated[str, Field(description="Node name that ran the task (e.g. 'pve')")],
            upid: Annotated[str, Field(description="Unique Process ID (UPID) of the task")],
            start: Annotated[
                Optional[int],
                Field(description="Start line for pagination (0-based)", ge=0, default=None),
            ] = None,
            limit: Annotated[
                int,
                Field(description="Maximum number of log lines to return", ge=1, le=500, default=50),
            ] = 50,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "get_task_log", lambda ts: ts.log_tools.get_task_log)(
                node=node, upid=upid, start=start, limit=limit, target=target
            )

        @server.mcp.tool(description=GET_CLUSTER_LOG_DESC)
        def get_cluster_log(
            max_entries: Annotated[
                int,
                Field(description="Maximum number of cluster log entries to return", ge=1, le=1000, default=50),
            ] = 50,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(server, "get_cluster_log", lambda ts: ts.log_tools.get_cluster_log)(
                max_entries=max_entries, target=target
            )

        @server.mcp.tool(description=GET_NODE_FIREWALL_LOG_DESC)
        def get_node_firewall_log(
            node: Annotated[str, Field(description="Node name (e.g. 'pve', 'pve1')")],
            limit: Annotated[
                int,
                Field(description="Maximum number of log lines to return", ge=1, le=1000, default=100),
            ] = 100,
            start: Annotated[
                Optional[int],
                Field(description="Start line for pagination (0-based)", ge=0, default=None),
            ] = None,
            since: Annotated[
                Optional[int],
                Field(description="Show entries since this UNIX epoch timestamp", default=None),
            ] = None,
            until: Annotated[
                Optional[int],
                Field(description="Show entries until this UNIX epoch timestamp", default=None),
            ] = None,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(
                server, "get_node_firewall_log", lambda ts: ts.log_tools.get_node_firewall_log
            )(node=node, limit=limit, start=start, since=since, until=until, target=target)

        @server.mcp.tool(description=GET_GUEST_FIREWALL_LOG_DESC)
        def get_guest_firewall_log(
            node: Annotated[str, Field(description="Node hosting the guest (e.g. 'pve')")],
            vmid: Annotated[int, Field(description="VM/container ID (e.g. 100)", ge=100)],
            vm_type: Annotated[
                Literal["qemu", "lxc"],
                Field(description="Guest type: 'qemu' (VM, default) or 'lxc' (container)", default="qemu"),
            ] = "qemu",
            limit: Annotated[
                int,
                Field(description="Maximum number of log lines to return", ge=1, le=1000, default=100),
            ] = 100,
            start: Annotated[
                Optional[int],
                Field(description="Start line for pagination (0-based)", ge=0, default=None),
            ] = None,
            since: Annotated[
                Optional[int],
                Field(description="Show entries since this UNIX epoch timestamp", default=None),
            ] = None,
            until: Annotated[
                Optional[int],
                Field(description="Show entries until this UNIX epoch timestamp", default=None),
            ] = None,
            target: Annotated[Optional[str], Field(description="Configured target name; required when multiple targets exist", default=None)] = None,
        ) -> Any:
            return self._wrap_sync(
                server, "get_guest_firewall_log", lambda ts: ts.log_tools.get_guest_firewall_log
            )(
                node=node,
                vmid=vmid,
                vm_type=vm_type,
                limit=limit,
                start=start,
                since=since,
                until=until,
                target=target,
            )
