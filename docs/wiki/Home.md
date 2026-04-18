# ProxmoxMCP-Plus Wiki

This wiki is the longer-form documentation hub for ProxmoxMCP-Plus.

ProxmoxMCP-Plus gives you one Proxmox VE control surface for both:

- MCP clients such as Claude Desktop and Open WebUI
- HTTP and OpenAPI consumers such as dashboards, internal tools, and automation jobs

Use the root `README.md` for the fast project overview. Use this wiki when you need setup detail, operating guidance, security notes, or tool-by-tool reference material.

## Start Here

| If you want to... | Open this page |
| --- | --- |
| Deploy the project against a configured Proxmox environment | [Operator Guide](Operator-Guide) |
| Work on the codebase, run checks, or publish releases | [Developer Guide](Developer-Guide) |
| Connect Claude Desktop, Open WebUI, or HTTP clients | [Integrations Guide](Integrations-Guide) |
| Understand auth, command policy, and execution safety | [Security Guide](Security-Guide) |
| Browse the exact tool surface and prerequisites | [API & Tool Reference](API-&-Tool-Reference) |
| Debug startup, auth, SSH, or `/health` issues | [Troubleshooting](Troubleshooting) |
| Review release history and upgrade notes | [Release & Upgrade Notes](Release-&-Upgrade-Notes) |

## What The Project Covers

- VM and LXC lifecycle operations
- snapshots, rollback, backup, and restore
- ISO and template workflows
- cluster, node, and storage inspection
- SSH-backed container command execution
- OpenAPI bridging for the MCP tool surface

## Architecture Summary

- `main.py` starts the MCP server entrypoint
- `src/proxmox_mcp/server.py` registers MCP tools
- `src/proxmox_mcp/openapi_proxy.py` exposes `/`, `/docs`, `/openapi.json`, and `/health`
- `src/proxmox_mcp/config/` validates configuration and runtime settings
- `src/proxmox_mcp/security/command_policy.py` applies allow and deny rules for execution requests
- `docs/container-command-execution.md` explains the SSH-backed LXC command path

## Validation Summary

The repository includes live-environment verification entry points for:

- VM create, start, stop, and delete
- snapshot create, rollback, and delete
- backup and restore
- ISO download and cleanup
- LXC create, start, stop, and delete
- container SSH-backed command execution
- container authorized_keys update
- local OpenAPI `/health` and schema
- Docker image build and `/health`

Primary validation entry points:

- `pytest -q`
- `tests/integration/test_real_contract.py`
- `test_scripts/run_real_e2e.py`

## External References

- [Proxmox VE installation guide](https://pve.proxmox.com/pve-docs/pve-installation-plain.html)
- [Proxmox VE API guide](https://pve.proxmox.com/wiki/Proxmox_VE_API)
- [Proxmox VE administration guide](https://pve.proxmox.com/pve-docs/pve-admin-guide.html)
- [Linux Container guide](https://pve.proxmox.com/wiki/Linux_Container)
