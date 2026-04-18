# ProxmoxMCP-Plus

<div align="center">
  <img src="assets/logo-proxmoxmcp-plus.png" alt="ProxmoxMCP-Plus Logo" width="200"/>
</div>

Open-source MCP server for Proxmox VE automation.  
This repository provides a secure control plane for VM and container lifecycle operations, plus an OpenAPI bridge for integrations.

Documentation strategy: this README is the stable entrypoint, while detailed runbooks and references live in Wiki.
This keeps onboarding fast while leaving longer guides and runbooks in Wiki.

[Quick Start](#quick-start) | [Security](#security) | [API Reference](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/API-&-Tool-Reference) | [Troubleshooting](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/Troubleshooting)

## 1) Project Positioning and Value

ProxmoxMCP-Plus is designed for teams that need:

- Reliable MCP-native automation for Proxmox clusters
- Safer execution paths with policy controls
- Integration flexibility across MCP clients and HTTP/OpenAPI consumers
- A documentation model where README stays concise and Wiki carries deep guidance

This project builds on [canvrno/ProxmoxMCP](https://github.com/canvrno/ProxmoxMCP), and extends it with stronger operational controls, OpenAPI access, and clearer documentation for day-to-day use.

Target audience:

- Teams operating Proxmox with MCP-based automation
- AI and tooling teams exposing virtualization controls to assistant workflows
- Infrastructure operators who need traceable automation with policy controls

## 2) Architecture and Capability Overview

High-level architecture:

- `MCP Server`: stdio MCP interface for assistants and MCP clients
- `Tooling Layer`: VM, container, storage, snapshot, backup, and cluster operations
- `Security Layer`: token auth, command policy, and scoped execution controls
- `Observability Layer`: logging and health visibility
- `OpenAPI Bridge`: HTTP exposure for external platforms

![ProxmoxMCP-Plus architecture overview](assets/architecture-overview.drawio-style.svg)

Capability groups:

| Domain | Coverage |
| --- | --- |
| Compute Lifecycle | VM and LXC create/start/stop/reset/delete/update |
| Data Protection | Snapshot, backup, and restore workflows |
| Platform Operations | Node, cluster, storage, and ISO/template management |
| Remote Execution | Optional command execution for VM and container workflows |
| Integrations | MCP clients, OpenAPI consumers, and WebUI-based automation |

Core features:

- `VM lifecycle you can actually automate`: create VMs with CPU, memory, disk, storage, OS type, and bridge settings; then start, stop, shut down, reset, or delete them from MCP or HTTP clients.
- `LXC management with practical controls`: list containers, start/stop/restart them, resize CPU and memory, create new containers from templates, inspect config, fetch container IPs, and remove containers cleanly.
- `Snapshots and rollback`: create, list, delete, and roll back snapshots for both VMs and containers, so assistants can handle change checkpoints without dropping to the Proxmox UI.
- `Backups and restore flows`: browse backup volumes, trigger backups, restore them to new IDs, and clean up old backup artifacts when needed.
- `Storage and image visibility`: inspect storage pools, browse uploaded ISOs, list templates, and download or delete ISO images without switching tools.
- `Cluster and node awareness`: read cluster status, enumerate nodes, and inspect per-node health before making changes.
- `Command execution with guardrails`: run commands in VMs through QEMU Guest Agent and in containers through SSH-backed execution, while still passing through command policy checks.
- `OpenAPI bridge out of the box`: expose the same MCP capabilities over HTTP with `/docs`, `/openapi.json`, and `/health`, which makes it easier to connect Open WebUI, internal tools, or simple automation scripts.

Why this is useful in practice:

- An assistant can create a test VM from a plain-language request, choose storage automatically, and return the resulting VM details.
- A workflow can snapshot a workload before change, run an update, and roll back if the verification step fails.
- A WebUI or internal portal can use the OpenAPI endpoint instead of implementing Proxmox calls directly.
- Teams can keep risky command execution behind policy checks instead of exposing raw shell access everywhere.

Full endpoint and tool details are maintained in Wiki: [API & Tool Reference](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/API-&-Tool-Reference).

Operational boundaries:

- ProxmoxMCP-Plus orchestrates Proxmox operations; it does not replace cluster-level backup/HA design.
- Security controls in this service must be paired with network segmentation and Proxmox RBAC.
- OpenAPI exposure is intended for controlled environments, not unauthenticated public access.

## 3) Quick Start

Prerequisites:

- Python 3.9+
- `uv` package manager
- Proxmox API token with required permissions

Minimal setup:

```bash
git clone https://github.com/RekklesNA/ProxmoxMCP-Plus.git
cd ProxmoxMCP-Plus
uv venv
uv pip install -e ".[dev]"
```

Create runtime config:

```bash
cp proxmox-config/config.example.json proxmox-config/config.json
```

Set required fields in `proxmox-config/config.json`:

- `proxmox.host`
- `auth.user`
- `auth.token_name`
- `auth.token_value`

Run MCP server:

```bash
python main.py
```

Optional OpenAPI mode:

```bash
docker compose up -d
```

Health endpoint:

```bash
curl -f http://localhost:8811/health
```

For deployment details and runtime operations, use [Operator Guide](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/Operator-Guide).

Validation path for first run:

1. Start server and verify no startup auth errors.
2. Call a read-only tool such as node or VM listing.
3. Validate `/health` when OpenAPI mode is enabled.
4. Proceed to write operations only after policy and RBAC validation.

## 4) Integration Entry Points

- `Claude Desktop`: [Integrations Guide](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/Integrations-Guide)
- `Cline`: [Integrations Guide](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/Integrations-Guide)
- `Open WebUI`: [Integrations Guide](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/Integrations-Guide)
- `OpenAPI / Swagger`: `http://<host>:8811/docs` and [API & Tool Reference](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/API-&-Tool-Reference)

Integration expectations:

- Keep client-specific connection settings outside committed source files.
- Use environment-specific API keys when exposing OpenAPI.
- Test with read-only operations before enabling lifecycle mutation workflows.

## 5) Security

Security summary:

- API-token based Proxmox authentication
- Environment-aware controls (`dev_mode` for development-only relaxation)
- Command execution policy and allow/deny constraints
- Operational logging and health visibility

Security controls, deployment guidance, and threat boundaries are documented in [Security Guide](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/Security-Guide).

Recommended deployment controls:

- Enforce `security.dev_mode=false`
- Restrict ingress to trusted networks or VPN paths
- Terminate TLS at a reverse proxy you control
- Rotate API credentials regularly and monitor denied operations

## 6) Contributing / Development

Developer workflow:

```bash
pytest
ruff .
mypy .
black .
```

Contribution standards, local setup, and validation expectations are maintained in [Developer Guide](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/Developer-Guide).

Packaging and release:

```bash
python -m pip install --upgrade build twine
python -m build
twine check dist/*
```

Release automation included in this repository:

- `publish-pypi.yml`: publishes `dist/` artifacts to PyPI on GitHub Release publish or manual dispatch
- `publish-ghcr.yml`: builds and publishes a container image to `ghcr.io/RekklesNA/ProxmoxMCP-Plus`

Release prerequisites:

- Configure a PyPI project named `proxmox-mcp-plus`
- Prefer PyPI Trusted Publishing, or set repository secret `PYPI_API_TOKEN`
- Ensure GitHub Actions has permission to publish packages to GHCR
- Create a GitHub Release such as `v0.1.0` to trigger both publish workflows

Pull request quality bar:

- Behavior changes are covered by tests
- Type and lint checks pass in CI
- Documentation updates are included when interfaces or operations change

## 7) Support / FAQ

Support channels:

- Bug reports and feature requests: [GitHub Issues](https://github.com/RekklesNA/ProxmoxMCP-Plus/issues)
- Operational incidents and known fixes: [Troubleshooting](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/Troubleshooting)

FAQ shortcuts:

- How do I deploy this service? See [Operator Guide](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/Operator-Guide).
- Where are all tools/endpoints listed? See [API & Tool Reference](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/API-&-Tool-Reference).
- How do I configure secure command execution? See [Security Guide](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/Security-Guide).

When troubleshooting deeper issues:

- For security-related incidents, collect logs and request context before remediation.
- For breaking behavior after upgrade, compare against [Release & Upgrade Notes](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/Release-&-Upgrade-Notes).

## 8) Wiki Navigation Panel

GitHub Wiki contains the detailed documentation.  
If Wiki is not enabled yet, enable it in repository settings first, then publish the seed pages from `docs/wiki/`.

### Documentation Map

| Topic | What it covers | Wiki link |
| --- | --- | --- |
| Home | Documentation landing page and navigation | [Home](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/Home) |
| Operator Guide | Deployment, runtime operations, OpenAPI, and operating checklist | [Operator Guide](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/Operator-Guide) |
| Developer Guide | Local setup, coding standards, testing and release flow | [Developer Guide](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/Developer-Guide) |
| Security Guide | Auth model, command policy, hardening, and logging guidance | [Security Guide](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/Security-Guide) |
| Integrations Guide | Claude, Cline, Open WebUI, MCP transport setup | [Integrations Guide](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/Integrations-Guide) |
| API & Tool Reference | Tool groups, endpoint behavior, and request notes | [API & Tool Reference](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/API-&-Tool-Reference) |
| Troubleshooting | Incident patterns, diagnostics, and recovery actions | [Troubleshooting](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/Troubleshooting) |
| Release & Upgrade Notes | Version-level changes and upgrade actions | [Release & Upgrade Notes](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/Release-&-Upgrade-Notes) |

Local seed pages for Wiki bootstrap are available in [`docs/wiki/`](docs/wiki/README.md).

### Documentation Notes

README remains intentionally concise and stable.  
Detailed operational guidance, examples, and runbooks live in Wiki.

The following entry points are treated as stable documentation interfaces:

- `Quick Start`: repository bootstrap and first-run verification
- `Security`: control overview and hardening navigation
- `API Reference`: tool and endpoint behavior index
- `Troubleshooting`: incident diagnosis and recovery guidance

When documentation changes:

1. Update the relevant Wiki page first.
2. Keep README links stable unless there is a structural migration.
3. Record version-impacting documentation updates in `Release & Upgrade Notes`.

## License

[MIT License](LICENSE)
