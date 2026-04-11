# Container Command Execution and SSH Management

## Overview

ProxmoxMCP-Plus includes tools that require direct CLI access to the Proxmox host via SSH to interact
with LXC containers:

1.  **`execute_container_command`**: Run arbitrary shell commands inside a running LXC container.
2.  **`update_container_ssh_keys`**: Inject or replace SSH authorized_keys for the `root` user inside a container.

Under the hood, both tools use `pct exec`, the official Proxmox CLI tool for executing commands
within container namespaces.

This feature requires a one-time SSH setup on your Proxmox nodes. It is **entirely opt-in** — if
you do not add an `ssh` section to your MCP config, these tools are not registered and will not
appear in the MCP tool list at all. Everything else continues to work normally.

---

## Why SSH? The Proxmox REST API Limitation

The Proxmox REST API exposes a QEMU guest agent endpoint that lets you run commands inside virtual
machines:

```
POST /nodes/{node}/qemu/{vmid}/agent/exec
```

LXC containers have no equivalent. `pct exec` is the only official mechanism, and it is a CLI
tool that runs on the Proxmox host itself. It uses `lxc-attach` internally to enter the
container's Linux namespaces — a kernel-level operation that has no REST API surface.

Since the MCP server runs inside a VM on the Proxmox cluster (not on the host directly), it
cannot call `pct exec` locally. The only way to reach it is to SSH into the Proxmox node where
the target container lives and run it there as a subprocess.

In a multi-node cluster, containers can be on any node. The MCP server resolves which node a
container is on via the Proxmox API first, then SSHes to that specific node — so the right node
is always targeted automatically, regardless of cluster topology.

---

## Security Model

### The feature is opt-in

`execute_container_command` is only registered when an `ssh` section is present in the config.
Without it, the tool does not appear in the MCP tool list at all — an absent tool is a clearer
signal to AI agents than a tool that returns an error at call time.

No `ssh` section → no tool registration → no SSH connection, no access.

### Recommended setup: dedicated `mcp-agent` user with scoped sudo

Rather than granting the MCP server SSH access as `root`, the recommended approach creates a
dedicated, unprivileged `mcp-agent` user on each Proxmox node. This user:

- Has no password and cannot log in interactively
- Can only authenticate via SSH key
- Has passwordless `sudo` access scoped **exclusively** to `/usr/sbin/pct exec`

The sudoers rule that enforces this is:

```
mcp-agent ALL=(root) NOPASSWD: /usr/sbin/pct exec *
```

This means `mcp-agent` can run `pct exec` as root (required by `lxc-attach`), but cannot run any
other command via sudo — not `apt`, not `rm`, not `pct start` or `pct stop`, nothing else.

### What a compromised MCP server can and cannot do

If the MCP server is compromised and an attacker gains access to the `mcp-agent` SSH key, this is
what they can and cannot do on your Proxmox nodes:

| Action | Possible? |
|---|---|
| Execute commands inside any running LXC container | Yes |
| Start, stop, or delete containers or VMs | No |
| Modify VM/container configurations | No |
| Access Proxmox storage directly | No |
| Change firewall rules or network configuration | No |
| Read or modify files on the Proxmox host itself | No |
| Escalate privileges beyond `pct exec` | No |
| Log in to the Proxmox host interactively | No (key-based SSH only, no password) |

The attack surface is limited to what can be done by running commands inside containers —
which is the same surface that already exists if an attacker compromises a container directly.

### SSH host key checking

The implementation now uses strict host key checking by default (`RejectPolicy`), which means
unknown hosts are rejected unless the host key is present in `known_hosts` (system-level or
configured `known_hosts_file`). This is the recommended production posture. You can explicitly
disable strict checking only for local development.

### Key management

The SSH private key stays on the MCP VM and is never transmitted. Use a dedicated keypair
(`~/.ssh/proxmox_key`) rather than a shared key. Restrict file permissions:

```bash
chmod 600 ~/.ssh/proxmox_key
```

---

## Setup Instructions

### Step 1: Install `sudo` on each Proxmox node

Proxmox VE is Debian-based but does not ship with `sudo` installed by default. On each Proxmox
node, as root:

```bash
apt install sudo
```

---

### Step 2: Create the `mcp-agent` user on each Proxmox node

On each Proxmox node, as root:

```bash
useradd -m -s /bin/bash mcp-agent
```

- `-m` creates a home directory at `/home/mcp-agent`, needed to store `authorized_keys`.
- `-s /bin/bash` gives the account a shell so SSH sessions work correctly.
- No password is set intentionally. The account starts in a locked state and can only be
  authenticated via SSH key, added in a later step.

---

### Step 3: Grant scoped `sudo` access to `pct exec`

On each Proxmox node, as root:

```bash
echo 'mcp-agent ALL=(root) NOPASSWD: /usr/sbin/pct exec *' > /etc/sudoers.d/mcp-agent
chmod 440 /etc/sudoers.d/mcp-agent
visudo -c -f /etc/sudoers.d/mcp-agent
```

**What the sudoers rule means:**
- `mcp-agent` — this rule applies to the `mcp-agent` user only.
- `ALL=` — from any terminal/host (SSH sessions don't have a fixed TTY origin).
- `(root)` — the command runs as root, which `pct exec` requires because it calls `lxc-attach`.
- `NOPASSWD:` — no password prompt. Required because the MCP server runs unattended.
- `/usr/sbin/pct exec *` — only this exact binary with any arguments is permitted. No other
  command can be run via sudo.

**Why `chmod 440`:** `sudo` refuses to read sudoers files with looser permissions as a security
measure.

**Why `visudo -c`:** validates the syntax before the file takes effect. A malformed sudoers file
can lock out all sudo access on the system. Expected output:

```
/etc/sudoers.d/mcp-agent: parsed OK
```

---

### Step 4: Generate an SSH keypair on the MCP VM

On the MCP VM, as the user running the MCP server:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/proxmox_key -N ""
```

- `ed25519` is a modern elliptic curve algorithm — smaller keys, faster, and more secure than RSA.
- `-f ~/.ssh/proxmox_key` saves the private key to this path. The public key is written to
  `proxmox_key.pub` automatically.
- `-N ""` sets an empty passphrase so the MCP server can use the key unattended.

Get the public key content to use in the next step:

```bash
cat ~/.ssh/proxmox_key.pub
```

The output is a single line starting with `ssh-ed25519`. Copy it entirely.

---

### Step 5: Install the public key on each Proxmox node

On each Proxmox node, as root:

```bash
mkdir -p /home/mcp-agent/.ssh && chmod 700 /home/mcp-agent/.ssh
echo "ssh-ed25519 AAAA...your key here..." >> /home/mcp-agent/.ssh/authorized_keys
chmod 600 /home/mcp-agent/.ssh/authorized_keys
chown -R mcp-agent:mcp-agent /home/mcp-agent/.ssh
```

**Why these permissions matter:** `sshd` enforces strict permission checks on `.ssh` and
`authorized_keys`. If the directory or file is world-readable or owned by another user, `sshd`
silently ignores the `authorized_keys` file and falls back to password auth — which is locked, so
the connection would be refused.

- `.ssh` must be `700` (only the owner can read/write/enter it)
- `authorized_keys` must be `600` (only the owner can read/write it)
- Both must be owned by `mcp-agent`

---

### Step 6: Verify SSH access from the MCP VM

From the MCP VM:

```bash
# Basic connectivity test
ssh -i ~/.ssh/proxmox_key mcp-agent@pve1 "echo SSH OK"

# End-to-end test: sudo + pct exec (replace 101 with a real running container ID)
ssh -i ~/.ssh/proxmox_key mcp-agent@pve1 "sudo /usr/sbin/pct exec 101 -- uname -a"
```

Both should succeed without any password prompt. If the first works but the second fails, check
the sudoers rule on that node.

---

### Step 7: Add the `ssh` section to the MCP config JSON

```json
{
  "proxmox": { "...": "..." },
  "auth": { "...": "..." },
  "logging": { "...": "..." },
  "ssh": {
    "user": "mcp-agent",
    "key_file": "/home/<your-user>/.ssh/proxmox_key",
    "use_sudo": true
  }
}
```

- `user` must match the account created on the Proxmox nodes.
- `key_file` is the path to the **private** key on the MCP VM (no `.pub` extension).
- `use_sudo: true` tells the MCP server to prefix the `pct exec` call with `sudo`, required
  because `mcp-agent` is not root.

**Optional — if Proxmox node names don't resolve via DNS from the MCP VM**, add `host_overrides`
to map node names to IPs directly:

```json
{
  "ssh": {
    "user": "mcp-agent",
    "key_file": "/home/<your-user>/.ssh/proxmox_key",
    "use_sudo": true,
    "host_overrides": {
      "pve1": "192.168.1.101",
      "pve2": "192.168.1.102"
    }
  }
}
```

The node names in `host_overrides` must match exactly what the `get_nodes` tool returns, since
that is how the MCP server identifies which node to SSH into for a given container.

---

## How it Works at Runtime

### `execute_container_command`

When `execute_container_command` is called with a selector like `101`:

1. The MCP server queries the Proxmox API to find which node container `101` lives on (e.g.
   `pve1`) and verifies it is in `running` state.
2. It opens an SSH connection to `pve1` (or the override IP if configured) using the
   `mcp-agent` key.
3. It runs: `sudo /usr/sbin/pct exec '101' -- sh -c '<your command>'`
4. `sudo` checks the sudoers rule, confirms `pct exec` is allowed, and runs it as root.
5. `pct exec` calls `lxc-attach` to enter container `101`'s namespaces and executes the
   command inside it.
6. stdout, stderr, and the exit code are captured over SSH and returned as JSON.

### `update_container_ssh_keys`

When `update_container_ssh_keys` is called:

1. The server identifies the target node and verifies the container is running.
2. It SSHes to the Proxmox host.
3. It executes a series of commands via `sudo pct exec` to:
   - Create `/root/.ssh` if it doesn't exist.
   - Set directory permissions to `700`.
   - Append or replace keys in `/root/.ssh/authorized_keys` using `printf`.
   - Set file permissions to `600`.
4. The result is returned as a success/failure JSON payload.

---

## Troubleshooting
   ```json
   {"success": true, "output": "...", "error": "", "exit_code": 0}
   ```
