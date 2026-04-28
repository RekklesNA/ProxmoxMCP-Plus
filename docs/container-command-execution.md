# Container Command Execution and SSH Management

## Overview

ProxmoxMCP-Plus includes tools that require direct CLI access to the Proxmox host via SSH to interact
with LXC containers:

1. **`execute_container_command`**: Run shell commands inside a running LXC container.
2. **`update_container_ssh_keys`**: Inject or replace SSH authorized_keys for the `root` user inside a container.

Under the hood, both tools use `pct exec`, the official Proxmox CLI tool for executing commands
within container namespaces.

This feature requires a one-time SSH setup on your Proxmox nodes. It is **entirely opt-in**: if
you do not add an `ssh` section to your MCP config, these tools are not registered and will not
appear in the MCP tool list. Everything else continues to work normally.

## Why SSH?

The Proxmox REST API exposes a QEMU guest agent endpoint that lets you run commands inside virtual
machines:

```text
POST /nodes/{node}/qemu/{vmid}/agent/exec
```

LXC containers have no equivalent REST endpoint. `pct exec` is the official mechanism, and it is a
CLI tool that runs on the Proxmox host itself. It uses `lxc-attach` internally to enter the
container's Linux namespaces.

In a multi-node cluster, containers can be on any node. The MCP server resolves which node a
container is on through the Proxmox API first, then SSHes to that node, so the correct node is
targeted automatically.

## Security Model

### The feature is opt-in

`execute_container_command` and `update_container_ssh_keys` are only registered when an `ssh`
section is present in the config.

No `ssh` section -> no tool registration -> no SSH connection -> no container command execution.

### Recommended setup: dedicated `mcp-agent` user with scoped sudo

Rather than granting the MCP server SSH access as `root`, create a dedicated unprivileged
`mcp-agent` user on each Proxmox node. This user:

- Has no password
- Authenticates only through an SSH key
- Has passwordless `sudo` access scoped exclusively to `/usr/sbin/pct exec`

The sudoers rule that enforces this is:

```text
mcp-agent ALL=(root) NOPASSWD: /usr/sbin/pct exec *
```

This means `mcp-agent` can run `pct exec` as root, which is required by `lxc-attach`, but cannot
run other commands through sudo.

### SSH host key checking

The Paramiko execution path uses strict host key checking. Unknown hosts are rejected unless the
host key is present in the system `known_hosts` file or in the configured `known_hosts_file`.

`strict_host_key_checking=false` does not make Paramiko auto-trust unknown hosts. If you need host
key behavior controlled by your local OpenSSH client configuration, set `prefer_ssh_client=true`.

### Command policy

Container command execution also passes through the configured `command_policy`. The default mode is
`deny_all`, so commands are blocked unless you either:

- Add matching `allow_patterns`, or
- Set `command_policy.mode` to `audit_only` for a trusted lab environment

Production deployments should prefer an allowlist.

## Setup Instructions

### Step 1: Install `sudo` on each Proxmox node

Proxmox VE is Debian-based but may not have `sudo` installed. On each Proxmox node, as root:

```bash
apt update
apt install sudo
```

### Step 2: Create the `mcp-agent` user on each Proxmox node

On each Proxmox node, as root:

```bash
useradd -m -s /bin/bash mcp-agent
passwd -l mcp-agent
```

`-m` creates `/home/mcp-agent`, which is needed for `authorized_keys`. The locked password keeps
the account key-only.

### Step 3: Grant scoped sudo access to `pct exec`

On each Proxmox node, as root:

```bash
echo 'mcp-agent ALL=(root) NOPASSWD: /usr/sbin/pct exec *' > /etc/sudoers.d/mcp-agent
chmod 440 /etc/sudoers.d/mcp-agent
visudo -c -f /etc/sudoers.d/mcp-agent
```

Expected validation output:

```text
/etc/sudoers.d/mcp-agent: parsed OK
```

### Step 4: Generate an SSH keypair on the machine running ProxmoxMCP-Plus

Run this as the same OS user that starts the MCP server:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/proxmox_key -N ""
chmod 600 ~/.ssh/proxmox_key
cat ~/.ssh/proxmox_key.pub
```

Copy the full public key line that starts with `ssh-ed25519`.

### Step 5: Install the public key on each Proxmox node

On each Proxmox node, as root:

```bash
mkdir -p /home/mcp-agent/.ssh
chmod 700 /home/mcp-agent/.ssh
echo "ssh-ed25519 AAAA...your key here..." >> /home/mcp-agent/.ssh/authorized_keys
chmod 600 /home/mcp-agent/.ssh/authorized_keys
chown -R mcp-agent:mcp-agent /home/mcp-agent/.ssh
```

The permissions matter. `sshd` can ignore `authorized_keys` if the directory or file is writable by
the wrong user.

### Step 6: Add host keys to `known_hosts`

From the machine running ProxmoxMCP-Plus:

```bash
ssh-keyscan -H pve1 >> ~/.ssh/known_hosts
ssh-keyscan -H pve2 >> ~/.ssh/known_hosts
```

Replace `pve1` and `pve2` with your node names or IP addresses. If node names do not resolve from
the MCP host, use the IPs here and configure `host_overrides` in the next step.

### Step 7: Verify SSH and `pct exec`

From the machine running ProxmoxMCP-Plus:

```bash
ssh -i ~/.ssh/proxmox_key mcp-agent@pve1 "echo SSH OK"
ssh -i ~/.ssh/proxmox_key mcp-agent@pve1 "sudo /usr/sbin/pct exec 101 -- uname -a"
```

Replace `101` with a real running container ID. Both commands should complete without a password
prompt.

### Step 8: Add the `ssh` section to the MCP config JSON

Add this to `proxmox-config/config.json`:

```json
{
  "ssh": {
    "user": "mcp-agent",
    "port": 22,
    "key_file": "/home/<your-user>/.ssh/proxmox_key",
    "use_sudo": true,
    "known_hosts_file": "/home/<your-user>/.ssh/known_hosts",
    "strict_host_key_checking": true
  }
}
```

If Proxmox node names do not resolve from the MCP host, add `host_overrides`:

```json
{
  "ssh": {
    "user": "mcp-agent",
    "port": 22,
    "key_file": "/home/<your-user>/.ssh/proxmox_key",
    "use_sudo": true,
    "known_hosts_file": "/home/<your-user>/.ssh/known_hosts",
    "host_overrides": {
      "pve1": "192.168.1.101",
      "pve2": "192.168.1.102"
    }
  }
}
```

The `host_overrides` keys must match the node names returned by `get_nodes`.

### Step 9: Allow the commands you intend to run

With the default `command_policy.mode=deny_all`, add allow patterns for the commands you want agents
to run. Example:

```json
{
  "command_policy": {
    "mode": "allowlist",
    "allow_patterns": [
      "^uname(\\s|$)",
      "^df\\s+-h(\\s|$)",
      "^cat\\s+/etc/os-release$",
      "^systemctl\\s+status\\s+[a-zA-Z0-9_.@-]+$"
    ],
    "deny_patterns": [
      "(^|\\s)rm\\s+-rf(\\s|$)",
      ":\\(\\)\\{:\\|:\\&\\};:"
    ],
    "require_approval_token": false,
    "approval_token": null
  }
}
```

For a private lab, you can temporarily use:

```json
{
  "command_policy": {
    "mode": "audit_only"
  }
}
```

### Step 10: Restart and verify the MCP tool list

Restart ProxmoxMCP-Plus after changing the config. The startup log should include:

```text
Container command execution enabled (SSH configured for user 'mcp-agent')
```

Then verify that the tool list includes:

- `execute_container_command`
- `update_container_ssh_keys`

## How It Works At Runtime

### `execute_container_command`

When `execute_container_command` is called with a selector such as `101`:

1. The server resolves the selector to a container and node through the Proxmox API.
2. It verifies the container is running.
3. It checks the configured command policy.
4. It opens an SSH connection to the node, or to the configured `host_overrides` value.
5. It runs `sudo /usr/sbin/pct exec 101 -- sh -c '<command>'`.
6. It returns stdout, stderr, and exit code.

Successful response shape:

```json
{
  "success": true,
  "output": "Linux ct-101 ...",
  "error": "",
  "exit_code": 0
}
```

### `update_container_ssh_keys`

When `update_container_ssh_keys` is called:

1. The server identifies the target node and verifies the container is running.
2. It SSHes to the Proxmox host.
3. It executes `pct exec` commands to create `/root/.ssh`, write `authorized_keys`, and set file permissions.
4. It returns a success or failure payload.

## Troubleshooting

### The tool does not appear

Most likely causes:

- The running config has no `ssh` section.
- The MCP server was not restarted after editing `config.json`.
- The client cached an older tool list.

Check the server log for either:

```text
Container command execution enabled (SSH configured for user 'mcp-agent')
Container command execution disabled (no [ssh] section in config)
```

### SSH works manually, but the tool fails with host key errors

Paramiko does not automatically inherit every OpenSSH behavior. Use one of these fixes:

- Add the node host key to the system `known_hosts`.
- Set `ssh.known_hosts_file` to the file that contains the host key.
- Set `ssh.prefer_ssh_client=true` if you need your local OpenSSH config to control host key behavior.

### SSH connects, but `pct exec` fails with sudo errors

Run this manually from the MCP host:

```bash
ssh -i ~/.ssh/proxmox_key mcp-agent@pve1 "sudo -n /usr/sbin/pct exec 101 -- true"
```

If it fails, re-check `/etc/sudoers.d/mcp-agent` on that Proxmox node.

### The command is blocked by policy

If the response mentions `CMD_POLICY_NOT_ALLOWLISTED`, your `command_policy` blocked the command.
Add a precise allow pattern or use `audit_only` only in a trusted lab.

### The container is reported as not running

`pct exec` only works for running containers. Start the container first, or select a different
container.

### Node names do not resolve

If `get_nodes` returns node names such as `pve1`, but DNS does not resolve those names from the MCP
host, configure `ssh.host_overrides` with node-name-to-IP mappings.
