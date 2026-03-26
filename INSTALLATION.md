## Configuration

Set environment variables **or** create a config file:

```bash
# Option A: environment variables
export PROXMOX_HOST=your-proxmox.host
export PROXMOX_USER=root@pam
export PROXMOX_TOKEN_NAME=your-token-name
export PROXMOX_TOKEN_VALUE=your-token-value
export PROXMOX_SSH_USER=root
export PROXMOX_SSH_KEY=~/.ssh/id_rsa
```

```bash
# Option B: config file in the skill directory (recommended)
cp ~/.claude/skills/proxmox/config.example.json ~/.claude/skills/proxmox/config.json
# Edit with your values
```

```bash
# Option C: global fallback
mkdir -p ~/.config/proxmox
cp ~/.claude/skills/proxmox/config.example.json ~/.config/proxmox/config.json
# Edit with your values
```

`pxas` searches for `config.json` (copied to deployment directory by uv install) next to `SKILL.md` first, then `~/.config/proxmox/`. Override with `PROXMOX_CONFIG=/path/to/config.json`.

- **Config Expansion:** Use `${VAR}` in `config.json` for environment variable expansion.

| Key | Env Var | Default | Description |
|-----|---------|---------|-------------|
| `proxmox.host` | `PROXMOX_HOST` | — | Proxmox host address |
| `proxmox.port` | `PROXMOX_PORT` | `8006` | API port |
| `proxmox.verify_ssl` | `PROXMOX_VERIFY_SSL` | `false` | SSL verification |
| `auth.user` | `PROXMOX_USER` | — | e.g. `root@pam` |
| `auth.token_name` | `PROXMOX_TOKEN_NAME` | — | API token name |
| `auth.token_value` | `PROXMOX_TOKEN_VALUE` | — | API token secret |
| `ssh.user` | `PROXMOX_SSH_USER` | `root` | SSH user |
| `ssh.key_file` | `PROXMOX_SSH_KEY` | — | SSH private key path |
| `ssh.password` | `PROXMOX_SSH_PASSWORD` | — | SSH password (not recommended) |
| `ssh.use_sudo` | — | `false` | Prefix `pct exec` with `sudo` (required for non-root SSH users) |
| `ssh.host_overrides` | — | `{}` | Map node names to IPs/hostnames when DNS doesn't resolve them |
| `ssh.strict_host_key_checking` | — | `false` | Reject unknown SSH host keys (`RejectPolicy`); set `true` after adding nodes to `known_hosts` |

---

# Installation

## Prerequisites

Install [uv](https://docs.astral.sh/uv/getting-started/installation/):

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## Claude Code

```bash
git clone https://github.com/codeandsolder/proxmox-agent-skill.git ~/.claude/skills/proxmox
cd ~/.claude/skills/proxmox
uv tool install . --reinstall
```

Claude Code discovers the skill automatically via `SKILL.md`. No registration needed.

## OpenCode

```bash
git clone https://github.com/codeandsolder/proxmox-agent-skill.git ~/.opencode/skills/proxmox
cd ~/.opencode/skills/proxmox
uv tool install . --reinstall
```

`uv` installs `pxas` as a globally available command. Verify with `pxas --help`.

---

## SSH Setup (for `execute_command` / `wait_until`)

`ct.execute_command()` and `ct.wait_until()` SSH into the Proxmox node and run `pct exec` to enter the container. This requires a one-time SSH setup. **Without this, all other features work normally** — only container command execution is unavailable.

### Why SSH?

The Proxmox REST API has no `pct exec` equivalent for LXC containers. `pct exec` is a CLI tool on the host that uses `lxc-attach` internally — a kernel-level operation with no API surface. SSH is the only way to reach it.

### Step 1: Install `sudo` (Proxmox nodes)

Proxmox doesn't ship `sudo` by default. On each node as root:

```bash
apt install sudo
```

### Step 2: Create `pxas-agent` user (Proxmox nodes)

On each node as root:

```bash
useradd -m -s /bin/bash pxas-agent
```

No password is set. The account can only authenticate via SSH key.

### Step 3: Grant scoped sudo (Proxmox nodes)

On each node as root:

```bash
echo 'pxas-agent ALL=(root) NOPASSWD: /usr/sbin/pct exec *' > /etc/sudoers.d/pxas-agent
chmod 440 /etc/sudoers.d/pxas-agent
visudo -c -f /etc/sudoers.d/pxas-agent
```

This lets `pxas-agent` run only `pct exec` as root — nothing else. Verify with `visudo` (expected: `parsed OK`).

### Step 4: Generate SSH keypair (agent machine)

```bash
ssh-keygen -t ed25519 -f ~/.ssh/proxmox_key -N ""
cat ~/.ssh/proxmox_key.pub
```

### Step 5: Install public key (Proxmox nodes)

On each node as root, paste the public key:

```bash
mkdir -p /home/pxas-agent/.ssh && chmod 700 /home/pxas-agent/.ssh
echo "ssh-ed25519 AAAA...your key..." >> /home/pxas-agent/.ssh/authorized_keys
chmod 600 /home/pxas-agent/.ssh/authorized_keys
chown -R pxas-agent:pxas-agent /home/pxas-agent/.ssh
```

Permissions must be exact — `sshd` silently ignores `authorized_keys` if permissions are wrong.

### Step 6: Verify

```bash
ssh -i ~/.ssh/proxmox_key pxas-agent@pve1 "echo SSH OK"
ssh -i ~/.ssh/proxmox_key pxas-agent@pve1 "sudo /usr/sbin/pct exec 101 -- uname -a"
```

Both should succeed without a password prompt.

### Step 7: Update config.json

```json
{
    "ssh": {
        "user": "pxas-agent",
        "key_file": "~/.ssh/proxmox_key",
        "use_sudo": true,
        "host_overrides": {},
        "strict_host_key_checking": false
    }
}
```

- `use_sudo: true` is required because `pxas-agent` is not root.
- Add `host_overrides` if node names don't resolve via DNS:
  ```json
  "host_overrides": {
      "pve1": "192.168.1.101",
      "pve2": "192.168.1.102"
  }
  ```

### Security summary

| Action | Compromised agent can do? |
|--------|--------------------------|
| Execute commands inside containers | Yes |
| Start/stop/delete containers or VMs | No |
| Modify configurations | No |
| Access Proxmox host files | No |
| Log in interactively | No (key-only, no password) |
| Run commands other than `pct exec` | No (sudoers scoped) |

> **Note:** The SSH client uses `AutoAddPolicy` by default (`strict_host_key_checking: false`), which silently accepts new host keys on first connection. For applications of national security concern, populate `~/.ssh/known_hosts` with the node's key beforehand and set `"strict_host_key_checking": true` in `config.json`.
