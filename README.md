# ProxmoxMCP-Plus

An enhanced Python-based Model Context Protocol (MCP) server for interacting with Proxmox virtualization platforms. This project extends [canvrno/ProxmoxMCP](https://github.com/canvrno/ProxmoxMCP) with additional features including complete OpenAPI integration and expanded virtualization management capabilities.

## Acknowledgments

This project is built upon the open-source project [ProxmoxMCP](https://github.com/canvrno/ProxmoxMCP) by [@canvrno](https://github.com/canvrno).

## New Features and Improvements

### Major Enhancements

| Feature Category | Description | Tools |
|-----------------|-------------|-------|
| **VM Lifecycle Management** | Complete virtual machine creation, management, and deletion | `create_vm`, `delete_vm` |
| **Power Management** | Control VM power states | `start_vm`, `stop_vm`, `shutdown_vm`, `reset_vm` |
| **Container Support** | Full LXC container lifecycle management | `get_containers`, `create_container`, `delete_container`, `start_container`, `stop_container`, `restart_container`, `update_container_resources` |
| **Snapshot Management** | Create and manage VM/container snapshots | `list_snapshots`, `create_snapshot`, `delete_snapshot`, `rollback_snapshot` |
| **Backup and Restore** | Backup and restore VMs and containers | `list_backups`, `create_backup`, `restore_backup`, `delete_backup` |
| **ISO and Template Management** | Manage installation media and templates | `list_isos`, `list_templates`, `download_iso`, `delete_iso` |
| **Monitoring** | Cluster and resource monitoring | `get_nodes`, `get_node_status`, `get_vms`, `get_storage`, `get_cluster_status` |
| **OpenAPI Integration** | REST API endpoints for external integration | 20+ API endpoints |
| **Security and Stability** | Production-grade error handling and validation | Token-based authentication, comprehensive logging |

## Built With

- [Proxmoxer](https://github.com/proxmoxer/proxmoxer) - Python wrapper for Proxmox API
- [MCP SDK](https://github.com/modelcontextprotocol/sdk) - Model Context Protocol SDK
- [Pydantic](https://docs.pydantic.dev/) - Data validation using Python type annotations

## Features

- Full integration with Cline and Open WebUI
- Built with the official MCP SDK
- Secure token-based authentication with Proxmox
- Complete VM lifecycle management (create, start, stop, reset, shutdown, delete)
- VM console command execution
- LXC container management support
- Intelligent storage type detection (LVM/file-based)
- Configurable logging system
- Type-safe implementation with Pydantic
- Rich output formatting with customizable themes
- OpenAPI REST endpoints for integration
- 20+ fully functional API endpoints
- Complete snapshot management (create, delete, rollback)
- Backup and restore capabilities
- ISO and template management


## Installation

### Prerequisites
- UV package manager (recommended)
- Python 3.9 or higher
- Git
- Access to a Proxmox server with API token credentials

Before starting, ensure you have:
- [ ] Proxmox server hostname or IP
- [ ] Proxmox API token (see [API Token Setup](#proxmox-api-token-setup))
- [ ] UV installed (`pip install uv`)

### Option 1: Quick Install (Recommended)

1. Clone and set up environment:
   ```bash
   # Clone repository
   git clone https://github.com/RekklesNA/ProxmoxMCP-Plus.git
   cd ProxmoxMCP-Plus

   # Create and activate virtual environment
   uv venv
   source .venv/bin/activate  # Linux/macOS
   # OR
   .\.venv\Scripts\Activate.ps1  # Windows
   ```

2. Install dependencies:
   ```bash
   # Install with development dependencies
   uv pip install -e ".[dev]"
   ```

3. Create configuration:
   ```bash
   # Create config directory and copy template
   mkdir -p proxmox-config
   cp proxmox-config/config.example.json proxmox-config/config.json
   ```

4. Edit `proxmox-config/config.json`:
   ```json
   {
       "proxmox": {
           "host": "PROXMOX_HOST",        # Required: Your Proxmox server address
           "port": 8006,                  # Optional: Default is 8006
           "verify_ssl": false,           # Optional: Set false for self-signed certs
           "service": "PVE"               # Optional: Default is PVE
       },
       "auth": {
           "user": "USER@pve",            # Required: Your Proxmox username
           "token_name": "TOKEN_NAME",    # Required: API token ID
           "token_value": "TOKEN_VALUE"   # Required: API token value
       },
       "logging": {
           "level": "INFO",               # Optional: DEBUG for more detail
           "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
           "file": "proxmox_mcp.log"      # Optional: Log to file
       },
       "mcp": {
           "host": "127.0.0.1",           # Optional: Host for SSE/STREAMABLE transports
           "port": 8000,                  # Optional: Port for SSE/STREAMABLE transports
           "transport": "STDIO"           # Optional: STDIO, SSE, or STREAMABLE
       }
   }
   ```

### Verifying Installation

1. Check Python environment:
   ```bash
   python -c "import proxmox_mcp; print('Installation OK')"
   ```

2. Run the tests:
   ```bash
   pytest
   ```

3. Verify configuration:
   ```bash
   # Linux/macOS
   PROXMOX_MCP_CONFIG="proxmox-config/config.json" python -m proxmox_mcp.server

   # Windows (PowerShell)
   $env:PROXMOX_MCP_CONFIG="proxmox-config\config.json"; python -m proxmox_mcp.server
   ```

## Configuration

### Proxmox API Token Setup
1. Log into your Proxmox web interface
2. Navigate to Datacenter -> Permissions -> API Tokens
3. Create a new API token:
   - Select a user (e.g., root@pam)
   - Enter a token ID (e.g., "mcp-token")
   - Uncheck "Privilege Separation" if you want full access
   - Save and copy both the token ID and secret

## Running the Server

### Development Mode
For testing and development:
```bash
# Activate virtual environment first
source .venv/bin/activate  # Linux/macOS
# OR
.\.venv\Scripts\Activate.ps1  # Windows

# Run the server
python -m proxmox_mcp.server
```

### MCP Transport Configuration

The MCP server supports multiple transport modes. Configure these in the `mcp` section of
your `proxmox-config/config.json`:

- `STDIO`: Default. Run over stdio for MCP clients like Claude Desktop/Cline.
- `SSE`: Serve MCP over Server-Sent Events (SSE).
- `STREAMABLE`: Serve MCP over streamable HTTP.

### OpenAPI Deployment (Production Ready)

Deploy ProxmoxMCP Plus as standard OpenAPI REST endpoints for integration with Open WebUI and other applications.

#### Quick OpenAPI Start
```bash
# Install mcpo (MCP-to-OpenAPI proxy)
pip install mcpo

# Start OpenAPI service on port 8811
./start_openapi.sh
```

#### Docker Deployment
```bash
# Build and run with Docker
docker build -t proxmox-mcp-api .
docker run -d --name proxmox-mcp-api -p 8811:8811 \
  -v $(pwd)/proxmox-config:/app/proxmox-config proxmox-mcp-api

# Or use Docker Compose
docker-compose up -d
```

#### Access OpenAPI Service
Once deployed, access your service at:
- **API Documentation**: http://your-server:8811/docs
- **OpenAPI Specification**: http://your-server:8811/openapi.json
- **Health Check**: http://your-server:8811/health

### Claude Desktop Integration

For Claude Desktop users, add this configuration to your MCP settings file:

**Configuration file location:**
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

**Quick Setup:**
1. Copy the example configuration:
   ```bash
   # macOS
   cp proxmox-config/claude_desktop_config.example.json ~/Library/Application\ Support/Claude/claude_desktop_config.json

   # Linux
   cp proxmox-config/claude_desktop_config.example.json ~/.config/Claude/claude_desktop_config.json

   # Windows (PowerShell)
   Copy-Item proxmox-config\claude_desktop_config.example.json $env:APPDATA\Claude\claude_desktop_config.json
   ```

2. Edit the file and replace the following values:
   - `/absolute/path/to/ProxmoxMCP-Plus` - Full path to your installation
   - `your-proxmox-host` - Your Proxmox server IP or hostname
   - `username@pve` - Your Proxmox username
   - `token-name` - Your API token name
   - `token-value` - Your API token value

**Configuration:**
```json
{
    "mcpServers": {
        "ProxmoxMCP-Plus": {
            "command": "/absolute/path/to/ProxmoxMCP-Plus/.venv/bin/python",
            "args": ["-m", "proxmox_mcp.server"],
            "env": {
                "PYTHONPATH": "/absolute/path/to/ProxmoxMCP-Plus/src",
                "PROXMOX_MCP_CONFIG": "/absolute/path/to/ProxmoxMCP-Plus/proxmox-config/config.json",
                "PROXMOX_HOST": "your-proxmox-host",
                "PROXMOX_USER": "username@pve",
                "PROXMOX_TOKEN_NAME": "token-name",
                "PROXMOX_TOKEN_VALUE": "token-value",
                "PROXMOX_PORT": "8006",
                "PROXMOX_VERIFY_SSL": "false",
                "PROXMOX_SERVICE": "PVE",
                "LOG_LEVEL": "DEBUG"
            }
        }
    }
}
```

**After configuration:**
1. Restart Claude Desktop
2. The ProxmoxMCP-Plus tools will be available in your conversations
3. You can now manage your Proxmox infrastructure through Claude Desktop!

### Cline Desktop Integration

For Cline users, add this configuration to your MCP settings file (typically at `~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`):

```json
{
    "mcpServers": {
        "ProxmoxMCP-Plus": {
            "command": "/absolute/path/to/ProxmoxMCP-Plus/.venv/bin/python",
            "args": ["-m", "proxmox_mcp.server"],
            "cwd": "/absolute/path/to/ProxmoxMCP-Plus",
            "env": {
                "PYTHONPATH": "/absolute/path/to/ProxmoxMCP-Plus/src",
                "PROXMOX_MCP_CONFIG": "/absolute/path/to/ProxmoxMCP-Plus/proxmox-config/config.json",
                "PROXMOX_HOST": "your-proxmox-host",
                "PROXMOX_USER": "username@pve",
                "PROXMOX_TOKEN_NAME": "token-name",
                "PROXMOX_TOKEN_VALUE": "token-value",
                "PROXMOX_PORT": "8006",
                "PROXMOX_VERIFY_SSL": "false",
                "PROXMOX_SERVICE": "PVE",
                "LOG_LEVEL": "DEBUG"
            },
            "disabled": false,
            "autoApprove": []
        }
    }
}
```

## Available Tools & API Endpoints

The server provides comprehensive MCP tools and corresponding REST API endpoints:

### VM Management Tools

#### create_vm 
Create a new virtual machine with specified resources.

**Parameters:**
- `node` (string, required): Name of the node
- `vmid` (string, required): ID for the new VM
- `name` (string, required): Name for the VM
- `cpus` (integer, required): Number of CPU cores (1-32)
- `memory` (integer, required): Memory in MB (512-131072)
- `disk_size` (integer, required): Disk size in GB (5-1000)
- `storage` (string, optional): Storage pool name
- `ostype` (string, optional): OS type (default: l26)

**API Endpoint:**
```http
POST /create_vm
Content-Type: application/json

{
    "node": "pve",
    "vmid": "200",
    "name": "my-vm",
    "cpus": 1,
    "memory": 2048,
    "disk_size": 10
}
```

**Example Response:**
```
VM 200 created successfully.

VM Configuration:
  - Name: my-vm
  - Node: pve
  - VM ID: 200
  - CPU Cores: 1
  - Memory: 2048 MB (2.0 GB)
  - Disk: 10 GB (local-lvm, raw format)
  - Storage Type: lvmthin
  - Network: virtio (bridge=vmbr0)
  - QEMU Agent: Enabled

Task ID: UPID:pve:001AB729:0442E853:682FF380:qmcreate:200:root@pam!mcp
```

#### VM Power Management

**start_vm**: Start a virtual machine
```http
POST /start_vm
{"node": "pve", "vmid": "200"}
```

**stop_vm**: Force stop a virtual machine
```http
POST /stop_vm
{"node": "pve", "vmid": "200"}
```

**shutdown_vm**: Gracefully shutdown a virtual machine
```http
POST /shutdown_vm
{"node": "pve", "vmid": "200"}
```

**reset_vm**: Reset (restart) a virtual machine
```http
POST /reset_vm
{"node": "pve", "vmid": "200"}
```

**delete_vm**: Completely delete a virtual machine
```http
POST /delete_vm
{"node": "pve", "vmid": "200", "force": false}
```

### Snapshot Management Tools

#### list_snapshots
List all snapshots for a VM or container.

**Parameters:**
- `node` (string, required): Host node name (e.g. 'pve')
- `vmid` (string, required): VM or container ID (e.g. '100')
- `vm_type` (string, optional): Type - 'qemu' for VMs, 'lxc' for containers (default: 'qemu')

**API Endpoint:** `POST /list_snapshots`

**Example:**
```http
POST /list_snapshots
{"node": "pve", "vmid": "100", "vm_type": "qemu"}
```

#### create_snapshot
Create a snapshot of a VM or container.

**Parameters:**
- `node` (string, required): Host node name
- `vmid` (string, required): VM or container ID
- `snapname` (string, required): Snapshot name (no spaces, e.g. 'before-update')
- `description` (string, optional): Description for the snapshot
- `vmstate` (boolean, optional): Include memory state (VMs only, default: false)
- `vm_type` (string, optional): Type - 'qemu' or 'lxc' (default: 'qemu')

**API Endpoint:**
```http
POST /create_snapshot
Content-Type: application/json

{
    "node": "pve",
    "vmid": "100",
    "snapname": "pre-upgrade",
    "description": "Before system upgrade",
    "vmstate": true
}
```

#### delete_snapshot
Delete a snapshot.

**Parameters:**
- `node` (string, required): Host node name
- `vmid` (string, required): VM or container ID
- `snapname` (string, required): Snapshot name to delete
- `vm_type` (string, optional): Type - 'qemu' or 'lxc' (default: 'qemu')

**API Endpoint:**
```http
POST /delete_snapshot
{"node": "pve", "vmid": "100", "snapname": "old-snapshot"}
```

#### rollback_snapshot
Rollback VM/container to a previous snapshot.

**WARNING:** This will stop the VM/container and restore to the snapshot state!

**Parameters:**
- `node` (string, required): Host node name
- `vmid` (string, required): VM or container ID
- `snapname` (string, required): Snapshot name to restore
- `vm_type` (string, optional): Type - 'qemu' or 'lxc' (default: 'qemu')

**API Endpoint:**
```http
POST /rollback_snapshot
{"node": "pve", "vmid": "100", "snapname": "before-update"}
```

### Container Management Tools

#### get_containers
List all LXC containers across the cluster.

**API Endpoint:** `POST /get_containers`

**Example Response:**
```
Containers

nginx-server (ID: 200)
  - Status: RUNNING
  - Node: pve
  - CPU Cores: 2
  - Memory: 1.5 GB / 2.0 GB (75.0%)
```

#### create_container
Create a new LXC container with specified configuration.

**Parameters:**
- `node` (string, required): Host node name (e.g. 'pve')
- `vmid` (string, required): Container ID number (e.g. '200')
- `ostemplate` (string, required): OS template path (e.g. 'local:vztmpl/alpine-3.19-default_20240207_amd64.tar.xz')
- `hostname` (string, optional): Container hostname (defaults to 'ct-{vmid}')
- `cores` (integer, optional): Number of CPU cores (default: 1)
- `memory` (integer, optional): Memory size in MiB (default: 512)
- `swap` (integer, optional): Swap size in MiB (default: 512)
- `disk_size` (integer, optional): Root disk size in GB (default: 8)
- `storage` (string, optional): Storage pool for rootfs (auto-detects if not specified)
- `password` (string, optional): Root password
- `ssh_public_keys` (string, optional): SSH public keys for root user
- `network_bridge` (string, optional): Network bridge name (default: 'vmbr0')
- `start_after_create` (boolean, optional): Start container after creation (default: false)
- `unprivileged` (boolean, optional): Create unprivileged container (default: true)

**API Endpoint:**
```http
POST /create_container
Content-Type: application/json

{
    "node": "pve",
    "vmid": "200",
    "ostemplate": "local:vztmpl/alpine-3.19-default_20240207_amd64.tar.xz",
    "hostname": "my-container",
    "cores": 2,
    "memory": 1024,
    "disk_size": 10
}
```

#### delete_container
Delete/remove an LXC container completely.

**WARNING:** This operation permanently deletes the container and all its data!

**Parameters:**
- `selector` (string, required): Container selector - '123' | 'pve1:123' | 'pve1/name' | 'name'
- `force` (boolean, optional): Force deletion even if container is running (default: false)

**API Endpoint:**
```http
POST /delete_container
Content-Type: application/json

{
    "selector": "200",
    "force": false
}
```

### Backup and Restore Tools

#### list_backups
List available backups across the cluster.

**Parameters:**
- `node` (string, optional): Filter by node
- `storage` (string, optional): Filter by storage pool
- `vmid` (string, optional): Filter by VM/container ID

**API Endpoint:** `POST /list_backups`

**Example:**
```http
POST /list_backups
{"node": "pve", "storage": "backup-storage"}
```

#### create_backup
Create a backup of a VM or container.

**Parameters:**
- `node` (string, required): Node where VM/container runs
- `vmid` (string, required): VM or container ID to backup
- `storage` (string, required): Target backup storage
- `compress` (string, optional): Compression - '0', 'gzip', 'lz4', 'zstd' (default: 'zstd')
- `mode` (string, optional): Backup mode - 'snapshot', 'suspend', 'stop' (default: 'snapshot')
- `notes` (string, optional): Notes/description for the backup

**API Endpoint:**
```http
POST /create_backup
Content-Type: application/json

{
    "node": "pve",
    "vmid": "100",
    "storage": "backup-storage",
    "compress": "zstd",
    "mode": "snapshot",
    "notes": "Weekly backup"
}
```

#### restore_backup
Restore a VM or container from a backup.

**Parameters:**
- `node` (string, required): Target node for restore
- `archive` (string, required): Backup volume ID (from list_backups output)
- `vmid` (string, required): New VM/container ID for the restored machine
- `storage` (string, optional): Target storage for disks (uses original if not specified)
- `unique` (boolean, optional): Generate unique MAC addresses (default: true)

**API Endpoint:**
```http
POST /restore_backup
Content-Type: application/json

{
    "node": "pve",
    "archive": "backup:backup/vzdump-qemu-100-2024_01_15.vma.zst",
    "vmid": "200",
    "unique": true
}
```

#### delete_backup
Delete a backup file from storage.

**WARNING:** This permanently deletes the backup!

**Parameters:**
- `node` (string, required): Node name
- `storage` (string, required): Storage pool name
- `volid` (string, required): Backup volume ID to delete

**API Endpoint:**
```http
POST /delete_backup
{
    "node": "pve",
    "storage": "backup-storage",
    "volid": "backup:backup/vzdump-qemu-100-2024_01_15.vma.zst"
}
```

### ISO and Template Management Tools

#### list_isos
List available ISO images across the cluster.

**Parameters:**
- `node` (string, optional): Filter by node
- `storage` (string, optional): Filter by storage pool

**API Endpoint:** `POST /list_isos`

**Returns:** List of ISOs with filename, size, and storage location.

#### list_templates
List available OS templates for container creation.

**Parameters:**
- `node` (string, optional): Filter by node
- `storage` (string, optional): Filter by storage pool

**API Endpoint:** `POST /list_templates`

**Returns:** List of templates (vztmpl) with name, size, and storage. Use the returned Volume ID with create_container's ostemplate parameter.

#### download_iso
Download an ISO image from a URL to Proxmox storage.

**Parameters:**
- `node` (string, required): Target node name
- `storage` (string, required): Target storage pool (must support ISO content)
- `url` (string, required): URL to download from
- `filename` (string, required): Target filename (e.g. 'ubuntu-22.04-live-server-amd64.iso')
- `checksum` (string, optional): Checksum for verification
- `checksum_algorithm` (string, optional): Algorithm - 'sha256', 'sha512', 'md5' (default: 'sha256')

**API Endpoint:**
```http
POST /download_iso
Content-Type: application/json

{
    "node": "pve",
    "storage": "local",
    "url": "https://releases.ubuntu.com/22.04/ubuntu-22.04-live-server-amd64.iso",
    "filename": "ubuntu-22.04-live-server-amd64.iso",
    "checksum": "a1b2c3..."
}
```

#### delete_iso
Delete an ISO or template from storage.

**Parameters:**
- `node` (string, required): Node name
- `storage` (string, required): Storage pool name
- `filename` (string, required): ISO/template filename to delete

**API Endpoint:**
```http
POST /delete_iso
{
    "node": "pve",
    "storage": "local",
    "filename": "old-distro.iso"
}
```

### Monitoring Tools

#### get_nodes
Lists all nodes in the Proxmox cluster.

**API Endpoint:** `POST /get_nodes`

**Example Response:**
```
Proxmox Nodes

pve-compute-01
  - Status: ONLINE
  - Uptime: 156d 12h
  - CPU Cores: 64
  - Memory: 186.5 GB / 512.0 GB (36.4%)
```

#### get_node_status
Get detailed status of a specific node.

**Parameters:**
- `node` (string, required): Name of the node

**API Endpoint:** `POST /get_node_status`

#### get_vms
List all VMs across the cluster.

**API Endpoint:** `POST /get_vms`

#### get_storage
List available storage pools.

**API Endpoint:** `POST /get_storage`

#### get_cluster_status
Get overall cluster status and health.

**API Endpoint:** `POST /get_cluster_status`

#### execute_vm_command
Execute a command in a VM's console using QEMU Guest Agent.

**Parameters:**
- `node` (string, required): Name of the node where VM is running
- `vmid` (string, required): ID of the VM
- `command` (string, required): Command to execute

**API Endpoint:** `POST /execute_vm_command`

**Requirements:**
- VM must be running
- QEMU Guest Agent must be installed and running in the VM

## Open WebUI Integration

### Configure Open WebUI

1. Access your Open WebUI instance
2. Navigate to **Settings** → **Connections** → **OpenAPI**
3. Add new API configuration:

```json
{
  "name": "Proxmox MCP API Plus",
  "base_url": "http://your-server:8811",
  "api_key": "",
  "description": "Enhanced Proxmox Virtualization Management API"
}
```

### Natural Language VM Creation

The system supports natural language VM creation requests through AI assistants. Example requests:

- "Can you create a VM with 1 cpu core and 2 GB ram with 10GB of storage disk"
- "Create a new VM for testing with minimal resources"
- "I need a development server with 4 cores and 8GB RAM"

The AI assistant will automatically call the appropriate APIs and provide detailed feedback.

## Storage Type Support

### Intelligent Storage Detection

ProxmoxMCP Plus automatically detects storage types and selects appropriate disk formats:

#### LVM Storage (local-lvm, vm-storage)
- Format: `raw`
- High performance
- Note: No cloud-init image support

#### File-based Storage (local, NFS, CIFS)
- Format: `qcow2`
- Cloud-init support
- Flexible snapshot capabilities

## Project Structure

```
ProxmoxMCP-Plus/
├── src/                          # Source code
│   └── proxmox_mcp/
│       ├── server.py             # Main MCP server implementation
│       ├── config/               # Configuration handling
│       ├── core/                 # Core functionality
│       ├── formatting/           # Output formatting and themes
│       ├── tools/                # Tool implementations
│       │   ├── vm.py             # VM management
│       │   ├── container.py      # Container management
│       │   └── console/          # VM console operations
│       └── utils/                # Utilities (auth, logging)
│
├── tests/                        # Unit test suite
├── test_scripts/                 # Integration tests & demos
│   ├── README.md                 # Test documentation
│   ├── test_vm_power.py          # VM power management tests
│   ├── test_vm_start.py          # VM startup tests
│   ├── test_create_vm.py         # VM creation tests
│   └── test_openapi.py           # OpenAPI service tests
│
├── proxmox-config/               # Configuration files
│   └── config.json               # Server configuration
│
├── Configuration Files
│   ├── pyproject.toml            # Project metadata
│   ├── docker-compose.yml        # Docker orchestration
│   ├── Dockerfile                # Docker image definition
│   └── requirements.in           # Dependencies
│
├── Scripts
│   ├── start_server.sh           # MCP server launcher
│   └── start_openapi.sh          # OpenAPI service launcher
│
└── Documentation
    ├── README.md                 # This file
    ├── VM_CREATION_GUIDE.md      # VM creation guide
    ├── OPENAPI_DEPLOYMENT.md     # OpenAPI deployment
    └── LICENSE                   # MIT License
```

## Testing

### Run Unit Tests
```bash
pytest
```

### Run Integration Tests
```bash
cd test_scripts

# Test VM power management
python test_vm_power.py

# Test VM creation
python test_create_vm.py

# Test OpenAPI service
python test_openapi.py
```

### API Testing with curl
```bash
# Test node listing
curl -X POST "http://your-server:8811/get_nodes" \
  -H "Content-Type: application/json" \
  -d "{}"

# Test VM creation
curl -X POST "http://your-server:8811/create_vm" \
  -H "Content-Type: application/json" \
  -d '{
    "node": "pve",
    "vmid": "300",
    "name": "test-vm",
    "cpus": 1,
    "memory": 2048,
    "disk_size": 10
  }'
```

## Production Security

### API Key Authentication
Set up secure API access:

```bash
export PROXMOX_API_KEY="your-secure-api-key"
export PROXMOX_MCP_CONFIG="/app/proxmox-config/config.json"
```

### Nginx Reverse Proxy
Example nginx configuration:

```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    location / {
        proxy_pass http://localhost:8811;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Troubleshooting

### Common Issues

1. **Port already in use**
   ```bash
   netstat -tlnp | grep 8811
   # Change port if needed
   mcpo --port 8812 -- ./start_server.sh
   ```

2. **Configuration errors**
   ```bash
   # Verify config file
   cat proxmox-config/config.json
   ```

3. **Connection issues**
   ```bash
   # Test Proxmox connectivity
   curl -k https://your-proxmox:8006/api2/json/version
   ```

### View Logs
```bash
# View service logs
tail -f proxmox_mcp.log

# Docker logs
docker logs proxmox-mcp-api -f
```

## Deployment Status

### Feature Completion Status

- [x] VM Creation (user requirement: 1 CPU + 2GB RAM + 10GB storage)
- [x] VM Power Management (start VPN-Server ID:101)
- [x] VM Deletion Feature
- [x] Container Management (LXC)
- [x] Container Creation and Deletion
- [x] Snapshot Management (create, delete, rollback)
- [x] Backup and Restore
- [x] ISO and Template Management
- [x] Storage Compatibility (LVM/file-based)
- [x] OpenAPI Integration (port 8811)
- [x] Open WebUI Integration
- [x] Error Handling & Validation
- [x] Complete Documentation & Testing

### Production Readiness

ProxmoxMCP Plus is ready for production deployment. The system supports natural language VM creation requests through AI assistants. When a user requests VM creation (e.g., "create a VM with 1 cpu core and 2 GB ram with 10GB of storage disk"), the system will:

1. Call the `create_vm` API endpoint
2. Automatically select appropriate storage and format
3. Create VMs matching the specified requirements
4. Return detailed configuration information
5. Provide next-step recommendations

## Development

After activating your virtual environment:

- Run tests: `pytest`
- Format code: `black .`
- Type checking: `mypy .`
- Lint: `ruff .`

## License

MIT License

## Special Thanks

- [@canvrno](https://github.com/canvrno) for the foundational project [ProxmoxMCP](https://github.com/canvrno/ProxmoxMCP)
- Thanks to the Proxmox community for providing the powerful virtualization platform
- Thanks to all contributors and users for their support

---

ProxmoxMCP Plus with OpenAPI integration is ready for production deployment.
