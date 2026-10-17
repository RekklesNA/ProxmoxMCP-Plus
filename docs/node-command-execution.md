# Guarded commands on Proxmox nodes

`execute_node_command` executes a shell command on a Proxmox host through SSH.
It is disabled by default and separate from `execute_container_command`.
The selected target must explicitly configure `ssh.allow_node_commands=true`.
When no target enables it, the tool is absent from the MCP catalog.

## Configuration

Merge these settings into the target's existing API and SSH configuration:

```json
{
  "ssh": {
    "user": "operator",
    "key_file": "~/.ssh/proxmox_operator",
    "known_hosts_file": "~/.ssh/known_hosts",
    "strict_host_key_checking": true,
    "use_sudo": false,
    "allow_node_commands": true
  },
  "command_policy": {
    "mode": "allowlist",
    "allow_patterns": ["id", "uptime"],
    "require_approval_token": true,
    "approval_token": "replace-with-a-private-approval-secret",
    "high_risk_mode": "enforce",
    "high_risk_require_approval_token": true
  }
}
```

For named targets, place both sections inside that target. Do not configure
top-level SSH settings alongside named targets. Existing client grants must also
permit `execute_node_command` and the selected target. Read-only targets reject it.
This opt-in is configured in the JSON file; there is no new environment variable.

Node commands require a full match of an allow pattern. For example, `id` permits
`id` but rejects `id; whoami` and `id -u`. Deny patterns retain regex search.
Guest command tools retain their existing regex search behavior. Broad patterns
can authorize compound shell commands; an allowlist is not a shell sandbox.
`high_risk_mode=disabled` disables the additional operation policy, not the tool.

The node name must appear in the authenticated Proxmox API node inventory before
an SSH destination is resolved. SSH host overrides remain operator-controlled.
Paramiko rejects unknown host keys; OpenSSH uses the configured host key policy.

## Execution and results

```text
execute_node_command(node="pve1", command="uptime", approval_token="...", target="lab")
```

Commands are limited to 8,192 characters. A remote GNU `timeout` watchdog applies
a 60-second limit with a 5-second termination grace; SSH waits and captured output
are bounded. Each stream is capped at 1 MiB. Results report `success`, `exit_code`,
`output`, `error`, `output_truncated`, and timeout metadata when applicable.
Inspect host state before repeating a timed-out command: partial changes can occur.
Detached processes can outlive a shell watchdog; this facility is not process isolation.

Use a restricted SSH identity. With `use_sudo=true`, the entire timeout/shell
wrapper runs under sudo; permission to run that wrapper permits arbitrary commands
as the elevated identity. For narrowly scoped sudo rules, keep `use_sudo=false`
and allow only explicitly approved individual sudo commands. Do not assume Proxmox
API token permissions limit an SSH identity's host privileges.
