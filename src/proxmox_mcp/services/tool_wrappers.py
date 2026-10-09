"""Target-aware tool execution, authorization and outcome metrics."""
from __future__ import annotations
import time
from typing import Any, Awaitable, Callable
from proxmox_mcp.services.tool_registry import ToolRegistryPlugin, approval_context
from proxmox_mcp.models.tooling import result_succeeded, result_status
from proxmox_mcp.security.access import authorize_client, client_principal

def _log_safe(value: object, max_length: int = 200) -> str:
    return str(value).replace("\r", "").replace("\n", "")[:max_length]

_READ_ONLY_TOOLS = {
    "list_bridges",
    "list_targets", "get_nodes", "get_node_status", "get_storage", "get_cluster_status",
    "list_jobs", "get_job", "poll_job", "get_vms", "get_vm_config", "get_vm_ip_addresses",
    "get_next_vmid", "get_containers",
    "get_container_config", "get_container_ip", "list_snapshots", "list_isos", "list_templates",
    "list_backups", "get_node_syslog", "get_task_log", "get_cluster_log", "get_node_firewall_log",
    "get_guest_firewall_log",
}


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
        authorize_client(server.config.mcp.client_permissions, client_principal(server.config.mcp.transport), operation_name, resolved_target.name)
        if not server.tool_exposure_policy.allows(operation_name):
            raise ValueError("The original operation is disabled by the current tool exposure policy")
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
            outcome = "error"
            target = kwargs.pop("target", None)
            approval_token = kwargs.get("approval_token") or approval_context.get()
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
                if tool_name in {"retry_job", "reconcile_job"}:
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
                if tool_name in {"retry_job", "reconcile_job"}:
                    kwargs.pop("approval_token", None)
                result = handler(*args, **kwargs)
                success = result_succeeded(result)
                outcome = result_status(result)
                return result
            finally:
                latency_ms = (time.perf_counter() - start) * 1000.0
                server.metrics.observe(tool_name, latency_ms=latency_ms, success=success, target=resolved_target.name if resolved_target is not None else "unresolved", outcome=outcome)

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
            outcome = "error"
            target = kwargs.pop("target", None)
            approval_token = kwargs.get("approval_token") or approval_context.get()
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
                success = result_succeeded(result)
                outcome = result_status(result)
                return result
            finally:
                latency_ms = (time.perf_counter() - start) * 1000.0
                server.metrics.observe(tool_name, latency_ms=latency_ms, success=success, target=resolved_target.name if resolved_target is not None else "unresolved", outcome=outcome)

        return wrapped


