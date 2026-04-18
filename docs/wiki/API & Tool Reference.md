# API & Tool Reference

This page is the main index for tools and endpoint behavior.

## Service Endpoints

When the OpenAPI wrapper is running, the main endpoints are:

| Path | Purpose |
| --- | --- |
| `/` | basic service metadata |
| `/docs` | Swagger UI |
| `/openapi.json` | generated OpenAPI schema |
| `/health` | wrapper health and MCP backend connection status |

## Tool Groups

The MCP server currently registers tools from these groups:

- nodes
- VMs
- containers
- storage
- cluster status
- snapshots
- ISOs and templates
- backups
- container config and IP inspection
- optional command execution

## Node Tools

| Tool | Purpose | Notes |
| --- | --- | --- |
| `get_nodes` | list nodes in the cluster | returns node status and summary data |
| `get_node_status` | inspect one node | accepts a required `node` parameter |

## VM Tools

| Tool | Purpose | Notes |
| --- | --- | --- |
| `get_vms` | list VMs across the cluster | skips nodes that cannot be queried |
| `create_vm` | create a new VM | requires `node`, `vmid`, `name`, `cpus`, `memory`, `disk_size` |
| `start_vm` | start a VM | mutating |
| `stop_vm` | force stop a VM | mutating |
| `shutdown_vm` | graceful shutdown | mutating |
| `reset_vm` | restart/reset a VM | mutating |
| `delete_vm` | delete a VM | supports `force=false` by default |
| `execute_vm_command` | run a command via QEMU Guest Agent | subject to command policy |

## Container Tools

| Tool | Purpose | Notes |
| --- | --- | --- |
| `get_containers` | list containers | supports node filter and `pretty` or `json` output |
| `start_container` | start one or more containers | selector syntax supports ID, node-prefixed ID, name, or comma list |
| `stop_container` | stop one or more containers | supports graceful or forced stop |
| `restart_container` | restart one or more containers | mutating |
| `update_container_resources` | update cores, memory, swap, and disk | supports resizing `rootfs` |
| `create_container` | create a new LXC container | supports template, resources, networking, onboot, nesting, unprivileged mode |
| `delete_container` | delete one or more containers | supports `force` |
| `execute_container_command` | run a command inside a running container | only registered when `ssh` config exists |
| `update_container_ssh_keys` | append or replace root `authorized_keys` in a container | only registered when `ssh` config exists |
| `get_container_config` | return full container config | no SSH required |
| `get_container_ip` | inspect container interfaces and primary IP | no SSH required |

### Container Selector Grammar

Several container tools accept a `selector` parameter. Supported forms:

- `123`
- `pve1:123`
- `pve1/name`
- `name`
- comma-separated lists for bulk operations

## Snapshot Tools

| Tool | Purpose | Notes |
| --- | --- | --- |
| `list_snapshots` | list snapshots for a VM or container | supports `vm_type=qemu|lxc` |
| `create_snapshot` | create a snapshot | can include `vmstate` for VMs |
| `delete_snapshot` | delete a snapshot | mutating |
| `rollback_snapshot` | restore a snapshot | mutating and potentially disruptive |

## ISO and Template Tools

| Tool | Purpose | Notes |
| --- | --- | --- |
| `list_isos` | list ISO images | optional node and storage filters |
| `list_templates` | list LXC templates | use result as `ostemplate` when creating containers |
| `download_iso` | download an ISO into Proxmox storage | supports checksum and algorithm |
| `delete_iso` | delete an ISO or template file | mutating |

## Backup Tools

| Tool | Purpose | Notes |
| --- | --- | --- |
| `list_backups` | list backup archives | optional node, storage, and VMID filters |
| `create_backup` | create a VM or container backup | supports compression and backup mode |
| `restore_backup` | restore from a backup archive | restore to a new `vmid` |
| `delete_backup` | delete a backup archive | mutating |

## Storage and Cluster Tools

| Tool | Purpose | Notes |
| --- | --- | --- |
| `get_storage` | list storage pools and usage | read-only |
| `get_cluster_status` | get overall cluster status | read-only |

## Output and Prerequisite Notes

- Some tools return pretty formatted text by default
- Some container tools support explicit JSON output through `format_style`
- `execute_vm_command` requires the VM to be running and QEMU Guest Agent to be available
- `execute_container_command` requires SSH config and a running container
- mutating tools should be tested only after read-only tools confirm the environment is reachable

## What To Document For New Tools

When you add a new tool, document:

- what it does
- required parameters
- optional parameters
- prerequisites
- common failure cases
- whether it is read-only or mutating

## Related Pages

- [Operator Guide](Operator-Guide)
- [Security Guide](Security-Guide)
- [Troubleshooting](Troubleshooting)
