# Docker Compose modes and host bindings

The example Compose file has two opt-in services. Choose `openapi` for the OpenAPI bridge or `mcp-http` for native MCP Streamable HTTP. Plain `docker compose up -d` selects no services. This does not stop containers that were already running.

Create `proxmox-config/config.json` from `proxmox-config/config.example.json` and configure the Proxmox API credentials first. The named `proxmox-jobs` volume preserves application state across container recreation.

## Native MCP HTTP only

```bash
export MCP_API_KEY="$(openssl rand -hex 32)"
docker compose --profile mcp-http up -d --build proxmox-mcp-http
```

Connect locally to `http://127.0.0.1:8000/mcp` with `Authorization: Bearer <MCP_API_KEY>`. This mode does not need `PROXMOX_API_KEY`. Existing explicit external-auth opt-out settings for MCP HTTP still apply; a configured MCP key is always enforced.

## OpenAPI only

```bash
export PROXMOX_API_KEY="$(openssl rand -hex 32)"
docker compose --profile openapi up -d --build proxmox-mcp-api
curl -f http://127.0.0.1:8811/livez
```

Use `Authorization: Bearer <PROXMOX_API_KEY>` on protected OpenAPI routes. This mode does not need `MCP_API_KEY`. Both profiles may be enabled together when both endpoints are wanted.

Compose interpolates configuration before selecting services. API-key variables therefore use empty defaults in the YAML so an inactive mode cannot block `config`, `ps`, or startup of the other mode. The selected application still refuses to start without its required credential; interpolation does not relax authentication.

## Host, reverse proxy and tunnel access

Host-published ports default to IPv4 loopback: `127.0.0.1:8000` and `127.0.0.1:8811`. A host-side reverse proxy or tunnel can use those addresses. Container listeners remain on `0.0.0.0` inside their Docker network so publishing and service-to-service routing work.

For a proxy/tunnel running in a separate container, attach it to the same Docker network and use `http://proxmox-mcp-http:8000/mcp` or `http://proxmox-mcp-api:8811`. The loopback host bindings do not isolate services from other containers attached to that network.

To expose one published port on additional host interfaces, explicitly select its bind address in the shell or Compose `.env`:

```bash
# Example: publish native MCP HTTP on all IPv4 host interfaces.
MCP_HTTP_BIND_ADDRESS=0.0.0.0 docker compose --profile mcp-http up -d --force-recreate proxmox-mcp-http
```

Use `OPENAPI_BIND_ADDRESS` for OpenAPI. A specific host IP can be used instead of `0.0.0.0`; overriding one mode does not widen the other. Authentication, transport security and any proxy Host/Origin settings still need to match the deployment.

## Upgrade from v0.6.5 and earlier

Recreate each wanted service with its explicit profile to apply the new bindings and hardening. For example, after setting its credential:

```bash
docker compose --profile openapi up -d --build --force-recreate proxmox-mcp-api
```

If switching to MCP-only operation, explicitly stop an old OpenAPI container that was started by the previous default:

```bash
docker compose --profile openapi stop proxmox-mcp-api
docker compose --profile mcp-http up -d --build --force-recreate proxmox-mcp-http
```

Both example services drop all Linux capabilities and enable `no-new-privileges`. The image already runs as a non-root user. The bare image's default OpenAPI mode remains unchanged; profile selection applies to Compose.

Related: [issue #183](https://github.com/RekklesNA/ProxmoxMCP-Plus/issues/183), [Docker profiles](https://docs.docker.com/compose/how-tos/profiles/), [Compose interpolation](https://docs.docker.com/reference/compose-file/interpolation/).
