# ProxmoxMCP-Plus Wiki

This wiki is the task-oriented documentation hub for ProxmoxMCP-Plus.

ProxmoxMCP-Plus exposes Proxmox VE operations through:

- native MCP stdio for local agents and IDEs
- native MCP Streamable HTTP at `/mcp` for remote MCP clients
- an OpenAPI bridge for HTTP automation, dashboards, and no-code workflows

Use the root `README.md` for the fast project overview. Use this wiki when you need to install a client, choose the right runtime, operate safely, debug a deployment, or inspect the tool surface.

## Start Here

| If you want to... | Open this page |
| --- | --- |
| Install the server in Claude Desktop, Cursor, VS Code, Codex, OpenCode, Open WebUI, or a generic MCP client | [Client Setup](Client-Setup) |
| Decide between stdio, Streamable HTTP, and OpenAPI | [Operator Guide](Operator-Guide) |
| Choose the right tool for VM, LXC, snapshot, backup, ISO, command, or job workflows | [Tool Selection Guide](Tool-Selection-Guide) |
| Understand auth, TLS, command policy, approval tokens, and MCP HTTP Host/Origin controls | [Security Guide](Security-Guide) |
| Enable SSH-backed LXC command execution | [Container Command Execution](Container-Command-Execution) |
| Browse exact tool names, inputs, prerequisites, and failure modes | [API & Tool Reference](API-&-Tool-Reference) |
| Debug startup, auth, SSH, `/livez`, `/readyz`, or `/health` issues | [Troubleshooting](Troubleshooting) |
| Work on code, run checks, or publish a release | [Developer Guide](Developer-Guide) |
| Review release history and upgrade notes | [Release & Upgrade Notes](Release-&-Upgrade-Notes) |
| Improve README, media, docs site, wiki, and docs automation | [Documentation Quality Plan](Documentation-Quality-Plan) |

## Five Minute Path

1. Create `proxmox-config/config.json` from `proxmox-config/config.example.json`.
2. Add Proxmox API host, user, token name, and token value.
3. Pick one runtime:

| Runtime | Command | Target |
| --- | --- | --- |
| MCP stdio | `uvx proxmox-mcp-plus` | launched by local MCP clients |
| MCP Streamable HTTP | `docker compose --profile mcp-http up -d proxmox-mcp-http` | `http://<host>:8000/mcp` |
| OpenAPI | `docker compose up -d` | `http://<host>:8811/docs` |

4. Verify read-only tools first: `get_nodes`, `get_vms`, `get_containers`, and `get_storage`.
5. Use mutating tools only after checking permissions, target IDs, storage, and safety policy.

## What The Project Covers

- VM and LXC lifecycle operations
- snapshots, rollback, backup, and restore
- ISO and template workflows
- cluster, node, and storage inspection
- SSH-backed container command execution
- persistent job tracking with retry, cancel, polling, and audit history
- OpenAPI bridging for the MCP tool surface
- named Proxmox targets with isolated connections, jobs, and safety policies
- opt-in MCP tool allowlists and denylists to reduce client schema exposure

## Safety Model Summary

ProxmoxMCP-Plus is not a replacement for Proxmox RBAC or network isolation. It adds an operator-facing control layer:

- Proxmox API token permissions remain the backend source of authority.
- OpenAPI mode requires `PROXMOX_API_KEY` by default.
- Native MCP HTTP mode can require a separate `MCP_API_KEY` Bearer token.
- TLS validation is enforced unless `security.dev_mode=true` is explicitly enabled.
- `command_policy` and `approval_token` can gate command execution and high-risk operations.
- MCP HTTP deployments can configure DNS rebinding protection plus Host and Origin allowlists.
- Logs are designed to avoid leaking command and credential material.

## Architecture Summary

- `main.py` starts the MCP server entrypoint.
- `src/proxmox_mcp/server.py` initializes the MCP server.
- `src/proxmox_mcp/services/builtin_tool_plugins.py` registers the built-in tool groups.
- `src/proxmox_mcp/openapi_proxy.py` exposes `/`, `/docs`, `/openapi.json`, `/livez`, `/readyz`, `/health`, `/metrics`, and `/jobs`.
- `src/proxmox_mcp/config/` validates configuration and runtime settings.
- `src/proxmox_mcp/security/command_policy.py` applies allow and deny rules for execution requests.
- `src/proxmox_mcp/services/jobs.py` persists long-running job state in SQLite.

## Validation Summary

Primary validation entry points:

- `pytest -q --cov=proxmox_mcp --cov-report=term-missing --cov-fail-under=75`
- `ruff check .`
- `mypy src --ignore-missing-imports`
- `pip-audit -r requirements.txt`
- `tests/integration/test_real_contract.py`
- `tests/scripts/run_real_e2e.py`

Live-environment validation covers VM, LXC, snapshot, backup, ISO, container command, OpenAPI, and Docker paths when a real Proxmox lab config is available.

## External References

- [Proxmox VE installation guide](https://pve.proxmox.com/pve-docs/pve-installation-plain.html)
- [Proxmox VE API guide](https://pve.proxmox.com/wiki/Proxmox_VE_API)
- [Proxmox VE administration guide](https://pve.proxmox.com/pve-docs/pve-admin-guide.html)
- [Linux Container guide](https://pve.proxmox.com/wiki/Linux_Container)
