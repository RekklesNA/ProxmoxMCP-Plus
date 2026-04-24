# Create a Test VM

## Goal

Create a small VM from an LLM or AI agent workflow without opening the Proxmox UI.

## Prompt for Claude Desktop or Open WebUI

```text
Create a small Debian test VM on node pve with 1 CPU, 2048 MB RAM, and a 12 GB disk.
Use the best available storage automatically, then start it and show me the resulting VM ID and status.
```

## Example OpenAPI request

```bash
curl -X POST http://localhost:8811/create_vm \
  -H "Content-Type: application/json" \
  -d '{
    "node": "pve",
    "vmid": "200",
    "name": "llm-test-vm",
    "cpus": 1,
    "memory": 2048,
    "disk_size": 12
  }'
```

Then start it:

```bash
curl -X POST http://localhost:8811/start_vm \
  -H "Content-Type: application/json" \
  -d '{
    "node": "pve",
    "vmid": "200"
  }'
```

## Expected operator outcome

- a new test VM exists on the target Proxmox node
- the same action is reachable from both MCP and OpenAPI
- the result can be returned to the user in LLM-friendly language
