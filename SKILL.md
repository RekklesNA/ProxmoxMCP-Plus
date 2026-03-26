---
name: proxmox
description: Proxmox Python scripting helper. Use when working with Proxmox VE — managing VMs, LXC containers, snapshots, backups, or nodes via the pxas scripting tool.
---

# Proxmox Python Scripting Skill

## Environment & Execution Rules (STATIC — DO NOT EDIT)

- `pxas` is installed globally via `uv tool install` — run it from any directory.
- Never create venvs manually; `uv` manages the tool environment.
- One-liner: `pxas -c "from pxas import ct; print(ct.get_containers())"`
- Script: `pxas your_script.py`
- Boilerplate: `from pxas import px, ct, nt, vt, st, bt, cfg`
- **Selector grammar:** `101` (int) | `'101'` (vmid) | `'node:101'` | `'node/name'` | `'name'` | comma-separated list | `['101', '102']` (list).
- **Query methods** (`get_*`, `list_*`, `execute_command`, `wait_until`) return plain dicts/lists.
- **Mutating methods** return `(bool, dict|list)` — unpack as `ok, info = vt.start_vm(node, vmid)`.
- On error, mutating methods return `(False, {"error": True, "function": "...", "reason": "...", "fix": "..."})`. Read `fix` to self-correct.
- Query method errors return the same error dict directly (no tuple).
- Paths are WSL-agnostic — Windows paths auto-convert to Linux mounts. SSH keys are auto-fixed to `600` permissions.
- `px` is the raw `ProxmoxAPI` instance for anything not in tool classes.
- Never wrap results in `json.dumps()` for tool returns — methods already return native Python objects.
- Use `cfg.ssh`, `cfg.proxmox`, `cfg.auth` for config access.
- Do not check for config before using, just try the call.

## Tool Classes Quick Reference

| Class | Var | Purpose |
|-------|-----|---------|
| `ContainerTools` | `ct` | LXC containers (list, start, stop, restart, exec, create, delete, config, IP, resize) |
| `NodeTools` | `nt` | Proxmox nodes (list, status) |
| `VMTools` | `vt` | QEMU VMs (list, start, stop, shutdown, reset, create, delete) |
| `SnapshotTools` | `st` | Snapshots (list, create, delete, rollback) — works for both LXC and QEMU |
| `BackupTools` | `bt` | Backups (list, create, restore, delete) |
| `Config` | `cfg` | Loaded configuration |

Most mutating methods accept `wait=True, timeout_s=60, retry=True` to poll until the task completes and retry on transient failures (lock contention, 5xx errors). Permanent failures (404, 403, already exists/running/stopped, invalid parameters) are never retried. Pass `wait=False` to get a raw UPID string instead. Notable exceptions: `create_container` and `create_backup`/`restore_backup` default to `timeout_s=300`; `restart_vm` and `create_vm` default to `timeout_s=120`.

## ContainerTools Methods

| Method | Parameters | Returns |
|--------|-----------|---------|
| `get_containers` | `node=None, include_stats=True, realtime=False` | `[{vmid, name, node, status, cores, memory_mib, cpu_pct, mem_bytes, maxmem_bytes, mem_pct, unlimited_memory}]` |
| `start_container` | `selector` | `(bool, [{node, vmid, name, output, elapsed}])` |
| `stop_container` | `selector, graceful=True, grace_timeout_s=10` | `(bool, [{node, vmid, name, output, elapsed}])` |
| `restart_container` | `selector` | `(bool, [{node, vmid, name, output, elapsed}])` |
| `execute_command` | `selector, command, timeout=60` | `{success, output, error, exit_code}` |
| `wait_until` | `selector, command, timeout_s=300, interval_s=5` | `{matched, attempts, elapsed, last_output, last_exit_code}` |
| `get_container_config` | `node, vmid` | `{vmid, hostname, cores, memory, ...}` (flat, verbose fields stripped) |
| `get_container_ip` | `node, vmid` | `{vmid, name, interfaces, primary_ip}` |
| `update_container_resources` | `selector, cores=None, memory=None, swap=None, disk_gb=None, disk="rootfs"` | `(bool, [{node, vmid, name, changes}])` |
| `update_container_ssh_keys` | `node, vmid, public_keys, mode="append"` | `(bool, {keys_added})` |
| `create_container` | `node, vmid, ostemplate, hostname=None, cores=1, memory=512, swap=512, disk_size=8, storage=None, password=None, ssh_public_keys=None, network_bridge="vmbr0", start_after_create=False, unprivileged=True` | `(bool, {vmid, hostname, node, ostemplate, cores, memory_mib, swap_mib, disk_gb, storage, network_bridge, unprivileged, start_after_create, output, elapsed})` |
| `delete_container` | `selector, force=False` | `(bool, [{node, vmid, name, output, elapsed}])` |

## NodeTools Methods

| Method | Parameters | Returns |
|--------|-----------|---------|
| `get_nodes` | — | `[{node, status, uptime, cpu_cores, cpu_pct, mem_used, mem_total, mem_pct, disk_used, disk_total}]` |
| `get_node_status` | `node` | `{node, status, uptime, cpu_cores, cpu_pct, mem_used, mem_total, mem_pct, kversion, pveversion}` |

## VMTools Methods

| Method | Parameters | Returns |
|--------|-----------|---------|
| `get_vms` | `node=None` | `[{vmid, name, status, node, cores, mem_bytes, maxmem_bytes, cpu_pct}]` |
| `start_vm` | `selector` | `(bool, [{node, vmid, name, output, elapsed}])` |
| `stop_vm` | `selector` | `(bool, [{node, vmid, name, output, elapsed}])` |
| `shutdown_vm` | `selector` | `(bool, [{node, vmid, name, output, elapsed}])` |
| `reset_vm` | `selector` | `(bool, [{node, vmid, name, output, elapsed}])` |
| `restart_vm` | `selector` | `(bool, [{node, vmid, name, output, elapsed}])` |
| `delete_vm` | `selector, force=False` | `(bool, [{node, vmid, name, output, elapsed}])` |
| `update_vm_resources` | `selector, cores=None, memory=None` | `(bool, [{node, vmid, name, changes}])` |
| `create_vm` | `node, vmid, name, cpus, memory, disk_size, storage=None, ostype=None, network_bridge=None` | `(bool, {vmid, name, node, cores, memory_mib, disk_gb, storage, output, elapsed})` |

## SnapshotTools Methods

| Method | Parameters | Returns |
|--------|-----------|---------|
| `list_snapshots` | `node, vmid, vm_type="qemu"` | `[{name, parent, created, ram_included}]` |
| `create_snapshot` | `node, vmid, snapname, description=None, vmstate=False, vm_type="qemu"` | `(bool, {snapname, vmid, node, vm_type, output, elapsed})` |
| `delete_snapshot` | `node, vmid, snapname, vm_type="qemu"` | `(bool, {snapname, vmid, node, vm_type, output, elapsed})` |
| `rollback_snapshot` | `node, vmid, snapname, vm_type="qemu"` | `(bool, {snapname, vmid, node, vm_type, deleted_newer, output, elapsed})` |

## BackupTools Methods

| Method | Parameters | Returns |
|--------|-----------|---------|
| `list_backups` | `node=None, storage=None, vmid=None` | `[{volid, size, size_human, vmid, format, ctime, node, storage, protected}]` |
| `create_backup` | `node, vmid, storage, compress="zstd", mode="snapshot", notes=None` | `(bool, {vmid, node, storage, compress, mode, output, elapsed})` |
| `restore_backup` | `node, archive, vmid, storage=None, unique=True` | `(bool, {vmid, node, archive, type, output, elapsed})` |
| `delete_backup` | `node, volid` | `(bool, {volid, node, storage, deleted, output, elapsed, also_cleaned?})` |

## Raw proxmoxer API

Use `px` for anything not covered by the tool classes:

```python
nodes = px.nodes.get()
containers = px.nodes("pve1").lxc.get()
status = px.nodes("pve1").lxc(101).status.current.get()
px.nodes("pve1").lxc(101).status.start.post()
px.nodes("pve1").lxc(101).config.put(memory=2048)
```

## Notes

- `execute_command` SSHes to the Proxmox node and runs `pct exec` — no guest agent needed.
- CPU percentages are rounded to 2 decimal places. Memory is in MiB / bytes.
- The `wait_until` method reuses a single SSH connection across all poll attempts.
- All commands passed to containers use `shlex.quote` to prevent injection.
- WSL path auto-conversion is built in — pass `C:\Users\...` paths and they convert to `/mnt/c/...` automatically.
