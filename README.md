# ProxmoxMCP-Plus - Enhanced Proxmox MCP Server


An enhanced Python-based Model Context Protocol (MCP) server for interacting with Proxmox virtualization platforms. This project is built upon **[canvrno/ProxmoxMCP](https://github.com/canvrno/ProxmoxMCP)** with numerous new features and improvements, providing complete OpenAPI integration and more powerful virtualization management capabilities.

## Acknowledgments

This project is built upon the excellent open-source project [ProxmoxMCP](https://github.com/canvrno/ProxmoxMCP) by [@canvrno](https://github.com/canvrno). Thanks to the original author for providing the foundational framework and creative inspiration!

## 🆕 New Features and Improvements

### Major enhancements compared to the original version:

- ✨ **Complete VM Lifecycle Management**
  - Brand new `create_vm` tool - Support for creating virtual machines with custom configurations
  - New `delete_vm` tool - Safe VM deletion (with force deletion option)
  - Enhanced intelligent storage type detection (LVM/file-based)

- 🔧 **Extended Power Management Features**
  - `start_vm` - Start virtual machines
  - `stop_vm` - Force stop virtual machines
  - `shutdown_vm` - Graceful shutdown
  - `reset_vm` - Restart virtual machines

- 🐳 **New Container Support**
  - `get_containers` - List all LXC containers and their status
  - `start_container` - Start LXC container
  - `stop_container` - Stop LXC container
  - `restart_container` - Restart LXC container (forcefully/gracefully)
  - `update_container_resources` - Adjust container CPU, memory, swap, or extend disk
  - `execute_container_command` - Run shell commands inside a running LXC container via SSH + `pct exec` (no guest agent required; [see setup guide](docs/container-command-execution.md))

- 📊 **Enhanced Monitoring and Display**
  - Improved storage pool status monitoring
  - More detailed cluster health status checks
  - Rich output formatting and themes

- 🌐 **Complete OpenAPI Integration**
  - 11 complete REST API endpoints
  - Production-ready Docker deployment
  - Perfect Open WebUI integration
  - Natural language VM creation support

- 🛡️ **Production-grade Security and Stability**
  - Enhanced error handling mechanisms
  - Comprehensive parameter validation
  - Production-level logging
  - Complete unit test coverage

## Built With

- [Cline](https://github.com/cline/cline) - Autonomous coding agent - Go faster with Cline
- [Proxmoxer](https://github.com/proxmoxer/proxmoxer) - Python wrapper for Proxmox API
- [MCP SDK](https://github.com/modelcontextprotocol/sdk) - Model Context Protocol SDK
- [Pydantic](https://docs.pydantic.dev/) - Data validation using Python type annotations

## Features

- 🤖 Full integration with Cline and Open WebUI
- 🛠️ Built with the official MCP SDK
- 🔒 Secure token-based authentication with Proxmox
- 🖥️ Complete VM lifecycle management (create, start, stop, reset, shutdown, delete)
- 💻 VM and LXC container command execution
- 🐳 LXC container management support
- 🗃️ Intelligent storage type detection (LVM/file-based)
- 📝 Configurable logging system
- ✅ Type-safe implementation with Pydantic
- 🎨 Rich output formatting with customizable themes
- 🌐 OpenAPI REST endpoints for integration
- 📡 11 fully functional API endpoints


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
- **📖 API Documentation**: http://your-server:8811/docs
- **🔧 OpenAPI Specification**: http://your-server:8811/openapi.json
- **❤️ Health Check**: http://your-server:8811/health

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

The server provides 11 comprehensive MCP tools and corresponding REST API endpoints:

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
🎉 VM 200 created successfully!

📋 VM Configuration:
  • Name: my-vm
  • Node: pve
  • VM ID: 200
  • CPU Cores: 1
  • Memory: 2048 MB (2.0 GB)
  • Disk: 10 GB (local-lvm, raw format)
  • Storage Type: lvmthin
  • Network: virtio (bridge=vmbr0)
  • QEMU Agent: Enabled

🔧 Task ID: UPID:pve:001AB729:0442E853:682FF380:qmcreate:200:root@pam!mcp
```

#### VM Power Management 🆕

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

**delete_vm** 🆕: Completely delete a virtual machine
```http
POST /delete_vm
{"node": "pve", "vmid": "200", "force": false}
```

### 🆕 Container Management Tools

#### get_containers 🆕
List all LXC containers across the cluster.

**API Endpoint:** `POST /get_containers`

**Example Response:**
```
🐳 Containers

🐳 nginx-server (ID: 200)
  • Status: RUNNING
  • Node: pve
  • CPU Cores: 2
  • Memory: 1.5 GB / 2.0 GB (75.0%)
```

### Monitoring Tools

#### get_nodes
Lists all nodes in the Proxmox cluster.

**API Endpoint:** `POST /get_nodes`

**Example Response:**
```
🖥️ Proxmox Nodes

🖥️ pve-compute-01
  • Status: ONLINE
  • Uptime: ⏳ 156d 12h
  • CPU Cores: 64
  • Memory: 186.5 GB / 512.0 GB (36.4%)
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

#### execute_container_command 🆕
Execute a shell command inside a running LXC container.

Unlike VMs, LXC containers have no QEMU guest agent equivalent — `pct exec` is the only official
mechanism, and it is a CLI tool that must be run directly on the Proxmox host. This tool SSHes to
the appropriate Proxmox node and invokes `pct exec` there, so no guest agent installation is
required inside the container.

**Parameters:**
- `selector` (string, required): Container selector — `123`, `pve1:123`, `pve1/name`, or `name`
- `command` (string, required): Shell command to run inside the container

**API Endpoint:** `POST /execute_container_command`

**Example Response:**
```json
{"success": true, "output": "Linux ct-101 6.1.0-31-amd64", "error": "", "exit_code": 0}
```

**Requirements:**
- Container must be running
- An `ssh` section must be present in the MCP config (the tool is opt-in and returns a clear error
  if SSH is not configured)

**Security:** This feature uses SSH to reach the Proxmox node. The recommended setup creates a
dedicated `mcp-agent` user with passwordless sudo scoped exclusively to `pct exec`, limiting what
a compromised MCP server could do on the host. See the
[Container Command Execution guide](docs/container-command-execution.md) for the full security
model and step-by-step setup instructions.

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

Users can now request VMs using natural language:

- **"Can you create a VM with 1 cpu core and 2 GB ram with 10GB of storage disk"**
- **"Create a new VM for testing with minimal resources"**
- **"I need a development server with 4 cores and 8GB RAM"**

The AI assistant will automatically call the appropriate APIs and provide detailed feedback.

## Storage Type Support

### Intelligent Storage Detection

ProxmoxMCP Plus automatically detects storage types and selects appropriate disk formats:

#### LVM Storage (local-lvm, vm-storage)
- ✅ Format: `raw`
- ✅ High performance
- ⚠️ No cloud-init image support

#### File-based Storage (local, NFS, CIFS)
- ✅ Format: `qcow2`
- ✅ Cloud-init support
- ✅ Flexible snapshot capabilities

## Project Structure

```
ProxmoxMCP-Plus/
├── 📁 src/                          # Source code
│   └── proxmox_mcp/
│       ├── server.py                # Main MCP server implementation
│       ├── config/                  # Configuration handling
│       ├── core/                    # Core functionality
│       ├── formatting/              # Output formatting and themes
│       ├── tools/                   # Tool implementations
│       │   ├── vm.py               # VM management (create/power) 🆕
│       │   ├── container.py        # Container management 🆕
│       │   └── console/            # VM console operations
│       └── utils/                   # Utilities (auth, logging)
│
├── 📁 tests/                       # Unit test suite
├── 📁 test_scripts/                # Integration tests & demos
│   ├── README.md                   # Test documentation
│   ├── test_vm_power.py           # VM power management tests 🆕
│   ├── test_vm_start.py           # VM startup tests
│   ├── test_create_vm.py          # VM creation tests 🆕
│   └── test_openapi.py            # OpenAPI service tests
│
├── 📁 proxmox-config/              # Configuration files
│   └── config.json                # Server configuration
│
├── 📄 Configuration Files
│   ├── pyproject.toml             # Project metadata
│   ├── docker-compose.yml         # Docker orchestration
│   ├── Dockerfile                 # Docker image definition
│   └── requirements.in            # Dependencies
│
├── 📄 Scripts
│   ├── start_server.sh            # MCP server launcher
│   └── start_openapi.sh           # OpenAPI service launcher
│
├── 📁 docs/                        # Extended documentation
│   └── container-command-execution.md  # Container exec: security model & SSH setup
│
└── 📄 Documentation
    ├── README.md                  # This file
    ├── VM_CREATION_GUIDE.md       # VM creation guide
    ├── OPENAPI_DEPLOYMENT.md      # OpenAPI deployment
    └── LICENSE                    # MIT License
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

### ✅ Feature Completion: 100%

- [x] VM Creation (user requirement: 1 CPU + 2GB RAM + 10GB storage) 🆕
- [x] VM Power Management (start VPN-Server ID:101) 🆕
- [x] VM Deletion Feature 🆕
- [x] Container Management (LXC) 🆕
- [x] Container Command Execution via SSH + `pct exec` (opt-in, scoped sudo) 🆕
- [x] Storage Compatibility (LVM/file-based)
- [x] OpenAPI Integration (port 8811)
- [x] Open WebUI Integration
- [x] Error Handling & Validation
- [x] Complete Documentation & Testing

### Production Ready!

**ProxmoxMCP Plus is now fully ready for production use!**

When users say **"Can you create a VM with 1 cpu core and 2 GB ram with 10GB of storage disk"**, the AI assistant can:

1. 📞 Call the `create_vm` API
2. 🔧 Automatically select appropriate storage and format
3. 🎯 Create VMs that match requirements
4. 📊 Return detailed configuration information
5. 💡 Provide next-step recommendations

## Development

After activating your virtual environment:

- Run tests: `pytest`
- Format code: `black .`
- Type checking: `mypy .`
- Lint: `ruff .`

## License

MIT License

## Special Thanks

- Thanks to [@canvrno](https://github.com/canvrno) for the excellent foundational project [ProxmoxMCP](https://github.com/canvrno/ProxmoxMCP)
- Thanks to the Proxmox community for providing the powerful virtualization platform
- Thanks to all contributors and users for their support

---

**Ready to Deploy!** 🎉 Your enhanced Proxmox MCP service with OpenAPI integration is ready for production use.
