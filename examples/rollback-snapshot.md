# Roll Back a Risky Change with Snapshots

## Goal

Use an LLM or AI assistant as a safer operator by creating a checkpoint before a risky change and rolling back if needed.

## Prompt for Claude Desktop or Open WebUI

```text
Create a snapshot named pre-update for VM 210 on node pve.
If the post-change validation fails, roll back that snapshot and confirm the VM is back to the checkpoint.
```

## Example OpenAPI requests

Create the snapshot:

```bash
curl -X POST http://localhost:8811/create_snapshot \
  -H "Content-Type: application/json" \
  -d '{
    "node": "pve",
    "vmid": "210",
    "snapname": "pre-update",
    "vm_type": "qemu"
  }'
```

Roll it back:

```bash
curl -X POST http://localhost:8811/rollback_snapshot \
  -H "Content-Type: application/json" \
  -d '{
    "node": "pve",
    "vmid": "210",
    "snapname": "pre-update",
    "vm_type": "qemu"
  }'
```

## Expected operator outcome

- a repeatable rollback path for risky system changes
- a concrete workflow that is easy to demo to homelab and AI infra users
- a cleaner story than "the project has snapshot endpoints"
