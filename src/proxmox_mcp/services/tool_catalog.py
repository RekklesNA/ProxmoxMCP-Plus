"""Canonical names for the built-in MCP tool catalog."""

from __future__ import annotations

from mcp.types import ToolAnnotations

BUILTIN_TOOL_NAMES = frozenset(
    {
        "list_targets",
        "get_nodes",
        "list_bridges",
        "get_node_status",
        "get_node_time",
        "get_node_diagnostics",
        "get_vms",
        "get_vm_config",
        "preflight_vm_migration",
        "migrate_vm",
        "configure_vm_serial_console",
        "import_cloud_image",
        "set_vm_description",
        "update_vm_config",
        "update_container_network",
        "get_vm_ip_addresses",
        "get_next_vmid",
        "create_vm",
        "clone_vm",
        "execute_vm_command",
        "start_vm",
        "stop_vm",
        "shutdown_vm",
        "reset_vm",
        "delete_vm",
        "get_storage",
        "get_node_storage",
        "get_cluster_status",
        "get_cluster_join_info",
        "list_jobs",
        "get_job",
        "poll_job",
        "cancel_job",
        "retry_job",
        "reconcile_job",
        "get_containers",
        "preflight_container_migration",
        "start_container",
        "stop_container",
        "restart_container",
        "update_container_resources",
        "create_container",
        "delete_container",
        "migrate_container",
        "execute_container_command",
        "execute_node_command",
        "update_container_ssh_keys",
        "get_container_config",
        "set_container_description",
        "get_container_ip",
        "list_snapshots",
        "create_snapshot",
        "delete_snapshot",
        "rollback_snapshot",
        "list_isos",
        "list_templates",
        "download_iso",
        "download_template",
        "delete_iso",
        "list_backups",
        "create_backup",
        "restore_backup",
        "delete_backup",
        "get_node_syslog",
        "get_task_log",
        "get_cluster_log",
        "get_node_firewall_log",
        "get_guest_firewall_log",
    }
)


def _read_only(*, open_world: bool = True) -> ToolAnnotations:
    return ToolAnnotations(readOnlyHint=True, openWorldHint=open_world)


def _write(
    *, destructive: bool, idempotent: bool = False, open_world: bool = True
) -> ToolAnnotations:
    return ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=destructive,
        idempotentHint=idempotent,
        openWorldHint=open_world,
    )


# MCP tool annotations advertised in tools/list. Clients may use readOnlyHint to
# skip confirmation for read-only tools. The read-only set must stay aligned with
# the tools allowed on read-only targets (_READ_ONLY_TOOLS plus list_targets).
BUILTIN_TOOL_ANNOTATIONS: dict[str, ToolAnnotations] = {
    # Read-only queries.
    "list_targets": _read_only(open_world=False),
    "get_nodes": _read_only(),
    "list_bridges": _read_only(),
    "get_node_status": _read_only(),
    "get_node_time": _read_only(),
    "get_node_diagnostics": _read_only(),
    "get_vms": _read_only(),
    "get_vm_config": _read_only(),
    "preflight_vm_migration": _read_only(),
    "get_vm_ip_addresses": _read_only(),
    "get_next_vmid": _read_only(),
    "get_storage": _read_only(),
    "get_node_storage": _read_only(),
    "get_cluster_status": _read_only(),
    "get_cluster_join_info": _read_only(),
    "list_jobs": _read_only(open_world=False),
    "get_job": _read_only(),
    "poll_job": _read_only(),
    "get_containers": _read_only(),
    "preflight_container_migration": _read_only(),
    "get_container_config": _read_only(),
    "get_container_ip": _read_only(),
    "list_snapshots": _read_only(),
    "list_isos": _read_only(),
    "list_templates": _read_only(),
    "list_backups": _read_only(),
    "get_node_syslog": _read_only(),
    "get_task_log": _read_only(),
    "get_cluster_log": _read_only(),
    "get_node_firewall_log": _read_only(),
    "get_guest_firewall_log": _read_only(),
    # Additive operations.
    "create_vm": _write(destructive=False),
    "clone_vm": _write(destructive=False),
    "import_cloud_image": _write(destructive=False),
    "create_container": _write(destructive=False),
    "create_snapshot": _write(destructive=False),
    "download_iso": _write(destructive=False),
    "download_template": _write(destructive=False),
    # Operations that overwrite, interrupt, delete or run arbitrary commands.
    # A start changes power state and starts guest workloads, not just inventory.
    "start_vm": _write(destructive=True),
    "start_container": _write(destructive=True),
    # Backup mode=stop/suspend can interrupt a running guest.
    "create_backup": _write(destructive=True),
    "set_vm_description": _write(destructive=True, idempotent=True),
    "update_vm_config": _write(destructive=True, idempotent=True),
    "configure_vm_serial_console": _write(destructive=True, idempotent=True),
    "set_container_description": _write(destructive=True, idempotent=True),
    # disk_gb is an increment (+NG), so repeating a call grows the disk again.
    "update_container_resources": _write(destructive=True),
    "update_container_network": _write(destructive=True, idempotent=True),
    "update_container_ssh_keys": _write(destructive=True),
    "migrate_vm": _write(destructive=True),
    "migrate_container": _write(destructive=True),
    "stop_vm": _write(destructive=True),
    "shutdown_vm": _write(destructive=True),
    "reset_vm": _write(destructive=True),
    "delete_vm": _write(destructive=True),
    "stop_container": _write(destructive=True),
    "restart_container": _write(destructive=True),
    "delete_container": _write(destructive=True),
    "execute_vm_command": _write(destructive=True),
    "execute_container_command": _write(destructive=True),
    "execute_node_command": _write(destructive=True),
    "rollback_snapshot": _write(destructive=True),
    "delete_snapshot": _write(destructive=True),
    "delete_iso": _write(destructive=True),
    "restore_backup": _write(destructive=True),
    "delete_backup": _write(destructive=True),
    "cancel_job": _write(destructive=True),
    "retry_job": _write(destructive=True),
    "reconcile_job": _write(destructive=True, open_world=False),
}
