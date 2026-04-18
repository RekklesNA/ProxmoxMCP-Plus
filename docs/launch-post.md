# Launch Post Draft

## Suggested Title

I built an MCP + OpenAPI server that lets LLMs and AI agents operate real Proxmox VE workflows

## Short post

I built `ProxmoxMCP-Plus`, an open-source control plane for Proxmox VE that exposes the same operations through both `MCP` and `OpenAPI`.

That means a user can:

- use `Claude Desktop` or `Open WebUI`
- ask an LLM or AI agent to create a VM or LXC
- run snapshot, backup, restore, ISO, and container execution workflows
- call the same system from plain HTTP tools through `/openapi.json`

What mattered to me was not just adding endpoints, but proving the project works on a real lab.

I verified these paths against a live Proxmox environment:

- VM create / start / stop / delete
- snapshot create / rollback / delete
- backup / restore
- ISO download / delete
- LXC create / start / stop / delete
- container SSH-backed command execution
- OpenAPI `/health`
- Docker image build and `/health`

Repo:

- GitHub: https://github.com/RekklesNA/ProxmoxMCP-Plus
- PyPI: https://pypi.org/project/proxmox-mcp-plus/

If you work on homelab automation, AI infra, MCP tooling, or self-hosted assistant workflows, feedback is welcome.

## Shorter X / social version

Built `ProxmoxMCP-Plus`: an open-source MCP + OpenAPI server for Proxmox VE.

It lets LLMs and AI agents do real VM, LXC, snapshot, backup, restore, ISO, and container execution workflows.

Not just docs either: core paths were verified on a live Proxmox lab.

GitHub: https://github.com/RekklesNA/ProxmoxMCP-Plus

## Show HN version

Show HN: ProxmoxMCP-Plus - MCP + OpenAPI control plane for Proxmox VE

I wanted a way to let LLMs and AI agents interact with Proxmox without writing one-off scripts for every workflow.

So I built `ProxmoxMCP-Plus`, which exposes Proxmox operations through:

- `MCP` for assistant clients such as Claude Desktop and Open WebUI
- `OpenAPI` for HTTP clients and internal tooling

The main thing I wanted to prove was that it is not just a wrapper around documentation.

I tested live workflows for VM, LXC, snapshot, backup, restore, ISO, container SSH execution, local `/health`, and Docker `/health`.

Repo: https://github.com/RekklesNA/ProxmoxMCP-Plus
