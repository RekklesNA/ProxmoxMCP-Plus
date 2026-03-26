# pxas — Proxmox Python Scripting SKILL.md for ClaudeCode, OpenCode and anything else

Single-file Proxmox management toolkit for AI coding agents. Zero MCP servers, zero boilerplate - just `uv install` and YOLO.

Inspired by [ProxmoxMCP-Plus](https://github.com/RekklesNA/ProxmoxMCP-Plus) but more ~~reckless~~ streamlined.

It turns out even the free models handle Python quite well, especially with skills:

![Minimax-m2.5](after2.png)

(also succesfully tested with Gemini 3 Flash, MiMo V2, Step 3.5 Flash, Kimi K2, use at your own risk)

## Features

- **Monolithic** — one `pxas.py` file, all logic inline, installed globally via `uv tool install`
- **Native returns** — every method returns Python dicts/lists, no deserialization wrappers
- **Token-optimized** — verbose API fields stripped, floats rounded to 2 decimals
- **Structured errors** — failures return `{reason, params, fix}` so the agent self-corrects
- **WSL-aware** — Windows paths auto-convert to Linux mounts
- **Secure exec** — `shlex.quote` on all commands, separated stdout/stderr, dynamic timeout

## Quick Start

```bash
# One-liner
pxas -c "from pxas import ct; print(ct.get_containers())"

# Run a script
pxas my_script.py
```

**[Configuration & Installation (Claude Code, OpenCode, standalone, SSH setup) →](INSTALLATION.md)**

## Usage

### Boilerplate

```python
from pxas import px, ct, nt, vt, st, bt, cfg
```

| Export | Class | Description |
|--------|-------|-------------|
| `px` | `ProxmoxAPI` | Raw proxmoxer client for direct API calls |
| `ct` | `ContainerTools` | LXC containers |
| `nt` | `NodeTools` | Proxmox nodes |
| `vt` | `VMTools` | QEMU virtual machines |
| `st` | `SnapshotTools` | Snapshots (LXC + QEMU) |
| `bt` | `BackupTools` | Backup and restore |
| `cfg` | `Config` | Loaded configuration |

### One-liners

```bash
pxas -c"from pxas import ct; print(ct.get_containers())"
pxas -c"from pxas import ct; print(ct.start_container('my-app'))"
pxas -c"from pxas import ct; print(ct.start_container(101))"
pxas -c"from pxas import ct; print(ct.delete_container(2137))"
pxas -c"from pxas import ct; print(ct.execute_command('101', 'uptime'))"
pxas -c"from pxas import nt; print(nt.get_nodes())"
```

### Scripts

```python
from pxas import ct, nt

for c in ct.get_containers():
    if c["status"] == "running":
        print(f"{c['name']}: {c['cpu_pct']}% CPU, {c['mem_pct']}% RAM")

result = ct.execute_command("my-app", "docker ps --format '{{.Names}}'")
print(result["output"])

ct.wait_until("my-app", "test -f /tmp/deploy.done", timeout_s=300)
```

### Raw proxmoxer API

```python
from pxas import px

nodes = px.nodes.get()
containers = px.nodes("pve1").lxc.get()
status = px.nodes("pve1").lxc(101).status.current.get()
px.nodes("pve1").lxc(101).config.put(memory=2048)
```

### Selector grammar

Most container methods accept a `selector` — either an `int` VMID or a `str`:

| Pattern | Example | Description |
|---------|---------|-------------|
| `int` | `101` | Match VMID across cluster |
| `str vmid` | `"101"` | Same — string form |
| `node:vmid` | `"pve1:101"` | Exact node + VMID |
| `node/name` | `"pve1/my-app"` | Node + container name |
| `name` | `"my-app"` | Match name across cluster |
| Comma list | `"101,pve1:102"` | Multiple targets |

## Container Operations

```python
ct.get_containers(node="pve1", include_stats=True)
ct.start_container("my-app")
ct.start_container(101)                          # int VMID works too
ct.stop_container("101", graceful=True, grace_timeout_s=30)
ct.stop_container(101)                            # same
ct.restart_container("my-app")
ct.get_container_config(node="pve1", vmid="101")
ct.get_container_ip(node="pve1", vmid="101")
ct.update_container_resources("101", cores=2, memory=4096)
ct.update_container_resources(101, cores=2)       # int works
ct.execute_command("my-app", "docker ps", timeout=30)
ct.execute_command(101, "uptime")                 # int works
ct.wait_until("my-app", "test -f /tmp/done", timeout_s=300)
ct.create_container(node="pve1", vmid="200", ostemplate="local:vztmpl/debian-12.tar.zst")
ct.delete_container("200", force=False)
ct.delete_container(200)                          # int works
```

## VM Operations

```python
vt.get_vms()
vt.start_vm("theranos:200")
vt.stop_vm("theranos:200")
vt.shutdown_vm("theranos:200")
vt.reset_vm("theranos:200")
vt.restart_vm("theranos:200")
vt.delete_vm("theranos:200", force=True)
vt.create_vm("theranos", "200", "my-vm", cpus=2, memory=4096, disk_size=50)
vt.update_vm_resources("theranos:200", cores=4, memory=8192)
```

## Snapshot Operations

```python
st.list_snapshots(node="pve1", vmid="101", vm_type="lxc")
st.create_snapshot(node="pve1", vmid="101", snapname="pre-upgrade", vm_type="lxc")
st.rollback_snapshot(node="pve1", vmid="101", snapname="pre-upgrade", vm_type="lxc")
st.delete_snapshot(node="pve1", vmid="101", snapname="old-snap", vm_type="lxc")
```

## Backup Operations

```python
bt.list_backups(node="pve1")
bt.create_backup(node="pve1", vmid="101", storage="local", compress="zstd")
bt.restore_backup(node="pve1", archive="local:backup/vzdump-lxc-101-...", vmid="200")
bt.delete_backup(node="pve1", storage="local", volid="local:backup/vzdump-...")
```

## Error handling

All methods return structured error dicts on failure:

```json
{
    "error": true,
    "function": "ContainerTools.execute_command",
    "reason": "Container 999 on pve1 is not running",
    "params": {"selector": "999", "command": "uptime"},
    "fix": "Start the container before executing commands inside it."
}
```

Always check for `"error" in result` and read the `fix` key to self-correct.

## Why not MCP?

MCP tool calls work fine for one-off queries, but break down quickly in practice:

- **Loops and conditionals** — an agent can't iterate over a list of containers in a single MCP call; it has to make N round-trips, each awaiting approval
- **Multiple operations in one turn** — a script can start 10 containers, wait for each, and report results atomically; MCP chains the same work across many tool calls
- **Elastic filtering** — filter, sort, and reshape API output in Python before it ever reaches the context window; MCP returns raw API payloads
- **Retries and polling** — `wait_until` holds one SSH connection across all poll attempts; MCP has no equivalent

Before (Claude Code with MCP, 7 tool calls to run 3 commands on a containers and verify docker started up):

![Before: MCP approach requiring many round-trips](before.png)

After (do anything you want with one `pxas` script, single tool call):

![After: pxas script handling the same task in one shot](after.png)

## License

MIT
