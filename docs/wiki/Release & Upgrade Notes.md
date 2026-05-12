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

### Version `0.5.1`

- Release date: 2026-05-12
- Summary: persistent job safety patch that blocks duplicate retries for running or completed jobs, discards stale poll results after a retry swaps UPIDs, and protects direct OpenAPI `/jobs` routes when an app is created with an API key but without strict middleware.
- New tools or endpoints:
  - no new tools or endpoints
- Changed behavior:
  - `retry_job` only replays jobs in `failed`, `cancelled`, or `cancel_requested` states
  - `poll_job` records `poll_discarded` instead of overwriting a job when the polled UPID is stale
  - direct OpenAPI `/jobs` routes reuse API-key verification in non-strict `create_app` usage
- Config changes:
  - no required config migration
- Docs updated:
  - `docs/releases/v0.5.1.md`
  - `docs/wiki/Release & Upgrade Notes.md`
- Upgrade steps:
  - poll jobs before retrying and retry only failed or cancelled jobs
  - keep sending `Authorization: Bearer <PROXMOX_API_KEY>` for OpenAPI job routes
- Rollback notes:
  - downgrade to `v0.5.0` only if callers depend on retrying completed jobs; doing so reopens the duplicate-operation risk

### Version `0.5.0`

- Release date: 2026-05-11
- Summary: OpenAPI security baseline release with required API-key startup, project-owned constant-time auth middleware, auth-failure rate limiting, split liveness/readiness probes, live E2E auth updates, and Paramiko 5.0.0.
- New tools or endpoints:
  - `/livez` for unauthenticated process liveness
  - `/readyz` for authenticated backend readiness
- Changed behavior:
  - OpenAPI mode refuses to start without `PROXMOX_API_KEY` unless `PROXMOX_ALLOW_NO_AUTH=true` is set
  - OpenAPI requests require `Authorization: Bearer <PROXMOX_API_KEY>` by default
  - OpenAPI API key verification uses project-owned constant-time comparison
  - auth failures pass through rate limiting before the auth decision
  - `/health` remains available as an authenticated readiness alias
  - live E2E and Docker OpenAPI checks send Bearer auth
  - `scripts/start_openapi.sh` uses `.venv/bin/python` for proxy startup and dependency checks
- Removed or deprecated behavior:
  - unauthenticated OpenAPI startup is no longer the default
  - the temporary `CVE-2026-44405` `pip-audit` exception is removed
- Config changes:
  - `PROXMOX_API_KEY` is required for OpenAPI mode unless `PROXMOX_ALLOW_NO_AUTH=true`
  - runtime dependency support now requires `paramiko>=5.0.0,<6.0.0`
- Docs updated:
  - `README.md`
  - `docs/examples/*.md`
  - `docs/releases/v0.5.0.md`
  - `docs/security/paramiko-cve-2026-44405.md`
  - `docs/wiki/API & Tool Reference.md`
  - `docs/wiki/Developer Guide.md`
  - `docs/wiki/Home.md`
  - `docs/wiki/Integrations Guide.md`
  - `docs/wiki/Operator Guide.md`
  - `docs/wiki/Release & Upgrade Notes.md`
  - `docs/wiki/Security Guide.md`
- Upgrade steps:
  - set `PROXMOX_API_KEY` before starting OpenAPI mode
  - update HTTP clients to send `Authorization: Bearer <PROXMOX_API_KEY>`
  - use `/livez` for unauthenticated process liveness
  - use authenticated `/readyz` or `/health` for backend readiness
  - verify SSH endpoints do not depend on legacy RSA/SHA-1, SHA-1 KEX, or GSSAPI before adopting Paramiko 5
- Rollback notes:
  - downgrade to `v0.4.9` if clients cannot yet send OpenAPI auth headers, but keep the Paramiko CVE tracking and OpenAPI no-auth exposure in mind

### Version `0.4.9`

- Release date: 2026-05-09
- Summary: supersedes `v0.4.8` with the same reliability hardening plus a CodeQL-blocking log-injection fix for high-risk retry audit logs.
- New tools or endpoints:
  - no new tools
- Changed behavior:
  - high-risk retry audit logs sanitize job IDs and persisted tool names before logging
  - all `v0.4.8` production reliability changes are included
- Config changes:
  - no required config migration
- Docs updated:
  - `docs/releases/v0.4.9.md`
  - `docs/wiki/Release & Upgrade Notes.md`
- Upgrade steps:
  - prefer `v0.4.9` over `v0.4.8`
  - continue passing `include_stats=true` to `get_containers` if callers require detailed stats by default
- Rollback notes:
  - use `v0.4.7` rather than `v0.4.8` if rollback is required for the log-sanitization fix

### Version `0.4.8`

- Release date: 2026-05-09
- Summary: production reliability and release-quality hardening for persistent jobs, inventory reads, OpenAPI job controls, metrics, Paramiko tracking, and `clone_vm`.
- New tools or endpoints:
  - no new tools
- Changed behavior:
  - `clone_vm` now registers persistent jobs and returns a stable Job ID
  - high-risk job retries now pass through the same approval-token policy checks as direct tool execution
  - VM guest-agent commands poll until exit and report non-zero exit codes as failures
  - `get_vms` and default `get_containers` use cluster resource inventory to avoid large N+1 scans
  - `get_containers` defaults `include_stats=false`; detailed per-container status/config/RRD remains opt-in
  - OpenAPI metrics use route templates instead of raw paths for request labels
  - `JobStore` SQLite uses WAL, busy timeout, migration tracking, indexes, SQL filtering/limits, and explicit close lifecycle
- Config changes:
  - no required config migration
  - runtime dependency support now allows `paramiko>=4.0.0,<5.0.0`
- Docs updated:
  - `README.md`
  - `docs/releases/v0.4.8.md`
  - `docs/security/paramiko-cve-2026-44405.md`
  - `docs/wiki/API & Tool Reference.md`
  - `docs/wiki/Developer Guide.md`
  - `docs/wiki/Home.md`
  - `docs/wiki/Release & Upgrade Notes.md`
- Upgrade steps:
  - pass `include_stats=true` to `get_containers` if callers require detailed stats by default
  - monitor Paramiko releases and remove the temporary `CVE-2026-44405` audit exception once a fixed PyPI release exists
- Rollback notes:
  - downgrade to `v0.4.7` if clients depend on default container stats, but keep the Paramiko CVE tracking in mind

### Version `0.4.7`

- Release date: 2026-05-08
- Summary: adds a Docker-native MCP Streamable HTTP runtime so remote MCP clients can connect to `/mcp` without going through the OpenAPI bridge.
- New tools or endpoints:
  - Docker Compose profile `mcp-http` exposes native MCP Streamable HTTP at `http://<host>:8000/mcp`
- Changed behavior:
  - the Docker image now starts through `proxmox_mcp.docker_entrypoint`
  - OpenAPI mode remains the default Docker runtime on port `8811`
  - `MCP_HOST`, `MCP_PORT`, and `MCP_TRANSPORT` can override the `mcp` section from a mounted config file
- Config changes:
  - optional `PROXMOX_MCP_MODE=mcp-http` selects native MCP HTTP mode in Docker
- Docs updated:
  - `README.md`
  - `docs/releases/v0.4.7.md`
  - `docs/wiki/API & Tool Reference.md`
  - `docs/wiki/Integrations Guide.md`
  - `docs/wiki/Operator Guide.md`
- Upgrade steps:
  - no migration required
  - continue using the default Docker mode for OpenAPI clients
  - use `docker compose --profile mcp-http up -d proxmox-mcp-http` for Streamable HTTP MCP clients

### Version `0.4.6`

- Release date: 2026-05-02
- Summary: fixes API tunnel routing, cross-process job visibility, secret persistence in LXC retry specs, snapshot rollback safety, and storage status node selection.
- Changed behavior:
  - `api_tunnel.enabled=true` now routes Proxmox API calls to the local tunnel endpoint
  - OpenAPI `/jobs` refreshes persisted SQLite records before reads and job controls
  - `create_container` no longer persists retry recipes when container passwords or SSH public keys are present
  - `rollback_snapshot` refuses to continue when newer child snapshots exist instead of deleting them implicitly
  - `get_storage` queries status through real Proxmox nodes instead of `localhost`
- Config changes:
  - no required config changes
- Docs updated:
  - `docs/releases/v0.4.6.md`
- Upgrade steps:
  - no migration required
  - if you use snapshot rollback, explicitly delete newer child snapshots before retrying rollback

### Version `0.4.5`

- Release date: 2026-05-01
- Summary: fixes Home Assistant MCP compatibility for `get_containers` by removing the nested `$ref` payload schema while retaining legacy payload calls.
- Changed behavior:
  - `get_containers` now exposes flat top-level MCP arguments
  - legacy `payload` object input remains accepted for existing clients
- Config changes:
  - no required config changes
- Docs updated:
  - `docs/releases/v0.4.5.md`
  - `docs/wiki/API & Tool Reference.md`
- Upgrade steps:
  - no migration required

### Version `0.4.4`

- Release date: 2026-04-28
- Summary: updates GitHub Actions workflow dependencies to current Node 24-compatible major versions.
- Changed behavior:
  - no runtime behavior changes
- Config changes:
  - no required config changes
- Docs updated:
  - `docs/releases/v0.4.4.md`
- Upgrade steps:
  - no migration required

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
- review OpenAPI wrapper behavior if your deployment depends on `/livez`, `/readyz`, `/health`, or auth
- check whether any new tool requires extra credentials or runtime dependencies

After upgrading:

- start the service and confirm config validation still passes
- call `get_nodes` and `get_cluster_status`
- verify expected tools are still registered
- verify unauthenticated `/livez` plus authenticated `/readyz`, `/health`, and `/docs` if you run the OpenAPI proxy
- test at least one mutating workflow in a safe environment

## Suggested Release Checklist

- run `pytest -q --cov=proxmox_mcp --cov-report=term-missing --cov-fail-under=60`
- run `ruff check .`
- run `mypy src --ignore-missing-imports`
- run `pip-audit -r requirements.txt`
- build the package
- confirm `README.md` and `docs/wiki/` reflect the released behavior
- note any user-visible changes here

## Existing Notes

Older release history has not been backfilled yet.
