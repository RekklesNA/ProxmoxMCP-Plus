# ProxmoxMCP-Plus

<!-- mcp-name: io.github.RekklesNA/proxmox-mcp-plus -->

<div align="center">
  <img src="docs/assets/logo-proxmoxmcp-plus.png" alt="ProxmoxMCP-Plus Logo" width="160"/>
</div>

<p align="center"><strong>Control Proxmox VE from LLMs, AI agents, MCP clients, and OpenAPI tooling with one safer interface for VMs, LXCs, backups, snapshots, ISOs, container commands, and persistent long-running jobs.</strong></p>

<p align="center">
  <a href="https://pypi.org/project/proxmox-mcp-plus/"><img alt="PyPI" src="https://img.shields.io/pypi/v/proxmox-mcp-plus"></a>
  <a href="https://github.com/RekklesNA/ProxmoxMCP-Plus/releases"><img alt="GitHub Release" src="https://img.shields.io/github/v/release/RekklesNA/ProxmoxMCP-Plus"></a>
  <a href="https://github.com/RekklesNA/ProxmoxMCP-Plus/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/RekklesNA/ProxmoxMCP-Plus/ci.yml?branch=main"></a>
  <a href="https://github.com/RekklesNA/ProxmoxMCP-Plus/pkgs/container/ProxmoxMCP-Plus"><img alt="GHCR" src="https://img.shields.io/badge/GHCR-container-blue"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/github/license/RekklesNA/ProxmoxMCP-Plus"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> |
  <a href="#demo">Demo</a> |
  <a href="#core-platform-capabilities">Capabilities</a> |
  <a href="#scenario-templates">Scenarios</a> |
  <a href="#documentation">Docs</a> |
  <a href="https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki">Wiki</a>
</p>

![ProxmoxMCP-Plus architecture and control flow](docs/assets/proxmoxmcp-drawio-hero-main-refresh.svg)

## Platform Overview

ProxmoxMCP-Plus provides a unified Proxmox VE control surface in two forms:

- `MCP` for Claude Desktop, Open WebUI, and other LLM or AI agent clients
- `OpenAPI` for HTTP automation, dashboards, internal tools, and no-code workflows

Instead of stitching together raw Proxmox API calls, shell scripts, and custom glue code, the project consolidates core operational workflows in one interface:

- VM and LXC lifecycle actions
- snapshot create, rollback, and delete
- backup and restore workflows
- ISO download and cleanup
- node, storage, and cluster inspection
- SSH-backed container command execution with guardrails
- persistent job tracking for async Proxmox tasks

## Design Priorities

ProxmoxMCP-Plus is designed for the gap between low-level Proxmox primitives and production-facing workflows that need to be usable from both LLM-native clients and standard automation systems.

- `Dual-surface architecture`: MCP for conversational workflows, OpenAPI for standard automation
- `Operator-oriented scope`: focused on day-2 tasks, not just raw low-level endpoints
- `Safer-by-default execution`: auth, command policy, and explicit execution paths
- `Observable long-running workflows`: stable `Job ID`s, progress polling, retry, cancel, and audit history
- `Operationally grounded`: documented workflows are backed by live-environment verification

## Quick Start

### 1. Prepare Proxmox access

Read the official Proxmox docs first if you are setting up a fresh lab:

- [Proxmox VE installation guide](https://pve.proxmox.com/pve-docs/pve-installation-plain.html)
- [Proxmox VE API guide](https://pve.proxmox.com/wiki/Proxmox_VE_API)
- [Proxmox VE administration guide](https://pve.proxmox.com/pve-docs/pve-admin-guide.html)
- [Linux Container guide](https://pve.proxmox.com/wiki/Linux_Container)

At minimum, `proxmox-config/config.json` needs:

- `proxmox.host`
- `proxmox.port`
- `auth.user`
- `auth.token_name`
- `auth.token_value`

Add an `ssh` section as well if you want container command execution.
Add a `jobs` section if you want job state persisted somewhere other than the default local SQLite file.

For real live verification, use a separate `proxmox-config/config.live.json` created from `proxmox-config/config.live.example.json`.
Do not point live e2e at a placeholder or local-only `config.json` unless you intentionally run a local API tunnel there.

Minimal job persistence config:

```json
{
  "jobs": {
    "sqlite_path": "proxmox-jobs.sqlite3"
  }
}
```

### 2. Choose one runtime path

#### PyPI

```bash
uvx proxmox-mcp-plus
```

Or install it first:

```bash
pip install proxmox-mcp-plus
proxmox-mcp-plus
```

#### Docker / GHCR

```bash
docker run --rm -p 8811:8811 \
  -v "$(pwd)/proxmox-config/config.json:/app/proxmox-config/config.json:ro" \
  ghcr.io/rekklesna/proxmoxmcp-plus:latest
```

#### Source

```bash
git clone https://github.com/RekklesNA/ProxmoxMCP-Plus.git
cd ProxmoxMCP-Plus
uv venv
uv pip install -e ".[dev]"
python main.py
```

### 3. Run the HTTP/OpenAPI surface

```bash
docker compose up -d
curl -f http://localhost:8811/health
curl http://localhost:8811/openapi.json
```

### 4. Point an MCP client at the server

Minimal MCP client shape:

```json
{
  "mcpServers": {
    "proxmox-mcp-plus": {
      "command": "python",
      "args": ["/path/to/ProxmoxMCP-Plus/main.py"],
      "env": {
        "PROXMOX_MCP_CONFIG": "/path/to/ProxmoxMCP-Plus/proxmox-config/config.json"
      }
    }
  }
}
```

Client-specific examples for Claude Desktop and Open WebUI are in the [Integrations Guide](docs/wiki/Integrations%20Guide.md).

## Demo

This demo is a direct terminal recording of `qwen/qwen3.6-plus` driving a live MCP session in English against a local Proxmox lab. It shows natural-language control flowing through MCP tools to create and start an LXC, execute a container command, and confirm the HTTP `/health` surface.

![Recorded demo gif](docs/assets/proxmoxmcp-demo.gif)

[Watch the MP4 version](docs/assets/proxmoxmcp-demo.mp4)

## Core Platform Capabilities

ProxmoxMCP-Plus provides a unified control surface for the operational tasks most teams actually need in Proxmox VE. The same server can expose these workflows to MCP clients for LLM and AI-agent use cases, and to HTTP consumers through the OpenAPI bridge.

Supported workflow areas:

| Capability Area | Availability |
| --- | --- |
| VM create / start / stop / delete | Available |
| VM snapshot create / rollback / delete | Available |
| Backup create / restore | Available |
| ISO download / delete | Available |
| LXC create / start / stop / delete | Available |
| Container SSH-backed command execution | Available |
| Container authorized_keys update | Available |
| Persistent job store for long tasks | Available |
| MCP job control tools (`list_jobs`, `get_job`, `poll_job`, `cancel_job`, `retry_job`) | Available |
| OpenAPI `/jobs` endpoints with explicit status codes | Available |
| Local OpenAPI `/health` and schema | Available |
| Docker image build and `/health` | Available |

Validation and contract entry points in this repository:

- `pytest -q`
- `tests/integration/test_real_contract.py`
- `tests/scripts/run_real_e2e.py`

`tests/scripts/run_real_e2e.py` now prefers `proxmox-config/config.live.json` or `PROXMOX_MCP_E2E_CONFIG`.
This avoids accidentally running live checks against a machine-specific default `config.json`.

## Long-Running Jobs

Many Proxmox mutations are asynchronous. ProxmoxMCP-Plus now wraps those tasks in a persistent job layer so MCP and OpenAPI clients can track them through a stable `Job ID`.

Long-running tools such as VM create/start/stop, container create/start/stop, snapshot changes, backup/restore, and ISO download/delete now return both:

- `task_id`: the raw Proxmox `UPID`
- `job_id`: the stable server-side job record

The job record stores:

- current status and progress
- retry count and prior `UPID`s
- latest result payload or failure reason
- audit history for create, poll, retry, and cancel actions

By default the job store persists to `proxmox-jobs.sqlite3`, so restart does not lose in-flight or completed job metadata.

### MCP Job Tools

- `list_jobs`
- `get_job`
- `poll_job`
- `cancel_job`
- `retry_job`

### OpenAPI Job Routes

When the OpenAPI proxy is enabled and a local `JobStore` is available, these routes are exposed directly:

| Path | Method | Purpose | Success Codes |
| --- | --- | --- | --- |
| `/jobs` | `GET` | list persisted jobs | `200` |
| `/jobs/{job_id}` | `GET` | fetch one job, optional `refresh=true` | `200` |
| `/jobs/{job_id}/poll` | `POST` | refresh status from Proxmox | `200` |
| `/jobs/{job_id}/cancel` | `POST` | request cancellation | `202` |
| `/jobs/{job_id}/retry` | `POST` | replay a stored retry recipe | `202` |

Common error codes:

- `404`: unknown `job_id`
- `409`: the job exists but that operation is not valid now
- `503`: the OpenAPI proxy was started without a local `JobStore`

## Positioning Against Common Approaches

| Capability | Official Proxmox API | One-off scripts | ProxmoxMCP-Plus |
| --- | --- | --- | --- |
| MCP for LLM and AI agent workflows | No | No | Yes |
| OpenAPI surface for standard HTTP tooling | No | Usually no | Yes |
| VM and LXC operations in one interface | Low-level only | Depends | Yes |
| Snapshot, backup, and restore workflows | Low-level only | Depends | Yes |
| Persistent async job tracking and retry | No | Rare | Yes |
| Container command execution with policy controls | No | Custom only | Yes |
| Docker distribution path | No | Rare | Yes |
| Repository-level live-environment verification | N/A | Rare | Yes |

## Scenario Templates

Ready-to-copy examples live in [`docs/examples/`](docs/examples/README.md):

- [Create a test VM](docs/examples/create-test-vm.md)
- [Roll back a risky change with snapshots](docs/examples/rollback-snapshot.md)
- [Download an ISO and create an LXC](docs/examples/download-iso-and-create-lxc.md)

These are written for both human operators and LLM-driven usage.

## Documentation

The README is intentionally optimized for fast GitHub comprehension. Longer operational docs live in `docs/wiki/` and can also be published to the GitHub Wiki.

| If you need to... | Start here |
| --- | --- |
| Understand the project and deployment flow | [Wiki Home](docs/wiki/Home.md) |
| Configure and run against a Proxmox environment | [Operator Guide](docs/wiki/Operator%20Guide.md) |
| Connect Claude Desktop or Open WebUI | [Integrations Guide](docs/wiki/Integrations%20Guide.md) |
| Install from MCP-aware IDEs and agents | [Agent Installation](docs/agent-installation.md) |
| Review security and command policy | [Security Guide](docs/wiki/Security%20Guide.md) |
| Inspect tool parameters, prerequisites, and behavior | [API & Tool Reference](docs/wiki/API%20%26%20Tool%20Reference.md) |
| Debug startup, auth, or health issues | [Troubleshooting](docs/wiki/Troubleshooting.md) |
| Work on the codebase or release it | [Developer Guide](docs/wiki/Developer%20Guide.md) |
| Review release and upgrade notes | [Release & Upgrade Notes](docs/wiki/Release%20%26%20Upgrade%20Notes.md) |

Published wiki:

- [GitHub Wiki Home](https://github.com/RekklesNA/ProxmoxMCP-Plus/wiki/Home)

## Repo Layout

- `src/proxmox_mcp/`: MCP server, config loading, security, OpenAPI bridge
- `main.py`: MCP entrypoint for local and client-driven usage
- `docker-compose.yml`: HTTP/OpenAPI runtime
- `requirements/`: auxiliary dependency sources and runtime install lists
- `scripts/`: helper startup scripts for local workflows
- `tests/scripts/run_real_e2e.py`: live Proxmox and Docker/OpenAPI path
- `tests/`: unit and integration coverage
- `docs/examples/`: scenario-driven prompts and HTTP examples
- `docs/wiki/`: longer-form operator, integration, and reference docs

## Development Checks

```bash
pytest -q
ruff check .
mypy src tests main.py tests/scripts/run_real_e2e.py
python -m build
```

## License

[MIT](LICENSE)
