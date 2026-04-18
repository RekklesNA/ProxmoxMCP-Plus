# 20-30 Second Demo Script

## Goal

Record a short GIF or video that shows:

`Claude Desktop or Open WebUI -> Proxmox action -> /health OK`

## Shot list

1. Open Claude Desktop or Open WebUI.
2. Paste this prompt:

```text
Create a small Proxmox test VM, snapshot it, and confirm the OpenAPI bridge is healthy.
```

3. Cut to the MCP / HTTP result:

- VM created or started
- snapshot created
- `/health` returns `{"status":"ok","connected_to_mcp":true}`

4. End frame:

- show `VM / LXC / Backup / Restore / Snapshot / ISO / SSH / OpenAPI / Docker`
- show repo URL

## Recording tips

- keep the clip under 30 seconds
- avoid terminal noise that does not prove value
- show one prompt and one concrete Proxmox result
- end with `/health` because it is easy to understand even for non-Proxmox users
