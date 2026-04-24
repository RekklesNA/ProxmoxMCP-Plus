# Operator Guide

This guide covers how to configure, run, and operate ProxmoxMCP-Plus.

## Runtime Modes

ProxmoxMCP-Plus can be used in two main ways:

- `MCP stdio mode`: assistants launch the server directly and call tools over MCP
- `OpenAPI mode`: FastAPI wraps the MCP server and exposes HTTP endpoints for other clients

The core tool set is the same in both modes. The difference is only the transport.

## Prerequisites

- Python 3.11 or newer
- Access to a Proxmox VE API endpoint
- A Proxmox API token with the permissions your workflows need
- Network access from the machine running ProxmoxMCP-Plus to the Proxmox API

Optional:

- SSH access from the MCP host to Proxmox nodes if you want LXC command execution tools

## Configuration File

The main config file is `proxmox-config/config.json`.

Start from the example:

```bash
cp proxmox-config/config.example.json proxmox-config/config.json
```

The main sections are:

- `proxmox`: host, port, TLS verification, service type
- `api_tunnel`: optional SSH local forward for the Proxmox API
- `auth`: Proxmox API user and token
- `logging`: log level, format, optional log file
- `mcp`: MCP host, port, and transport
- `security`: currently includes `dev_mode`
- `jobs`: SQLite path for persistent job tracking
- `command_policy`: rules for `execute_*` tools and high-risk mutating operations
- `ssh`: optional SSH settings for LXC command execution

## Environment Variable Fallback

If `PROXMOX_MCP_CONFIG` is not set or the file is missing, the loader falls back to environment variables.

Common variables:

- `PROXMOX_HOST`
- `PROXMOX_PORT`
- `PROXMOX_USER`
- `PROXMOX_TOKEN_NAME`
- `PROXMOX_TOKEN_VALUE`
- `PROXMOX_VERIFY_SSL`
- `PROXMOX_SERVICE`
- `LOG_LEVEL`
- `MCP_HOST`
- `MCP_PORT`
- `MCP_TRANSPORT`
- `PROXMOX_DEV_MODE`
- `COMMAND_POLICY_MODE`
- `PROXMOX_JOBS_SQLITE_PATH`

## Minimal Local Start

```bash
uv venv
uv pip install -e ".[dev]"
$env:PROXMOX_MCP_CONFIG="D:\\PycharmProject\\ProxmoxMCP-Plus\\proxmox-config\\config.json"
python main.py
```

If startup succeeds, the server stays attached to stdio and waits for MCP clients.

## OpenAPI Mode

You can run the OpenAPI wrapper directly:

```bash
python -m proxmox_mcp.openapi_proxy --host 0.0.0.0 --port 8811 -- python main.py
```

Available routes:

- `/` returns basic service metadata
- `/docs` serves Swagger UI
- `/openapi.json` serves the generated schema
- `/health` returns `503` until the proxy is connected to the MCP backend, then `200`
- `/metrics` exposes Prometheus-style request metrics
- `/jobs` exposes direct job query and control routes when a local `JobStore` is available

## Docker Compose Deployment

The repository includes `docker-compose.yml` and `Dockerfile`.

Default Compose behavior:

- Builds the local image
- Mounts `./proxmox-config` read-only into `/app/proxmox-config`
- Exposes `8811`
- Sets `PROXMOX_MCP_CONFIG=/app/proxmox-config/config.json`
- Adds a container health check against `http://localhost:8811/health`

Start it with:

```bash
docker compose up -d --build
```

## Operating Checklist

Before exposing the service to users:

- Confirm the Proxmox API token has only the permissions you intend to expose
- Keep `proxmox.verify_ssl=true` unless you are explicitly in development mode
- Keep `security.dev_mode=false` outside local testing
- Set an API key when exposing the OpenAPI endpoint outside a private dev machine
- Restrict ingress to networks you control
- Monitor the `/health` endpoint if you run the OpenAPI proxy
- Monitor `/metrics` if you scrape the service with Prometheus-compatible tooling
- Persist the configured `jobs.sqlite_path` on durable storage if job history matters across restarts
- Store logs somewhere persistent if you need auditability

## Command Execution Features

There are two command execution paths:

- `execute_vm_command`: uses QEMU Guest Agent inside VMs
- `execute_container_command`: uses SSH to the Proxmox node and then `pct exec` inside containers

Container command execution is optional and only appears when an `ssh` section exists in the config.

For setup details, see [Container Command Execution Guide](https://github.com/RekklesNA/ProxmoxMCP-Plus/blob/main/docs/container-command-execution.md).

## Long-Running Job Operations

Asynchronous Proxmox actions now register a persistent job record. This applies to operations such as:

- VM create, start, stop, shutdown, reset, and delete
- container create, start, stop, restart, and delete
- snapshot create, delete, and rollback
- backup create, restore, and delete
- ISO download and delete

Operational guidance:

- Treat `job_id` as the stable identifier you hand back to users, agents, and automation systems.
- Treat `task_id` or `UPID` as Proxmox internals that may change after a retry.
- Keep `jobs.sqlite_path` on a persistent volume in Docker or any long-lived service deployment.
- Use `/jobs/{job_id}/poll` or MCP `poll_job` to refresh progress from Proxmox.
- Use `/jobs/{job_id}/retry` only after reviewing `last_error`, `result`, and `audit_log`.

## First Verification Flow

After deployment, test in this order:

1. Start the service and confirm there are no config validation errors
2. Call read-only tools first: `get_nodes`, `get_vms`, `get_storage`, `get_cluster_status`
3. In OpenAPI mode, confirm `/health` and `/docs` both respond
4. Confirm `/jobs` responds if you expect persistent job tracking
5. If you enabled SSH-backed container commands, confirm `execute_container_command` appears in the tool list
6. Only then test mutating tools such as create, start, delete, snapshot, or backup

## Logs and Health

- Application logging is configured under the `logging` section
- `main.py` prints early startup messages to stderr to make bootstrap failures visible
- The OpenAPI wrapper reports `degraded` until it is connected to the MCP subprocess
- `/health` reports whether direct job routes are enabled in the OpenAPI process

## Related Pages

- [Security Guide](Security-Guide)
- [Integrations Guide](Integrations-Guide)
- [Troubleshooting](Troubleshooting)
