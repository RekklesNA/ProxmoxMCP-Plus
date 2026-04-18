# API & Tool Reference

This page is the reference index for the ProxmoxMCP-Plus tool surface and the OpenAPI wrapper that exposes it over HTTP.

Use this page when you need exact tool names, input shapes, prerequisites, or common failure patterns. Use the [Operator Guide](Operator-Guide) for deployment and runtime setup, and the [Security Guide](Security-Guide) for policy and access controls.

## How To Read This Page

- `Read-only` tools inspect Proxmox state and should be your first call when validating reachability or inventory.
- `Mutating` tools create, start, stop, change, restore, or delete infrastructure.
- Tool availability depends on runtime configuration. In particular, some command-execution tools are only registered when `ssh` config is present.
- HTTP mode is a bridge over the same MCP tool surface. The generated schema at `/openapi.json` is the source of truth for the exact request and response shape exposed by the running server.

## OpenAPI Service Endpoints

When the OpenAPI wrapper is enabled, the primary endpoints are:

| Path | Purpose | Notes |
| --- | --- | --- |
| `/` | service metadata | basic wrapper metadata |
| `/docs` | Swagger UI | interactive API docs for the currently running tool set |
| `/openapi.json` | generated OpenAPI schema | reflects conditional tool registration such as SSH-backed tools |
| `/health` | health and backend status | validates wrapper availability and MCP backend connectivity |

## Global Behavior And Constraints

### Authentication and Authorization

- Proxmox API access requires a valid `proxmox` and `auth` configuration.
- SSH-backed container command workflows require a valid `ssh` configuration.
- Command-execution tools are subject to command-policy checks. Depending on policy, a request can be allowed, denied, or require an `approval_token`.
- Detailed policy behavior lives in the [Security Guide](Security-Guide).

### Output Conventions

- Some tools return human-readable text by default.
- Several container tools support `format_style` with `pretty` or `json`.
- In HTTP mode, exact request and response payloads should be verified against `/openapi.json` for the running server version.

### Common Prerequisites

- Mutating tools assume the target node, VM, container, storage pool, or archive already exists unless the tool itself creates it.
- VM command execution requires a running VM with QEMU Guest Agent available.
- Container command execution requires SSH to the Proxmox host and a running target container.
- Backup restore uses a new target `vmid`; it is not an in-place overwrite workflow.

### Container Selector Grammar

Several container tools accept a `selector` parameter. Supported forms:

- `123`
- `pve1:123`
- `pve1/name`
- `name`
- comma-separated lists for bulk operations

Selector-based tools fail when no container matches the selector or when a bulk selector includes invalid targets.

## Node Tools

| Tool | Mode | Required Inputs | Optional Inputs | Prerequisites | Common Failures |
| --- | --- | --- | --- | --- | --- |
| `get_nodes` | Read-only | none | none | Proxmox API reachable | auth failure, API unavailable |
| `get_node_status` | Read-only | `node` | none | target node exists | unknown node, auth failure |

## VM Tools

| Tool | Mode | Required Inputs | Optional Inputs | Prerequisites | Common Failures |
| --- | --- | --- | --- | --- | --- |
| `get_vms` | Read-only | none | none | Proxmox API reachable | partial node-query failures may reduce returned coverage |
| `create_vm` | Mutating | `node`, `vmid`, `name`, `cpus`, `memory`, `disk_size` | `storage`, `ostype`, `network_bridge` | target node exists and selected storage is valid | duplicate `vmid`, invalid storage, insufficient resources |
| `start_vm` | Mutating | `node`, `vmid` | none | VM exists | VM not found, node mismatch |
| `stop_vm` | Mutating | `node`, `vmid` | none | VM exists | VM not found, stop failure from Proxmox |
| `shutdown_vm` | Mutating | `node`, `vmid` | none | VM exists | guest shutdown unavailable or timeout on guest side |
| `reset_vm` | Mutating | `node`, `vmid` | none | VM exists | VM not found, reset rejected by Proxmox |
| `delete_vm` | Mutating | `node`, `vmid` | `force=false` | VM exists | running VM without `force`, VM not found |
| `execute_vm_command` | Mutating | `node`, `vmid`, `command` | `approval_token` | VM running, QEMU Guest Agent installed, policy allows command | guest agent unavailable, VM not running, policy denial |

### VM Notes

- `stop_vm` is the force-stop path. Use `shutdown_vm` for graceful guest shutdown when supported.
- `execute_vm_command` is not a generic SSH shell. It is mediated through QEMU Guest Agent and command-policy checks.

## Container Tools

| Tool | Mode | Required Inputs | Optional Inputs | Prerequisites | Common Failures |
| --- | --- | --- | --- | --- | --- |
| `get_containers` | Read-only | `payload` body | `node`, `include_stats=true`, `include_raw=false`, `format_style=pretty\|json` | Proxmox API reachable | invalid payload shape, auth failure |
| `start_container` | Mutating | `selector` | `format_style=pretty\|json` | selector resolves to one or more containers | no selector match, start failure from Proxmox |
| `stop_container` | Mutating | `selector` | `graceful=true`, `timeout_seconds=10`, `format_style=pretty\|json` | selector resolves to one or more containers | no selector match, timeout on graceful shutdown, container already stopped |
| `restart_container` | Mutating | `selector` | `timeout_seconds=10`, `format_style=pretty\|json` | selector resolves to one or more containers | no selector match, reboot failure |
| `update_container_resources` | Mutating | `selector` | `cores`, `memory`, `swap`, `disk_gb`, `disk=rootfs`, `format_style=pretty\|json` | selector resolves to one or more containers | no selector match, invalid resize target, resource update rejected |
| `create_container` | Mutating | `node`, `vmid`, `ostemplate` | `hostname`, `cores=1`, `memory=512`, `swap=512`, `disk_size=8`, `storage`, `password`, `ssh_public_keys`, `network_bridge=vmbr0`, `start_after_create=false`, `onboot=false`, `nesting=false`, `unprivileged=true` | target node exists, template path valid, target storage valid | duplicate `vmid`, missing template, invalid storage or bridge |
| `delete_container` | Mutating | `selector` | `force=false`, `format_style=pretty\|json` | selector resolves to one or more containers | no selector match, running container without `force`, delete failure |
| `execute_container_command` | Mutating | `selector`, `command` | `approval_token` | only registered when `ssh` config exists; container must be running; policy must allow command | tool unavailable without SSH config, no selector match, SSH failure, policy denial |
| `update_container_ssh_keys` | Mutating | `node`, `vmid`, `public_keys` | `mode=append\|replace` | only registered when `ssh` config exists; target container reachable through configured execution path | tool unavailable without SSH config, invalid container target, SSH failure |
| `get_container_config` | Read-only | `node`, `vmid` | none | target container exists | container not found, node mismatch |
| `get_container_ip` | Read-only | `node`, `vmid` | none | target container exists | container not found, IP information unavailable |

### Container Notes

- `get_containers` uses a request body model rather than a flat parameter list.
- `update_container_resources.disk_gb` is an additional resize amount for the selected disk, not a full replacement size target.
- `create_container.start_after_create` controls immediate startup after provisioning.
- `create_container.nesting` and `create_container.unprivileged` change container execution characteristics and should match your Proxmox policy.

## Snapshot Tools

| Tool | Mode | Required Inputs | Optional Inputs | Prerequisites | Common Failures |
| --- | --- | --- | --- | --- | --- |
| `list_snapshots` | Read-only | `node`, `vmid` | `vm_type=qemu\|lxc` | target VM or container exists | wrong `vm_type`, missing target |
| `create_snapshot` | Mutating | `node`, `vmid`, `snapname` | `description`, `vmstate=false`, `vm_type=qemu\|lxc` | target exists | duplicate snapshot name, unsupported `vmstate` use, wrong target type |
| `delete_snapshot` | Mutating | `node`, `vmid`, `snapname` | `vm_type=qemu\|lxc` | snapshot exists | snapshot not found, wrong target type |
| `rollback_snapshot` | Mutating | `node`, `vmid`, `snapname` | `vm_type=qemu\|lxc` | snapshot exists | snapshot not found, rollback rejected by Proxmox |

### Snapshot Notes

- `rollback_snapshot` is a disruptive restore action and should be treated as an operationally sensitive step.
- `vmstate` applies to VM snapshots and is not a general LXC memory-capture option.

## ISO and Template Tools

| Tool | Mode | Required Inputs | Optional Inputs | Prerequisites | Common Failures |
| --- | --- | --- | --- | --- | --- |
| `list_isos` | Read-only | none | `node`, `storage` | Proxmox API reachable | invalid node or storage filter |
| `list_templates` | Read-only | none | `node`, `storage` | Proxmox API reachable | invalid node or storage filter |
| `download_iso` | Mutating | `node`, `storage`, `url`, `filename` | `checksum`, `checksum_algorithm=sha256` | target storage writable and reachable by Proxmox | invalid URL, checksum mismatch, unsupported storage target |
| `delete_iso` | Mutating | `node`, `storage`, `filename` | none | file exists in target storage | file not found, storage mismatch |

### ISO and Template Notes

- `list_templates` is commonly used to discover a valid `ostemplate` value for `create_container`.
- When `checksum` is supplied, `checksum_algorithm` must match the provided digest.

## Backup Tools

| Tool | Mode | Required Inputs | Optional Inputs | Prerequisites | Common Failures |
| --- | --- | --- | --- | --- | --- |
| `list_backups` | Read-only | none | `node`, `storage`, `vmid` | backup-capable storage reachable | invalid filter or storage mismatch |
| `create_backup` | Mutating | `node`, `vmid`, `storage` | `compress=0\|gzip\|lz4\|zstd`, `mode=snapshot\|suspend\|stop`, `notes` | target workload exists and storage accepts backups | invalid mode, storage unavailable, backup job rejected |
| `restore_backup` | Mutating | `node`, `archive`, `vmid` | `storage`, `unique=true` | archive exists and target `vmid` is free | missing archive, duplicate target `vmid`, invalid target storage |
| `delete_backup` | Mutating | `node`, `storage`, `volid` | none | backup volume exists | volume not found, storage mismatch |

### Backup Notes

- `restore_backup` restores into a new `vmid`.
- `create_backup.mode` changes how Proxmox coordinates workload state during backup and may affect runtime interruption characteristics.

## Storage and Cluster Tools

| Tool | Mode | Required Inputs | Optional Inputs | Prerequisites | Common Failures |
| --- | --- | --- | --- | --- | --- |
| `get_storage` | Read-only | none | none | Proxmox API reachable | auth failure, cluster query failure |
| `get_cluster_status` | Read-only | none | none | Proxmox API reachable | auth failure, cluster query failure |

## Change Checklist For New Tools

When adding or changing a tool, update all of the following:

- tool implementation under `src/proxmox_mcp/tools/`
- registration in `src/proxmox_mcp/server.py`
- human-facing description in `src/proxmox_mcp/tools/definitions.py`
- tests under `tests/`
- this page if parameters, prerequisites, or availability changed

## Related Pages

- [Operator Guide](Operator-Guide)
- [Security Guide](Security-Guide)
- [Integrations Guide](Integrations-Guide)
- [Troubleshooting](Troubleshooting)
