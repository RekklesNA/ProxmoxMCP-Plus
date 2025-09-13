"""
Tool descriptions for Proxmox MCP tools.
"""

# Node tool descriptions
GET_NODES_DESC = """List all nodes in the Proxmox cluster with their status, CPU, memory, and role information.

Example:
{"node": "pve1", "status": "online", "cpu_usage": 0.15, "memory": {"used": "8GB", "total": "32GB"}}"""

GET_NODE_STATUS_DESC = """Get detailed status information for a specific Proxmox node.

Parameters:
node* - Name/ID of node to query (e.g. 'pve1')

Example:
{"cpu": {"usage": 0.15}, "memory": {"used": "8GB", "total": "32GB"}}"""

# VM tool descriptions
GET_VMS_DESC = """List all virtual machines across the cluster with their status and resource usage.

Example:
{"vmid": "100", "name": "ubuntu", "status": "running", "cpu": 2, "memory": 4096}"""

CREATE_VM_DESC = """Create a new virtual machine with specified configuration.

Parameters:
node* - Host node name (e.g. 'pve')
vmid* - New VM ID number (e.g. '200', '300')
name* - VM name (e.g. 'my-new-vm', 'web-server')
cpus* - Number of CPU cores (e.g. 1, 2, 4)
memory* - Memory size in MB (e.g. 2048 for 2GB, 4096 for 4GB)
disk_size* - Disk size in GB (e.g. 10, 20, 50)
storage - Storage name (optional, will auto-detect if not specified)
ostype - OS type (optional, default: 'l26' for Linux)

Examples:
- Create VM with 1 CPU, 2GB RAM, 10GB disk: node='pve', vmid='200', name='test-vm', cpus=1, memory=2048, disk_size=10
- Create VM with 2 CPUs, 4GB RAM, 20GB disk: node='pve', vmid='201', name='web-server', cpus=2, memory=4096, disk_size=20"""

EXECUTE_VM_COMMAND_DESC = """Execute commands in a VM via QEMU guest agent.

Parameters:
node* - Host node name (e.g. 'pve1')
vmid* - VM ID number (e.g. '100')
command* - Shell command to run (e.g. 'uname -a')

Example:
{"success": true, "output": "Linux vm1 5.4.0", "exit_code": 0}"""

# VM Power Management tool descriptions
START_VM_DESC = """Start a virtual machine.

Parameters:
node* - Host node name (e.g. 'pve')
vmid* - VM ID number (e.g. '101')

Example:
Power on VPN-Server with ID 101 on node pve"""

STOP_VM_DESC = """Stop a virtual machine (force stop).

Parameters:
node* - Host node name (e.g. 'pve')  
vmid* - VM ID number (e.g. '101')

Example:
Force stop VPN-Server with ID 101 on node pve"""

SHUTDOWN_VM_DESC = """Shutdown a virtual machine gracefully.

Parameters:
node* - Host node name (e.g. 'pve')
vmid* - VM ID number (e.g. '101')

Example:
Gracefully shutdown VPN-Server with ID 101 on node pve"""

RESET_VM_DESC = """Reset (restart) a virtual machine.

Parameters:
node* - Host node name (e.g. 'pve')
vmid* - VM ID number (e.g. '101')

Example:
Reset VPN-Server with ID 101 on node pve"""

DELETE_VM_DESC = """Delete/remove a virtual machine completely.

⚠️ WARNING: This operation permanently deletes the VM and all its data!

Parameters:
node* - Host node name (e.g. 'pve')
vmid* - VM ID number (e.g. '998')
force - Force deletion even if VM is running (optional, default: false)

This will permanently remove:
- VM configuration
- All virtual disks
- All snapshots
- Cannot be undone!

Example:
Delete test VM with ID 998 on node pve"""

# Container tool descriptions
GET_CONTAINERS_DESC = """List LXC containers across the cluster (or filter by node).

Parameters:
- node (optional): Node name to filter (e.g. 'pve1')
- include_stats (bool, default true): Include live CPU/memory stats
- include_raw (bool, default false): Include raw Proxmox API payloads for debugging
- format_style ('pretty'|'json', default 'pretty'): Pretty text or raw JSON list

Notes:
- Live stats from /nodes/{node}/lxc/{vmid}/status/current.
- If maxmem is 0 (unlimited), memory limit falls back to /config.memory (MiB).
- If live returns zeros, the most recent RRD sample is used as a fallback.
- Fields provided: cores (CPU cores/cpulimit), memory (MiB limit), cpu_pct, mem_bytes, maxmem_bytes, mem_pct, unlimited_memory.
"""

START_CONTAINER_DESC = """Start one or more LXC containers.
selector: '123' | 'pve1:123' | 'pve1/name' | 'name' | comma list
Example: start_container selector='pve1:101,pve2/web'
"""

STOP_CONTAINER_DESC = """Stop LXC containers. graceful=True uses shutdown; otherwise force stop.
selector: same grammar as start_container
timeout_seconds: 10 (default)
"""

RESTART_CONTAINER_DESC = """Restart LXC containers (reboot).
selector: same grammar as start_container
"""

UPDATE_CONTAINER_RESOURCES_DESC = """Update resources for one or more LXC containers.

selector: same grammar as start_container
cores: New CPU core count (optional)
memory: New memory limit in MiB (optional)
swap: New swap limit in MiB (optional)
disk_gb: Additional disk size in GiB to add (optional)
disk: Disk identifier to resize (default 'rootfs')
"""

# Storage tool descriptions
GET_STORAGE_DESC = """List storage pools across the cluster with their usage and configuration.

Example:
{"storage": "local-lvm", "type": "lvm", "used": "500GB", "total": "1TB"}"""

# Cluster tool descriptions
GET_CLUSTER_STATUS_DESC = """Get overall Proxmox cluster health and configuration status.

Example:
{"name": "proxmox", "quorum": "ok", "nodes": 3, "ha_status": "active"}"""
