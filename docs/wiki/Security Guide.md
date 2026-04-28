# Security Guide

This guide covers the main security boundaries and hardening steps for ProxmoxMCP-Plus.

## Security Model Overview

ProxmoxMCP-Plus sits between clients and the Proxmox API. The main controls are:

- Proxmox API token authentication
- TLS verification for Proxmox API connections
- optional API key protection for OpenAPI exposure
- command policy checks for `execute_*` tools
- optional SSH configuration for container command execution

## Basic Controls

- Use least-privilege Proxmox API tokens
- Keep `proxmox.verify_ssl=true`
- Only use `security.dev_mode=true` for local development
- Restrict who can reach the OpenAPI endpoint
- Keep logs for sensitive operations

## TLS Safety

The config loader rejects insecure TLS in normal operation.

If `proxmox.verify_ssl=false` and `security.dev_mode=false`, startup fails with a validation error.

This is an intentional guardrail to avoid quietly running against a Proxmox API endpoint without certificate verification.

## Command Policy

Command execution tools are protected by `command_policy`.

Supported modes:

- `deny_all`: block commands unless they match `allow_patterns`
- `allowlist`: also requires matching `allow_patterns`
- `audit_only`: allow commands but still evaluate the rules

Other controls:

- `deny_patterns`: blocks known-dangerous patterns
- `require_approval_token`: requires a caller-supplied token
- `approval_token`: token value checked by the server

Default deny patterns in the config model already block common destructive shell patterns such as `rm -rf`.

## VM Command Execution

`execute_vm_command` depends on QEMU Guest Agent inside the guest VM.

Implications:

- the VM must be running
- the guest agent must be installed and reachable
- command results come back through the agent channel, not SSH

## Container Command Execution

`execute_container_command` and `update_container_ssh_keys` are optional.

These tools only register when the config includes an `ssh` section. Without it:

- no SSH connection is attempted
- the tools do not appear at all

The implementation SSHes to the Proxmox node and runs `pct exec`. Because this path is more powerful than pure API reads, treat it as a separate security decision.

Read the full setup and threat model in [Container Command Execution](Container-Command-Execution).

## OpenAPI Exposure

If you run the OpenAPI proxy:

- configure an API key when the service is not strictly local
- place it behind TLS termination
- restrict ingress to networks you control
- monitor `/health`
- avoid exposing it directly to the public internet without additional controls

## Credential Handling

- Keep Proxmox API tokens out of committed source files
- Use a dedicated config file or environment variables per environment
- If using SSH for container execution, use a dedicated keypair for this service
- Rotate API tokens and SSH keys on a schedule that fits your environment

## Hardening Checklist

- Restrict ingress to networks you control
- Keep OpenAPI behind a reverse proxy you manage
- Use per-environment credentials
- Keep `dev_mode` off outside local testing
- Review command policy after enabling or expanding command tools
- Verify host key checking if you enable SSH-backed container commands

## Related Pages

- [Operator Guide](Operator-Guide)
- [Container Command Execution](Container-Command-Execution)
- [Troubleshooting](Troubleshooting)
