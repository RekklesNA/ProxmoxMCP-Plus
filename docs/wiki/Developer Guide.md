# Developer Guide

This guide covers local development, testing, and release work for ProxmoxMCP-Plus.

Start with [Contributing](../../CONTRIBUTING.md) for contribution channels,
the Code of Conduct, safe test setup, and pull request expectations.

## Local Setup

```bash
python -m venv .venv
# Activate .venv using the command for your shell (see CONTRIBUTING.md).
python -m pip install --require-hashes -r requirements/runtime.lock
python -m pip install -r requirements/dev.in
python -m pip install --no-deps -e .
```

Unit tests use mocks and do not require a real Proxmox configuration. For manual
server work, copy `proxmox-config/config.example.json` to the ignored local
`proxmox-config/config.json` and use an authorized lab environment, or select a
dedicated config with `PROXMOX_MCP_CONFIG`. Do not commit credentials.

## Common Commands

```bash
python -m pytest -q
ruff check .
mypy src --ignore-missing-imports
python -m pip_audit -r requirements/runtime.lock --require-hashes --disable-pip --strict
python -m build
```

Install `pip-audit` separately if needed. CI requires every runtime statement and
all branches in its critical modules to be covered. It supplies a disposable
PostgreSQL service and Docker/Compose; see [the contribution guide](../../CONTRIBUTING.md#validate-a-change)
for equivalent commands and why local optional-environment skips do not establish
the full coverage gate. Follow [Dependency updates](../dependency-updates.md) for
lock-file changes.

For manual server startup and OpenAPI authentication, follow the
[README](../../README.md#quick-start) and [Compose guide](../docker-compose.md).

## Project Layout

| Path | Purpose |
| --- | --- |
| `main.py` | bootstrap entrypoint used by the packaged bundle |
| `src/proxmox_mcp/server.py` | MCP server initialization and tool registration |
| `src/proxmox_mcp/openapi_proxy.py` | FastAPI wrapper for HTTP/OpenAPI mode |
| `src/proxmox_mcp/config/` | config models and loader |
| `src/proxmox_mcp/security/` | command policy checks |
| `src/proxmox_mcp/services/jobs.py` | persistent SQLite-backed job store |
| `src/proxmox_mcp/services/builtin_tool_plugins.py` | plugin-based tool registration |
| `src/proxmox_mcp/tools/` | Proxmox-facing tool implementations |
| `tests/` | unit and integration-facing test coverage |
| `docs/wiki/` | wiki seed pages |

## Development Expectations

- Keep behavior changes covered by tests
- Prefer clear, typed interfaces for tool contracts
- Update docs when a tool, config field, or runtime behavior changes
- Verify tool availability through the registry and configured capability filters

## What To Check When Changing Tools

If you add or change a tool:

- Update the implementation in `src/proxmox_mcp/tools/`
- Register or adjust it in `src/proxmox_mcp/services/builtin_tool_plugins.py`
- Update descriptions in `src/proxmox_mcp/tools/definitions.py`
- Add or update tests under `tests/`
- Update [API & Tool Reference](API-&-Tool-Reference) if the surface changed

If the tool launches an asynchronous Proxmox task, also:

- return a stable `job_id` alongside the raw Proxmox `task_id`
- add or update the persisted retry recipe in `src/proxmox_mcp/services/jobs.py`
- verify the job is queryable through both MCP tools and the OpenAPI `/jobs` routes

## Configuration Development Notes

The config loader supports:

- JSON file loading through `PROXMOX_MCP_CONFIG`
- Environment-only fallback when no config file is available
- TLS safety checks that block `verify_ssl=false` unless `security.dev_mode=true`
- MCP transport normalization, including `STREAMABLE_HTTP` to `STREAMABLE`
- `jobs.sqlite_path` fallback through `PROXMOX_JOBS_SQLITE_PATH`

If you change config semantics, keep the example files in `proxmox-config/` consistent.

## Packaging and Release

The package metadata lives in `pyproject.toml`.

Notable details:

- Package name: `proxmox-mcp-plus`
- Console script: `proxmox-mcp = proxmox_mcp.server:main`
- Build backend: `hatchling`
- Supported Python versions in metadata: 3.11 and 3.12

Local packaging check:

```bash
python -m pip install --upgrade build twine
python -m build
twine check dist/*
```

## Test Coverage Focus

The current tests cover several important behaviors already:

- tool registration with and without SSH config
- config validation and TLS safety checks
- OpenAPI root and health endpoints
- OpenAPI `/metrics` and `/jobs` endpoints
- VM and container tool behavior
- backup, storage, ISO, and cluster-related flows
- SQLite-backed job persistence and retry behavior

When adding a new feature, extend tests in the same area rather than only relying on manual checks.

## Documentation Workflow

- Update `README.md` for top-level positioning or setup changes
- Update `docs/wiki/` for details, examples, and operational behavior
- Keep wiki titles stable so the GitHub Wiki URLs do not change
