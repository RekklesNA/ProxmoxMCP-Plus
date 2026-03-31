# OpenCode Configuration

This folder contains example configuration files for OpenCode with Proxmox MCP.

## Files

| File | Purpose |
|------|---------|
| `opencode.jsonc.example` | OpenCode configuration template |
| `proxmox-mcp.env.example` | Proxmox MCP environment variables template |

## Setup Instructions

### 1. Copy Examples to Project Root

```bash
# From project root
cp proxmox-config/opencode/opencode.jsonc.example opencode.jsonc
cp proxmox-config/opencode/proxmox-mcp.env.example proxmox-mcp.env
```

### 2. Configure Environment Variables

Edit `proxmox-mcp.env` with your Proxmox credentials:

```bash
export PROXMOX_HOST=your-proxmox-host
export PROXMOX_PORT=8006
export PROXMOX_USER=user@pam
export PROXMOX_TOKEN_NAME=your-token-name
export PROXMOX_TOKEN_VALUE=your-token-secret-value
export PROXMOX_VERIFY_SSL=false
export PROXMOX_SERVICE=PVE
export LOG_LEVEL=INFO
```

### 3. How MCP Loads Environment

The MCP command in `opencode.jsonc` sources the environment file automatically:

```json
"command": ["sh", "-c", ". ./proxmox-mcp.env && uvx --from git+https://github.com/NewsRx/ProxmoxMCP-Plus.git proxmox-mcp"]
```

**No manual sourcing needed** - OpenCode runs the MCP, and the MCP command sources `proxmox-mcp.env` before starting.

## Security

**Never commit files with real credentials to version control!**

Both `opencode.jsonc` and `proxmox-mcp.env` are excluded via `.git/info/exclude`.

*Co-authored with AI: OpenCode (ollama-cloud/glm-5)*