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
network_bridge - Network bridge name (optional, default: 'vmbr0')

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

CREATE_CONTAINER_DESC = """Create a new LXC container with specified configuration.

Parameters:
node* - Host node name (e.g. 'pve', 'pveZ3')
vmid* - Container ID number (e.g. '200', '300')
ostemplate* - OS template path (e.g. 'local:vztmpl/alpine-3.19-default_20240207_amd64.tar.xz')
hostname - Container hostname (optional, defaults to 'ct-{vmid}')
cores - Number of CPU cores (optional, default: 1)
memory - Memory size in MiB (optional, default: 512)
swap - Swap size in MiB (optional, default: 512)
disk_size - Root disk size in GB (optional, default: 8)
storage - Storage pool for rootfs (optional, auto-detects if not specified)
password - Root password (optional)
ssh_public_keys - SSH public keys for root user (optional)
network_bridge - Network bridge name (optional, default: 'vmbr0')
start_after_create - Start container after creation (optional, default: false)
unprivileged - Create unprivileged container (optional, default: true)

Examples:
- Create Alpine container: node='pveZ3', vmid='200', ostemplate='local:vztmpl/alpine-3.19-default_20240207_amd64.tar.xz'
- Create with custom resources: node='pve', vmid='201', ostemplate='local:vztmpl/ubuntu-22.04-standard_22.04-1_amd64.tar.zst', cores=2, memory=2048, disk_size=20
"""

DELETE_CONTAINER_DESC = """Delete/remove an LXC container completely.

WARNING: This operation permanently deletes the container and all its data!

Parameters:
selector* - Container selector: '123' | 'pve1:123' | 'pve1/name' | 'name' | comma list
force - Force deletion even if container is running (optional, default: false)

This will permanently remove:
- Container configuration
- Root filesystem and all data
- All snapshots
- Cannot be undone!

Examples:
- Delete container 200: selector='200'
- Delete by name: selector='my-container'
- Force delete running container: selector='pve:201', force=True
"""

# Storage tool descriptions
GET_STORAGE_DESC = """List storage pools across the cluster with their usage and configuration.

Example:
{"storage": "local-lvm", "type": "lvm", "used": "500GB", "total": "1TB"}"""

# Cluster tool descriptions
GET_CLUSTER_STATUS_DESC = """Get overall Proxmox cluster health and configuration status.

Example:
{"name": "proxmox", "quorum": "ok", "nodes": 3, "ha_status": "active"}"""

# Snapshot tool descriptions
LIST_SNAPSHOTS_DESC = """List all snapshots for a VM or container.

Parameters:
node* - Host node name (e.g. 'pve')
vmid* - VM or container ID (e.g. '100')
vm_type - Type: 'qemu' for VMs, 'lxc' for containers (default: 'qemu')

Example:
list_snapshots node='pve' vmid='100' vm_type='qemu'
"""

CREATE_SNAPSHOT_DESC = """Create a snapshot of a VM or container.

Parameters:
node* - Host node name
vmid* - VM or container ID
snapname* - Snapshot name (no spaces, e.g. 'before-update')
description - Optional description
vmstate - Include memory state (VMs only, default: false)
vm_type - Type: 'qemu' or 'lxc' (default: 'qemu')

Examples:
- Create VM snapshot: node='pve', vmid='100', snapname='pre-upgrade'
- Create with RAM state: node='pve', vmid='100', snapname='state1', vmstate=true
"""

DELETE_SNAPSHOT_DESC = """Delete a snapshot.

Parameters:
node* - Host node name
vmid* - VM or container ID
snapname* - Snapshot name to delete
vm_type - Type: 'qemu' or 'lxc' (default: 'qemu')

Example:
delete_snapshot node='pve' vmid='100' snapname='old-snapshot'
"""

ROLLBACK_SNAPSHOT_DESC = """Rollback VM/container to a previous snapshot.

WARNING: This will stop the VM/container and restore to the snapshot state!

Parameters:
node* - Host node name
vmid* - VM or container ID
snapname* - Snapshot name to restore
vm_type - Type: 'qemu' or 'lxc' (default: 'qemu')

Example:
rollback_snapshot node='pve' vmid='100' snapname='before-update'
"""

# ISO and Template tool descriptions
LIST_ISOS_DESC = """List available ISO images across the cluster.

Parameters:
node - Filter by node (optional)
storage - Filter by storage pool (optional)

Returns list of ISOs with filename, size, and storage location.
"""

LIST_TEMPLATES_DESC = """List available OS templates for container creation.

Parameters:
node - Filter by node (optional)
storage - Filter by storage pool (optional)

Returns list of templates (vztmpl) with name, size, and storage.
Use the returned Volume ID with create_container's ostemplate parameter.
"""

DOWNLOAD_ISO_DESC = """Download an ISO image from a URL to Proxmox storage.

Parameters:
node* - Target node name
storage* - Target storage pool (must support ISO content)
url* - URL to download from
filename* - Target filename (e.g. 'ubuntu-22.04-live-server-amd64.iso')
checksum - Optional checksum for verification
checksum_algorithm - Algorithm: sha256, sha512, md5 (default: sha256)

Example:
download_iso node='pve' storage='local' url='https://...' filename='ubuntu.iso'
"""

DELETE_ISO_DESC = """Delete an ISO or template from storage.

Parameters:
node* - Node name
storage* - Storage pool name
filename* - ISO/template filename to delete

Example:
delete_iso node='pve' storage='local' filename='old-distro.iso'
"""

# Backup and Restore tool descriptions
LIST_BACKUPS_DESC = """List available backups across the cluster.

Parameters:
node - Filter by node (optional)
storage - Filter by storage pool (optional)
vmid - Filter by VM/container ID (optional)

Returns backups with timestamp, size, compression, and notes.
Use the returned Volume ID with restore_backup.
"""

CREATE_BACKUP_DESC = """Create a backup of a VM or container.

Parameters:
node* - Node where VM/container runs
vmid* - VM or container ID to backup
storage* - Target backup storage
compress - Compression: 0, gzip, lz4, zstd (default: zstd)
mode - Backup mode: snapshot, suspend, stop (default: snapshot)
notes - Optional notes/description for the backup

Example:
create_backup node='pve' vmid='100' storage='backup-storage' compress='zstd'
"""

RESTORE_BACKUP_DESC = """Restore a VM or container from a backup.

Parameters:
node* - Target node for restore
archive* - Backup volume ID (from list_backups output)
vmid* - New VM/container ID for the restored machine
storage - Target storage for disks (optional, uses original if not specified)
unique - Generate unique MAC addresses (default: true)

Example:
restore_backup node='pve' archive='backup:backup/vzdump-qemu-100-2024_01_15.vma.zst' vmid='200'
"""

DELETE_BACKUP_DESC = """Delete a backup file from storage.

WARNING: This permanently deletes the backup!

Parameters:
node* - Node name
storage* - Storage pool name
volid* - Backup volume ID to delete

Example:
delete_backup node='pve' storage='backup-storage' volid='backup:backup/vzdump-qemu-100-2024_01_15.vma.zst'
"""
