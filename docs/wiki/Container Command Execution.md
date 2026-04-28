# Container Command Execution

This page restores the wiki entry for SSH-backed LXC command execution.

The canonical setup guide lives in the repository docs:

- [Container Command Execution and SSH Management](../container-command-execution.md)

Use that guide when you need to enable:

- `execute_container_command`
- `update_container_ssh_keys`

Quick summary:

- These tools are registered only when the MCP config includes an `ssh` section.
- The recommended setup is a dedicated `mcp-agent` SSH user on every Proxmox node.
- Grant that user passwordless sudo only for `/usr/sbin/pct exec *`.
- Add the Proxmox node host keys to `known_hosts`, or use `prefer_ssh_client=true` if you need OpenSSH config behavior.
- Configure `command_policy` so agents can only run the container commands you intend to allow.

Related pages:

- [Operator Guide](Operator-Guide)
- [Security Guide](Security-Guide)
- [API & Tool Reference](API-&-Tool-Reference)
