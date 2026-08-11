# Security Guide

This guide covers the main security boundaries and hardening steps for ProxmoxMCP-Plus.

## Security Model Overview

ProxmoxMCP-Plus sits between clients and the Proxmox API. The main controls are:

- Proxmox API token authentication
- TLS verification for Proxmox API connections
- required API key protection for OpenAPI exposure, unless `PROXMOX_ALLOW_NO_AUTH=true` is explicitly set for local development
- optional `MCP_API_KEY` Bearer protection for native Streamable HTTP exposure
- MCP transport DNS rebinding protection and Host/Origin allowlists for Streamable HTTP deployments
- command policy checks for `execute_*` tools
- optional SSH configuration for container command execution

## Basic Controls

- Use least-privilege Proxmox API tokens
- Keep `proxmox.verify_ssl=true`
- Only use `security.dev_mode=true` for local development
- Set `PROXMOX_API_KEY` before starting OpenAPI mode
- Set a separate `MCP_API_KEY` before exposing native Streamable HTTP beyond a trusted local environment
- Keep MCP DNS rebinding protection enabled when exposing Streamable HTTP through a reverse proxy
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

The implementation SSHes to the Proxmox node and runs `pct exec`. Because this path is more powerful than pure API reads, treat it as a separate security decision. `update_container_ssh_keys` is classified as a high-risk operation and follows `command_policy.high_risk_*` approval settings.

Read the full setup and threat model in [Container Command Execution](Container-Command-Execution).

## OpenAPI Exposure

If you run the OpenAPI proxy:

- configure `PROXMOX_API_KEY`; startup refuses no-auth mode unless `PROXMOX_ALLOW_NO_AUTH=true` is set
- place it behind TLS termination
- restrict ingress to networks you control
- monitor unauthenticated `/livez` for process liveness and authenticated `/health` or `/readyz` for backend readiness
- avoid exposing it directly to the public internet without additional controls

## MCP HTTP Host Validation

Native Streamable HTTP MCP deployments can configure DNS rebinding protection through the `mcp` config section or environment variables.

Set `MCP_API_KEY` to require `Authorization: Bearer <MCP_API_KEY>` on the native
`/mcp` endpoint. Missing, malformed, or incorrect credentials receive `401 Unauthorized`
with `WWW-Authenticate: Bearer`. The token is compared in constant time. This setting is
independent of `PROXMOX_API_KEY`, which protects only the OpenAPI service on port `8811`.

For backward compatibility, leaving `MCP_API_KEY` unset keeps the native endpoint
unauthenticated and emits a startup warning. Do not rely on Host or Origin validation as
caller authentication: those settings mitigate DNS rebinding but do not identify clients.

Recommended reverse proxy settings:

```json
{
  "mcp": {
    "host": "0.0.0.0",
    "port": 8000,
    "transport": "STREAMABLE_HTTP",
    "dns_rebinding_protection": true,
    "allowed_hosts": ["mcp.example.com:*", "localhost:*"],
    "allowed_origins": ["https://mcp.example.com"]
  }
}
```

If these fields are omitted, ProxmoxMCP-Plus leaves transport-security defaults to the installed MCP SDK. Set `dns_rebinding_protection=false` only for a trusted local development setup.

When Caddy or another reverse proxy is used, disable response buffering for
`text/event-stream` traffic. For Caddy, `flush_interval -1` prevents Streamable HTTP SSE
responses from being delayed behind the proxy buffer.

## Credential Handling

- Keep Proxmox API tokens out of committed source files
- Keep `MCP_API_KEY` and `PROXMOX_API_KEY` out of committed source files and rotate them independently
- Use a dedicated config file or environment variables per environment
- If using SSH for container execution, use a dedicated keypair for this service
- Rotate API tokens and SSH keys on a schedule that fits your environment

## Hardening Checklist

- Restrict ingress to networks you control
- Require `MCP_API_KEY` for every remotely reachable native `/mcp` endpoint
- Keep OpenAPI behind a reverse proxy you manage
- Use per-environment credentials
- Keep `dev_mode` off outside local testing
- Review command policy after enabling or expanding command tools
- Verify host key checking if you enable SSH-backed container commands

## Related Pages

- [Operator Guide](Operator-Guide)
- [Container Command Execution](Container-Command-Execution)
- [Troubleshooting](Troubleshooting)
