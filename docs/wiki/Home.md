# ProxmoxMCP-Plus Wiki

This wiki contains the longer documentation for ProxmoxMCP-Plus.

ProxmoxMCP-Plus is an MCP server and OpenAPI bridge for Proxmox VE. It lets MCP-capable assistants, WebUI tools, and HTTP clients work with VMs, LXC containers, snapshots, backups, storage, and cluster state through one service.

## Start Here

- First-time deployment: [Operator Guide](Operator-Guide)
- Local setup and contribution flow: [Developer Guide](Developer-Guide)
- Security settings and command policy: [Security Guide](Security-Guide)
- Client integration examples: [Integrations Guide](Integrations-Guide)
- Tool-by-tool capability index: [API & Tool Reference](API-&-Tool-Reference)
- Common failures and recovery steps: [Troubleshooting](Troubleshooting)
- Version tracking and upgrade notes: [Release & Upgrade Notes](Release-&-Upgrade-Notes)

## What This Project Does

- Exposes Proxmox operations as MCP tools
- Optionally exposes the same operations over HTTP through an OpenAPI proxy
- Supports VM lifecycle actions such as create, start, stop, shutdown, reset, and delete
- Supports LXC listing, creation, resource updates, start/stop/restart, config reads, IP discovery, and deletion
- Supports snapshots, backup creation, backup restore, ISO browsing, template browsing, node status, storage status, and cluster status
- Adds policy checks around command execution tools

## Architecture Summary

- `main.py` starts the MCP server bundle
- `src/proxmox_mcp/server.py` registers MCP tools
- `src/proxmox_mcp/openapi_proxy.py` wraps the MCP server behind FastAPI and adds `/`, `/docs`, `/openapi.json`, and `/health`
- `src/proxmox_mcp/config/` contains validation for JSON and environment-based configuration
- `src/proxmox_mcp/security/command_policy.py` evaluates command execution requests against allow and deny rules
- `docs/container-command-execution.md` explains the SSH-based LXC command flow

## Documentation Layout

- Use the root `README.md` for a quick product overview and minimal startup steps
- Use this wiki for setup details, operating guidance, and tool behavior
- Keep page titles stable so README and external links do not break

## Quick Navigation

| Topic | Use it for |
| --- | --- |
| [Operator Guide](Operator-Guide) | Config, runtime modes, Docker/OpenAPI deployment, health checks |
| [Developer Guide](Developer-Guide) | Local install, test commands, code layout, release workflow |
| [Security Guide](Security-Guide) | TLS, token handling, `dev_mode`, command policy, SSH-based container execution |
| [Integrations Guide](Integrations-Guide) | Claude Desktop, OpenCode, OpenAPI clients |
| [API & Tool Reference](API-&-Tool-Reference) | Exact tool groups, parameters, prerequisites, and output expectations |
| [Troubleshooting](Troubleshooting) | Startup failures, auth issues, tool registration problems, health check issues |
| [Release & Upgrade Notes](Release-&-Upgrade-Notes) | Release entries, upgrade checklist, rollback notes |
