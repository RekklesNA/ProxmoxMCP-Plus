# Run commands over SSH inside a Linux VM

`execute_vm_command` defaults to the QEMU Guest Agent. An administrator can
enable SSH for individual Linux VMs by adding a `vm_ssh` profile keyed by VMID.
Use the top level for a legacy single-target configuration, or add it inside
the appropriate entry under `targets`.

```json
{
  "vm_ssh": {
    "101": {
      "host": "192.0.2.101",
      "port": 22,
      "user": "mcp-guest",
      "key_file": "/run/secrets/vm101_ssh_key",
      "known_hosts_file": "/run/secrets/vm101_known_hosts",
      "prefer_ssh_client": false
    }
  }
}
```

Use a guest account limited to the tasks it needs, a private key readable by
the server, and a known-hosts file containing the guest host key verified
through a trusted source. Mount both files read-only when running in Docker.
The MCP server must be able to reach the configured guest address. The VM
needs an SSH server, `/bin/sh` and GNU `/usr/bin/timeout`. `prefer_ssh_client: true`
uses system OpenSSH instead of Paramiko. Both verify the guest against the
configured known-hosts file and use the configured identity.

Pass `"transport": "ssh"` alongside `node`, `vmid` and `command`. For a
multi-target server also pass `target`. The Proxmox API must confirm that the
VM is running on that node. Authorize the MCP caller and configure the target's
command policy to allow the entire command string, including any arguments.
Approval tokens and read-only target restrictions still apply. The command
runs with the permissions of the guest SSH account.

The command has a 60-second guest deadline with five seconds of termination
grace and bounded output. A timeout or lost SSH result can leave partial
changes. Check guest state before retrying. Each tool call attempts just the
selected transport. If you omit `transport`, the tool continues to use the
Guest Agent, including on VMs with an SSH profile.
