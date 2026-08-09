# Tool Selection Guide

Use this page when you know the operational goal but are not sure which ProxmoxMCP-Plus tool path to use.

## Start With Discovery

Run read-only tools before mutating anything:

| Goal | Read-only tools |
| --- | --- |
| Check cluster health | `get_nodes`, `get_cluster_status` |
| Find VMs | `get_vms`, `get_vm_config` |
| Find containers | `get_containers`, `get_container_config`, `get_container_ip` |
| Check storage | `get_storage` |
| Check snapshots | `list_snapshots` with `vm_type=qemu` or `vm_type=lxc` |
| Check jobs | `list_jobs`, `get_job` |
| Check logs | `get_node_syslog`, `get_cluster_log` |

Discovery confirms node names, VMIDs, storage IDs, guest status, and whether the tool is visible in the connected client.

## VM Workflows

| Operator goal | Tool sequence | Verify |
| --- | --- | --- |
| Create a VM | `get_nodes` -> `get_storage` -> `create_vm` -> `poll_job` | `get_vms` or `get_vm_config` |
| Start or stop a VM | `get_vms` -> `start_vm` or `stop_vm` -> `poll_job` | `get_vms` |
| Delete a VM | `get_vms` -> snapshot or backup if needed -> `delete_vm` -> `poll_job` | `get_vms` |
| Run a guest command | `get_vms` -> `execute_vm_command` | command output and guest-agent status |

VM command execution requires QEMU Guest Agent inside the VM.

## Container Workflows

| Operator goal | Tool sequence | Verify |
| --- | --- | --- |
| Create an LXC | `get_nodes` -> `get_storage` -> `create_container` -> `poll_job` | `get_containers` |
| Start or stop an LXC | `get_containers` -> `start_container` or `stop_container` -> `poll_job` | `get_containers` |
| Delete an LXC | `get_containers` -> snapshot or backup if needed -> `delete_container` -> `poll_job` | `get_containers` |
| Execute a command in an LXC | `get_containers` -> `execute_container_command` | command output |
| Update container SSH keys | `get_containers` -> `update_container_ssh_keys` | inspect authorized keys inside the container |

Container command execution appears only when the config has an `ssh` section. It SSHes to the Proxmox node and uses `pct exec`, so treat it as a separate security decision.

## Snapshot And Rollback Workflows

| Operator goal | Tool sequence | Verify |
| --- | --- | --- |
| Prepare for a risky change | `list_snapshots` -> `create_snapshot` -> `poll_job` | `list_snapshots` |
| Roll back a VM or LXC | `list_snapshots` -> `rollback_snapshot` -> `poll_job` | guest status and `list_snapshots` |
| Clean old snapshots | `list_snapshots` -> `delete_snapshot` -> `poll_job` | `list_snapshots` |

Use snapshots before testing destructive tool flows in a lab.

## Backup And Restore Workflows

| Operator goal | Tool sequence | Verify |
| --- | --- | --- |
| Create a backup | `get_storage` -> `create_backup` -> `poll_job` | backup list or storage contents |
| Restore a backup | `get_storage` -> select backup artifact -> `restore_backup` -> `poll_job` | VM or LXC status |
| Delete a backup | inspect backup metadata -> `delete_backup` | backup list |

Backup and restore operations are long-running Proxmox tasks. Use `job_id` for user-facing tracking and `task_id` for Proxmox-level traceability.

## ISO And Template Workflows

| Operator goal | Tool sequence | Verify |
| --- | --- | --- |
| Download an ISO | `get_storage` -> `download_iso` -> `poll_job` | storage contents |
| Delete an ISO | inspect storage contents -> `delete_iso` | storage contents |
| Create an LXC from template | `get_storage` -> confirm template exists -> `create_container` -> `poll_job` | container status |

Check storage content support before downloading ISOs or using templates.

## Job Tracking Workflows

Most mutating Proxmox operations return:

- `task_id`: the raw Proxmox `UPID`
- `job_id`: the persistent ProxmoxMCP-Plus job record

Use the job tools this way:

| Situation | Tool |
| --- | --- |
| User asks for recent work | `list_jobs` |
| User asks about one operation | `get_job` |
| You need fresh Proxmox task status | `poll_job` |
| A retryable operation failed | inspect `get_job`, then `retry_job` |
| A running task should stop | `cancel_job` |

Keep `jobs.sqlite_path` on durable storage when the deployment should preserve job history across restarts.

## Log Inspection Workflows

All log tools are read-only and safe to run at any time:

| Operator goal | Tool sequence | Verify |
| --- | --- | --- |
| Investigate a node problem | `get_node_syslog` with `since`/`until` filters | narrowed log window around the incident |
| Find out why a task failed | `get_task_log` with the task's `UPID` | task log output and exit status lines |
| Audit recent cluster activity | `get_cluster_log` | cluster-wide event history |
| Debug firewall behavior | `get_node_firewall_log` or `get_guest_firewall_log` | ACCEPT/DROP entries for the traffic in question |

`get_task_log` accepts any Proxmox task `UPID`, including tasks started outside this server. Use `poll_job` instead when you are tracking a `job_id` created by a mutating tool.

## OpenAPI Workflows

Use OpenAPI when a client cannot speak MCP:

1. Start the OpenAPI bridge.
2. Check `/livez`.
3. Send bearer auth to `/health` or `/readyz`.
4. Inspect `/openapi.json`.
5. Use generated tool routes and `/jobs` routes from the schema.

The OpenAPI bridge is not the native MCP Streamable HTTP endpoint. MCP HTTP clients should connect to `/mcp` on the service running on port `8000`.

## Safety Checklist Before Mutating

- Confirm the Proxmox API token has the required permissions and no more than necessary.
- Confirm the node, storage, VMID, and guest status from read-only tools.
- Confirm TLS verification settings are intentional.
- Confirm command policy and approval-token settings before using command tools.
- Confirm a snapshot or backup exists before risky changes.
- Confirm the user expects a real Proxmox mutation, not a dry-run explanation.

## Related Pages

- [API & Tool Reference](API-&-Tool-Reference)
- [Operator Guide](Operator-Guide)
- [Security Guide](Security-Guide)
- [Troubleshooting](Troubleshooting)
