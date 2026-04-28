# Release & Upgrade Notes

Use this page to track version-level behavior changes, upgrade steps, and rollback notes.

## Release Entry Template

### Version `<version>`

- Release date:
- Summary:
- New tools or endpoints:
- Changed behavior:
- Removed or deprecated behavior:
- Config changes:
- Docs updated:
- Upgrade steps:
- Rollback notes:

## Release History

### Version `0.4.3`

- Release date: 2026-04-28
- Summary: adds the `clone_vm` MCP tool for cloning existing Proxmox QEMU virtual machines.
- New tools or endpoints:
  - MCP tool: `clone_vm`
- Changed behavior:
  - no behavior changes to existing tools
- Config changes:
  - no required config changes
- Docs updated:
  - `docs/releases/v0.4.3.md`
- Upgrade steps:
  - no migration required
  - confirm the configured Proxmox API token has VM clone permissions before using `clone_vm`

### Version `0.4.2`

- Release date: 2026-04-28
- Summary: restores and updates the LXC container command execution setup guide for the current SSH-backed `pct exec` implementation.
- Changed behavior:
  - no runtime behavior changes
- Config changes:
  - `proxmox-config/config.example.json` now shows the recommended `mcp-agent` SSH user, `use_sudo=true`, and `known_hosts_file` setup
- Docs updated:
  - `docs/container-command-execution.md`
  - `docs/wiki/Container Command Execution.md`
  - `README.md`
  - `docs/releases/v0.4.2.md`
- Upgrade steps:
  - no migration required
  - if enabling container command execution, review the updated SSH and `command_policy` setup

### Version `0.4.1`

- Release date: 2026-04-25
- Summary: fixes first-run documentation and client example configuration issues found after the 0.4.0 release.
- Changed behavior:
  - no runtime behavior changes
- Config changes:
  - client examples now default to `PROXMOX_VERIFY_SSL=true`
  - examples that expose TLS mode also include `PROXMOX_DEV_MODE`
- Docs updated:
  - `README.md`
  - `docs/releases/v0.4.1.md`
  - `proxmox-config/opencode/README.md`
- Upgrade steps:
  - no migration required
  - for self-signed lab endpoints, set both `PROXMOX_VERIFY_SSL=false` and `PROXMOX_DEV_MODE=true`

### Version `0.4.0`

- Release date: 2026-04-25
- Summary: production-readiness pass for release packaging, Docker runtime size, dependency consistency, OpenAPI security visibility, and client-safe text output.
- Changed behavior:
  - runtime output now uses ASCII-safe labels and bullets instead of emoji glyphs
  - Docker installs only production package dependencies and runs as a non-root user
  - OpenAPI `/health` includes `security_warnings`
- Config changes:
  - no required config changes
  - production OpenAPI deployments should set `PROXMOX_API_KEY`, `PROXMOX_STRICT_AUTH=true`, and a specific `MCPO_CORS_ALLOW_ORIGINS`
- Docs updated:
  - `docs/releases/v0.4.0.md`
- Upgrade steps:
  - rebuild Docker images from this release
  - review OpenAPI security warnings after startup
  - verify clients do not rely on emoji prefixes in tool output

### Version `0.3.0`

- Release date: 2026-04-24
- Summary: adds a persistent SQLite-backed job layer for long-running Proxmox tasks, direct OpenAPI job routes, richer OpenAPI operational endpoints, and plugin-based tool registration.
- New tools or endpoints:
  - MCP tools: `list_jobs`, `get_job`, `poll_job`, `cancel_job`, `retry_job`
  - OpenAPI routes: `GET /jobs`, `GET /jobs/{job_id}`, `POST /jobs/{job_id}/poll`, `POST /jobs/{job_id}/cancel`, `POST /jobs/{job_id}/retry`
  - OpenAPI route: `/metrics`
- Changed behavior:
  - async mutating tools now return a stable `job_id` in addition to raw Proxmox `task_id`
  - tool registration now flows through built-in registry plugins instead of one growing `server.py` block
  - high-risk operations can be policy-gated separately from command execution
- Removed or deprecated behavior:
  - none
- Config changes:
  - new `jobs.sqlite_path`
  - new optional `api_tunnel` section
  - expanded `command_policy` with high-risk operation controls
- Docs updated:
  - `README.md`
  - `docs/wiki/Home.md`
  - `docs/wiki/Operator Guide.md`
  - `docs/wiki/API & Tool Reference.md`
  - `docs/wiki/Troubleshooting.md`
  - `docs/wiki/Developer Guide.md`
- Upgrade steps:
  - add a persistent path for `jobs.sqlite_path` in long-lived deployments
  - update config from `proxmox-config/config.example.json`
  - if you depend on async tooling, switch client logic to keep `job_id` and not just `task_id`
  - if you use OpenAPI, update monitors and clients to account for `/metrics` and `/jobs`
- Rollback notes:
  - older versions cannot read back persisted jobs through `/jobs`
  - clients written against `job_id` should be reverted together with the server downgrade

## Suggested Upgrade Checklist

Before upgrading:

- review changes to config examples
- review command policy defaults
- review OpenAPI wrapper behavior if your deployment depends on `/health` or auth
- check whether any new tool requires extra credentials or runtime dependencies

After upgrading:

- start the service and confirm config validation still passes
- call `get_nodes` and `get_cluster_status`
- verify expected tools are still registered
- verify `/health` and `/docs` if you run the OpenAPI proxy
- test at least one mutating workflow in a safe environment

## Suggested Release Checklist

- run `pytest`
- run `ruff .`
- run `mypy .`
- build the package
- confirm `README.md` and `docs/wiki/` reflect the released behavior
- note any user-visible changes here

## Existing Notes

Older release history has not been backfilled yet.
