# Developer Guide

This guide covers local development, testing, and release work for ProxmoxMCP-Plus.

## Local Setup

```bash
uv venv
uv pip install -e ".[dev]"
cp proxmox-config/config.example.json proxmox-config/config.json
```

Set `proxmox-config/config.json` to a real environment or use a test config path through `PROXMOX_MCP_CONFIG`.

## Common Commands

```bash
pytest
ruff .
mypy .
black .
python main.py
python -m proxmox_mcp.openapi_proxy --host 0.0.0.0 --port 8811 -- python main.py
```

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
- Avoid documenting features that are not actually registered in `server.py`

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
