# Client Setup

This page covers the common ways to connect MCP clients and HTTP clients to ProxmoxMCP-Plus.

## Choose A Connection Pattern

| Client or use case | Recommended pattern | Target |
| --- | --- | --- |
| Claude Desktop | MCP stdio | local `uvx proxmox-mcp-plus` or source checkout |
| Cursor | MCP stdio, or Streamable HTTP if hosted separately | local command or `http://<host>:8000/mcp` |
| VS Code / GitHub Copilot agent mode | MCP stdio, or Streamable HTTP where supported | local command or remote MCP endpoint |
| Codex | MCP stdio | local command configured in Codex MCP settings |
| OpenCode | MCP stdio with env file | examples under `proxmox-config/opencode/` |
| Open WebUI or HTTP-only tools | OpenAPI bridge | `http://127.0.0.1:8811/docs` and `/openapi.json` |
| Remote MCP clients | MCP Streamable HTTP | `http://<host>:8000/mcp` |

Use MCP stdio when the client can launch the server locally. Use MCP Streamable HTTP when the server runs on another host. Use OpenAPI when the consumer only understands HTTP or Swagger-style schemas.

## One-Click Installs

Use these buttons only if your client supports MCP install deeplinks.

[![Install in VS Code](https://img.shields.io/badge/VS_Code-Install_Server-0098FF?style=flat-square&logo=visualstudiocode&logoColor=white)](https://insiders.vscode.dev/redirect/mcp/install?name=proxmox-mcp-plus&inputs=%5B%7B%22id%22%3A%22proxmox_host%22%2C%22type%22%3A%22promptString%22%2C%22description%22%3A%22Proxmox%20host%22%7D%2C%7B%22id%22%3A%22proxmox_user%22%2C%22type%22%3A%22promptString%22%2C%22description%22%3A%22Proxmox%20user%2C%20for%20example%20root%40pam%22%7D%2C%7B%22id%22%3A%22proxmox_token_name%22%2C%22type%22%3A%22promptString%22%2C%22description%22%3A%22Proxmox%20API%20token%20name%22%7D%2C%7B%22id%22%3A%22proxmox_token_value%22%2C%22type%22%3A%22promptString%22%2C%22description%22%3A%22Proxmox%20API%20token%20value%22%2C%22password%22%3Atrue%7D%5D&config=%7B%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22proxmox-mcp-plus%22%5D%2C%22env%22%3A%7B%22PROXMOX_HOST%22%3A%22%24%7Binput%3Aproxmox_host%7D%22%2C%22PROXMOX_USER%22%3A%22%24%7Binput%3Aproxmox_user%7D%22%2C%22PROXMOX_TOKEN_NAME%22%3A%22%24%7Binput%3Aproxmox_token_name%7D%22%2C%22PROXMOX_TOKEN_VALUE%22%3A%22%24%7Binput%3Aproxmox_token_value%7D%22%2C%22PROXMOX_VERIFY_SSL%22%3A%22true%22%7D%7D)
[![Install in Cursor](https://img.shields.io/badge/Cursor-Install_Server-000000?style=flat-square)](https://cursor.com/en/install-mcp?name=proxmox-mcp-plus&config=eyJjb21tYW5kIjoidXZ4IHByb3htb3gtbWNwLXBsdXMiLCJlbnYiOnsiUFJPWE1PWF9IT1NUIjoieW91ci1wcm94bW94LWhvc3QiLCJQUk9YTU9YX1VTRVIiOiJyb290QHBhbSIsIlBST1hNT1hfVE9LRU5fTkFNRSI6Im1jcC10b2tlbiIsIlBST1hNT1hfVE9LRU5fVkFMVUUiOiJ5b3VyLXRva2VuLXNlY3JldCIsIlBST1hNT1hfVkVSSUZZX1NTTCI6InRydWUifX0=)

## Stdio Config

This config works for MCP clients that launch local server processes:

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
        "LOG_LEVEL": "INFO"
      }
    }
  }
}
```

If the repo is cloned locally and you want file-based config:

```json
{
  "mcpServers": {
    "proxmox-mcp-plus": {
      "command": "uvx",
      "args": ["proxmox-mcp-plus"],
      "env": {
        "PROXMOX_MCP_CONFIG": "/absolute/path/to/ProxmoxMCP-Plus/proxmox-config/config.json"
      }
    }
  }
}
```

For source checkouts that launch `main.py` directly:

```json
{
  "mcpServers": {
    "proxmox-mcp-plus": {
      "command": "python",
      "args": ["/absolute/path/to/ProxmoxMCP-Plus/main.py"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/ProxmoxMCP-Plus/src",
        "PROXMOX_MCP_CONFIG": "/absolute/path/to/ProxmoxMCP-Plus/proxmox-config/config.json"
      }
    }
  }
}
```

## Claude Desktop

An example Claude Desktop config is included at:

```text
proxmox-config/claude_desktop_config.example.json
```

Typical workflow:

1. Create and populate `proxmox-config/config.json`.
2. Update the example paths to your local machine.
3. Add the server entry to Claude Desktop's MCP config.
4. Restart Claude Desktop.
5. Confirm read-only tools such as `get_nodes`, `get_vms`, and `get_storage` appear.

## Cursor

Cursor can use the stdio config above. After adding the server, refresh the MCP server list and verify that read-only tools appear before running mutating workflows.

If the server is hosted remotely, run the Docker Streamable HTTP service and connect Cursor to:

```text
http://<docker-host>:8000/mcp
```

## VS Code

Use the install button above if your VS Code build supports MCP install deeplinks. Otherwise add the stdio config manually in the MCP server settings used by your VS Code agent extension.

For a remote Streamable HTTP deployment, use:

```json
{
  "type": "http",
  "url": "http://<host>:8000/mcp"
}
```

## Codex

Use the stdio config with `uvx proxmox-mcp-plus`. Prefer a config file path when you already have `proxmox-config/config.json` checked and validated locally.

Minimal server shape:

```toml
[mcp_servers.proxmox-mcp-plus]
command = "uvx"
args = ["proxmox-mcp-plus"]

[mcp_servers.proxmox-mcp-plus.env]
PROXMOX_MCP_CONFIG = "/absolute/path/to/ProxmoxMCP-Plus/proxmox-config/config.json"
```

## OpenCode

Examples for OpenCode live under:

```text
proxmox-config/opencode/
```

The example command sources environment variables and then launches the package. This is useful when you want to avoid hard-coding credentials in JSON.

## Open WebUI And HTTP Clients

For HTTP-native clients, run the OpenAPI bridge:

```bash
export PROXMOX_API_KEY="${PROXMOX_API_KEY:-$(openssl rand -hex 32)}"
docker compose --profile openapi up -d proxmox-mcp-api
```

Compose publishes on loopback by default; see [Compose network access and upgrades](../docker-compose.md) for remote clients.

Then connect locally to:

| Route | Purpose |
| --- | --- |
| `http://127.0.0.1:8811/docs` | Swagger UI |
| `http://127.0.0.1:8811/openapi.json` | OpenAPI schema |
| `http://127.0.0.1:8811/livez` | unauthenticated liveness |
| `http://127.0.0.1:8811/readyz` | authenticated readiness |
| `http://127.0.0.1:8811/health` | authenticated readiness alias |

Send authenticated requests with:

```text
Authorization: Bearer <PROXMOX_API_KEY>
```

## Post-Install Verification

After connecting any client:

1. Confirm the server starts without config validation errors.
2. Confirm read-only tools appear: `get_nodes`, `get_vms`, `get_containers`, `get_storage`.
3. In OpenAPI mode, confirm `/livez` returns `200`.
4. In OpenAPI mode, confirm authenticated `/health` or `/readyz` is healthy.
5. Confirm `execute_container_command` appears only if the config includes an `ssh` section.
6. Run mutating tools only after checking target IDs, storage, permissions, and command policy.

## Common Client Mistakes

- `uvx` is not installed or not on PATH.
- `PYTHONPATH` is missing when launching from a source checkout.
- `PROXMOX_MCP_CONFIG` points to the wrong file.
- The Proxmox API token lacks permissions for the requested operation.
- TLS verification is disabled but `PROXMOX_DEV_MODE` or `security.dev_mode` is not enabled.
- A client points to `http://<host>:8811` expecting MCP Streamable HTTP; use `http://<host>:8000/mcp` instead.
- `execute_container_command` is expected even though the `ssh` config is absent.

## Related Pages

- [Operator Guide](Operator-Guide)
- [Tool Selection Guide](Tool-Selection-Guide)
- [Security Guide](Security-Guide)
- [Troubleshooting](Troubleshooting)
