# Download an ISO and Create an LXC

## Goal

Show that the same control plane can manage both image delivery and guest lifecycle.

## Prompt for Claude Desktop or Open WebUI

```text
Download an ISO to Proxmox storage, then create a lightweight LXC test container,
start it, and tell me whether the HTTP/OpenAPI bridge is healthy.
```

## Example OpenAPI requests

Download an ISO:

```bash
curl -X POST http://localhost:8811/download_iso \
  -H "Content-Type: application/json" \
  -d '{
    "node": "pve",
    "storage": "local",
    "url": "https://example.com/test.iso",
    "filename": "test.iso"
  }'
```

Create an LXC:

```bash
curl -X POST http://localhost:8811/create_container \
  -H "Content-Type: application/json" \
  -d '{
    "node": "pve",
    "vmid": "300",
    "ostemplate": "local:vztmpl/alpine-3.22-default_20250617_amd64.tar.xz",
    "hostname": "llm-test-ct",
    "storage": "local-lvm"
  }'
```

Check the bridge:

```bash
curl -f http://localhost:8811/health
```

## Expected operator outcome

- the project demonstrates image management, LXC lifecycle, and API health in one short flow
- new users can see a practical LLM / AI infra use case instead of a long feature list
