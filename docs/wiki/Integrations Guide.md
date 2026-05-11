# Integrations Guide

This guide covers the main ways to connect clients and platforms to ProxmoxMCP-Plus.

## Integration Patterns

- `Direct MCP`: a client launches the server locally and talks over stdio
- `Native MCP HTTP`: a client connects to the Streamable HTTP MCP endpoint at `/mcp`
- `HTTP/OpenAPI`: a client talks to the FastAPI proxy over HTTP

Use direct MCP when the client launches local stdio servers. Use native MCP HTTP when the client supports Streamable HTTP and the server runs elsewhere, such as Docker on another host. Use OpenAPI when the client only understands HTTP or Swagger-style APIs.

## Claude Desktop

An example Claude Desktop config is included at `proxmox-config/claude_desktop_config.example.json`.

Key fields:

- `command`: points to your Python interpreter
- `args`: launches `-m proxmox_mcp.server`
- `PYTHONPATH`: points to the local `src` directory
- `PROXMOX_MCP_CONFIG`: points to your config file

Typical workflow:

1. Create and populate `proxmox-config/config.json`
2. Update the example paths to your local machine
3. Add the server entry to Claude Desktop's MCP config
4. Restart Claude Desktop and confirm the tools appear

## OpenCode

Examples for OpenCode live under `proxmox-config/opencode/`.

Files included:

- `opencode.jsonc.example`
- `proxmox-mcp.env.example`

The example command sources environment variables and then launches the package. This is useful when you want to avoid hard-coding credentials into the JSON client config.

## Generic MCP Clients

Any client that supports launching a stdio MCP server can use this project.

Typical requirements:

- Python environment with project dependencies installed
- `PYTHONPATH` pointing to `src` when running from source
- `PROXMOX_MCP_CONFIG` or equivalent environment variables

## Streamable HTTP MCP Clients

For remote MCP clients, run the native MCP HTTP Docker mode:

```bash
docker compose --profile mcp-http up -d proxmox-mcp-http
```

Then connect the client to:

```text
http://<docker-host>:8000/mcp
```

The default OpenAPI service on port `8811` is not an MCP Streamable HTTP endpoint; MCP HTTP clients should use `/mcp` on the native MCP service.

## OpenAPI Clients

For HTTP-native clients, run the OpenAPI wrapper and connect to:

- root: `http://<host>:8811/`
- docs: `http://<host>:8811/docs`
- schema: `http://<host>:8811/openapi.json`
- health: `http://<host>:8811/health`

This path works well for:

- internal portals
- small automation scripts
- tools that only speak REST/OpenAPI
- Open WebUI-style integrations

## OpenAPI Auth and CORS

The proxy supports:

- API key middleware, required by default
- automatic strict auth when `PROXMOX_API_KEY` is configured
- configurable CORS allow origins
- configurable path prefix and root path

OpenAPI mode refuses to start without `PROXMOX_API_KEY` unless
`PROXMOX_ALLOW_NO_AUTH=true` is set for local unauthenticated development.
Send authenticated requests with `Authorization: Bearer <PROXMOX_API_KEY>`.
If you expose the API outside a dev machine, also restrict origin and network access.

## Integration Checks

After connecting a client, verify:

- the server starts without config validation errors
- read-only tools such as `get_nodes` and `get_vms` are listed
- OpenAPI mode returns `/docs` and `/health`
- container SSH tools appear only when the `ssh` config exists

## Common Integration Mistakes

- `PYTHONPATH` not set when running from source
- `PROXMOX_MCP_CONFIG` points to the wrong file
- OpenAPI proxy runs, but `/health` stays degraded because the MCP subprocess did not start
- TLS verification disabled in config while `dev_mode` is false
- assuming `execute_container_command` should exist without an `ssh` section

## Related Pages

- [Operator Guide](Operator-Guide)
- [Security Guide](Security-Guide)
- [Troubleshooting](Troubleshooting)
