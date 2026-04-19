# ProxmoxMCP-Plus installation notes for AI agents

These instructions are written for MCP-capable IDEs and agents such as Cline, Claude Desktop, Cursor, and VS Code.

## What this server does

`ProxmoxMCP-Plus` exposes Proxmox VE operations for:

- VMs and LXCs
- snapshots and rollbacks
- backups and restores
- ISO and template workflows
- storage and cluster inspection
- optional SSH-backed container command execution

## Recommended install path

Use the published PyPI package with `uvx`.

Command:

```bash
uvx proxmox-mcp-plus
```

If `uvx` is not available, install `uv` first or fall back to:

```bash
pip install proxmox-mcp-plus
proxmox-mcp-plus
```

## Required runtime inputs

Minimum required environment variables when not using a JSON config file:

- `PROXMOX_HOST`
- `PROXMOX_USER`
- `PROXMOX_TOKEN_NAME`
- `PROXMOX_TOKEN_VALUE`

Common optional environment variables:

- `PROXMOX_PORT` default `8006`
- `PROXMOX_VERIFY_SSL` default `true`
- `PROXMOX_DEV_MODE` set `true` only for self-signed lab environments when `PROXMOX_VERIFY_SSL=false`
- `PROXMOX_SERVICE` default `PVE`
- `LOG_LEVEL` default `INFO`

Alternative:

- `PROXMOX_MCP_CONFIG` can point to a JSON config file. If that file exists, it is loaded before env-var fallback.

## Safe default client config

Use this when the user wants env-var based setup:

```json
{
  "mcpServers": {
    "proxmox-mcp-plus": {
      "command": "uvx",
      "args": ["proxmox-mcp-plus"],
      "env": {
        "PROXMOX_HOST": "your-proxmox-host",
        "PROXMOX_USER": "root@pam",
        "PROXMOX_TOKEN_NAME": "mcp-token",
        "PROXMOX_TOKEN_VALUE": "your-token-secret",
        "PROXMOX_PORT": "8006",
        "PROXMOX_VERIFY_SSL": "true",
        "PROXMOX_SERVICE": "PVE",
        "LOG_LEVEL": "INFO"
      }
    }
  }
}
```

## Self-signed lab setup

If the Proxmox endpoint uses a self-signed certificate, set both of these:

```json
{
  "PROXMOX_VERIFY_SSL": "false",
  "PROXMOX_DEV_MODE": "true"
}
```

Do not use this combination for production environments.

## Config-file based setup

If the repository is cloned locally and a JSON config file already exists, prefer:

```json
{
  "mcpServers": {
    "proxmox-mcp-plus": {
      "command": "uvx",
      "args": ["proxmox-mcp-plus"],
      "env": {
        "PROXMOX_MCP_CONFIG": "/absolute/path/to/proxmox-config/config.json"
      }
    }
  }
}
```

## Troubleshooting

- If the client reports `spawn uvx ENOENT`, install `uv` or switch to `pip install proxmox-mcp-plus`.
- If startup fails with missing auth credentials, confirm `PROXMOX_HOST`, `PROXMOX_USER`, `PROXMOX_TOKEN_NAME`, and `PROXMOX_TOKEN_VALUE` are all present.
- If startup fails on TLS validation in a homelab, either install a trusted certificate or set `PROXMOX_VERIFY_SSL=false` together with `PROXMOX_DEV_MODE=true`.
- If the server starts but tools fail, verify the Proxmox API token permissions and realm suffix in `PROXMOX_USER` such as `root@pam`.
