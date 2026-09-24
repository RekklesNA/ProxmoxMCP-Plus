"""
Output templates for Proxmox MCP resource types.
"""
from typing import Dict, List, Any
from proxmox_mcp.formatting.formatters import ProxmoxFormatters
from proxmox_mcp.formatting.theme import ProxmoxTheme

class ProxmoxTemplates:
    """Output templates for different Proxmox resource types."""
    
    @staticmethod
    def node_list(nodes: List[Dict[str, Any]]) -> str:
        """Template for node list output.
        
        Args:
            nodes: List of node data dictionaries
            
        Returns:
            Formatted node list string
        """
        result = [f"{ProxmoxTheme.RESOURCES['node']} Proxmox Nodes"]
        
        for node in nodes:
            # Get node status
            status = node.get("status", "unknown")
            
            # Get memory info
            memory = node.get("memory", {})
            memory_used = memory.get("used", 0)
            memory_total = memory.get("total", 0)
            memory_percent = (memory_used / memory_total * 100) if memory_total > 0 else 0
            
            # Format node info
            result.extend([
                "",  # Empty line between nodes
                f"{ProxmoxTheme.RESOURCES['node']} {node['node']}",
                f"  - Status: {status.upper()}",
                f"  - Uptime: {ProxmoxFormatters.format_uptime(node.get('uptime', 0))}",
                f"  - CPU Cores: {node.get('maxcpu', 'N/A')}",
                f"  - Memory: {ProxmoxFormatters.format_bytes(memory_used)} / "
                f"{ProxmoxFormatters.format_bytes(memory_total)} ({memory_percent:.1f}%)"
            ])
            
            # Add disk usage if available
            disk = node.get("disk", {})
            if disk:
                disk_used = disk.get("used", 0)
                disk_total = disk.get("total", 0)
                disk_percent = (disk_used / disk_total * 100) if disk_total > 0 else 0
                result.append(
                    f"  - Disk: {ProxmoxFormatters.format_bytes(disk_used)} / "
                    f"{ProxmoxFormatters.format_bytes(disk_total)} ({disk_percent:.1f}%)"
                )
            
        return "\n".join(result)
    
    @staticmethod
    def node_status(node: str, status: Dict[str, Any]) -> str:
        """Template for detailed node status output.
        
        Args:
            node: Node name
            status: Node status data
            
        Returns:
            Formatted node status string
        """
        cpuinfo = status.get("cpuinfo", {}) or {}
        memory = status.get("memory", {}) or {}
        memory_used = memory.get("used", 0)
        memory_total = memory.get("total", 0)
        memory_percent = (memory_used / memory_total * 100) if memory_total > 0 else 0

        result = [
            f"{ProxmoxTheme.RESOURCES['node']} Node: {node}",
            f"  - Status: {status.get('status', 'unknown').upper()}",
            f"  - Uptime: {ProxmoxFormatters.format_uptime(status.get('uptime', 0))}",
            # The /nodes/{node}/status endpoint reports the CPU count nested
            # under cpuinfo.cpus. The top-level maxcpu field is the node-list
            # field and is not present here, so we fall back to it for
            # forward compatibility.
            f"  - CPU Cores: {cpuinfo.get('cpus', status.get('maxcpu', 'N/A'))}",
        ]

        # CPU detail. The endpoint returns the model, the core/socket layout and
        # the nominal clock, none of which were surfaced before.
        if cpuinfo.get("model"):
            result.append(f"  - CPU Model: {cpuinfo['model']}")

        layout = []
        if cpuinfo.get("cores"):
            layout.append(f"{cpuinfo['cores']} cores")
        if cpuinfo.get("sockets"):
            layout.append(f"{cpuinfo['sockets']} sockets")
        if layout:
            line = f"  - CPU Layout: {' / '.join(layout)}"
            try:
                line += f" @ {float(cpuinfo['mhz']):.0f} MHz"
            except (KeyError, TypeError, ValueError):
                pass
            result.append(line)

        cpu_usage = status.get("cpu")
        if isinstance(cpu_usage, (int, float)):
            line = f"  - CPU Usage: {cpu_usage * 100:.1f}%"
            iowait = status.get("wait")
            if isinstance(iowait, (int, float)):
                line += f" (iowait {iowait * 100:.1f}%)"
            result.append(line)

        loadavg = status.get("loadavg")
        if loadavg:
            result.append(
                f"  - Load Average: {', '.join(str(value) for value in loadavg)}"
            )

        result.append(
            f"  - Memory: {ProxmoxFormatters.format_bytes(memory_used)} / "
            f"{ProxmoxFormatters.format_bytes(memory_total)} ({memory_percent:.1f}%)"
        )
        if memory.get("available") is not None:
            result.append(
                f"  - Memory Available: "
                f"{ProxmoxFormatters.format_bytes(memory['available'])}"
            )

        swap = status.get("swap", {}) or {}
        swap_total = swap.get("total", 0) or 0
        if swap_total:
            swap_used = swap.get("used", 0) or 0
            swap_percent = swap_used / swap_total * 100
            result.append(
                f"  - Swap: {ProxmoxFormatters.format_bytes(swap_used)} / "
                f"{ProxmoxFormatters.format_bytes(swap_total)} ({swap_percent:.1f}%)"
            )

        # This endpoint names the root filesystem "rootfs"; "disk" is the node-list
        # field and is absent here, so the disk line never rendered. Accept either.
        disk = status.get("rootfs") or status.get("disk") or {}
        if disk:
            disk_used = disk.get("used", 0)
            disk_total = disk.get("total", 0)
            disk_percent = (disk_used / disk_total * 100) if disk_total > 0 else 0
            result.append(
                f"  - Disk: {ProxmoxFormatters.format_bytes(disk_used)} / "
                f"{ProxmoxFormatters.format_bytes(disk_total)} ({disk_percent:.1f}%)"
            )
        
        return "\n".join(result)
    
    @staticmethod
    def vm_list(vms: List[Dict[str, Any]]) -> str:
        """Template for VM list output.
        
        Args:
            vms: List of VM data dictionaries
            
        Returns:
            Formatted VM list string
        """
        result = [f"{ProxmoxTheme.RESOURCES['vm']} Virtual Machines"]
        
        for vm in vms:
            memory = vm.get("memory", {})
            memory_used = memory.get("used", 0)
            memory_total = memory.get("total", 0)
            memory_percent = (memory_used / memory_total * 100) if memory_total > 0 else 0
            
            result.extend([
                "",  # Empty line between VMs
                f"{ProxmoxTheme.RESOURCES['vm']} {vm['name']} (ID: {vm['vmid']})",
                f"  - Status: {vm['status'].upper()}",
                f"  - Node: {vm['node']}",
                f"  - CPU Cores: {vm.get('cpus', 'N/A')}",
                f"  - Memory: {ProxmoxFormatters.format_bytes(memory_used)} / "
                f"{ProxmoxFormatters.format_bytes(memory_total)} ({memory_percent:.1f}%)"
            ])
            
        return "\n".join(result)
    
    @staticmethod
    def storage_list(storage: List[Dict[str, Any]]) -> str:
        """Template for storage list output.
        
        Args:
            storage: List of storage data dictionaries
            
        Returns:
            Formatted storage list string
        """
        result = [f"{ProxmoxTheme.RESOURCES['storage']} Storage Pools"]
        
        for store in storage:
            used = store.get("used", 0)
            total = store.get("total", 0)
            percent = (used / total * 100) if total > 0 else 0
            
            result.extend([
                "",  # Empty line between storage pools
                f"{ProxmoxTheme.RESOURCES['storage']} {store['storage']}",
                f"  - Status: {store.get('status', 'unknown').upper()}",
                f"  - Type: {store['type']}",
                f"  - Usage: {ProxmoxFormatters.format_bytes(used)} / "
                f"{ProxmoxFormatters.format_bytes(total)} ({percent:.1f}%)"
            ])
            
        return "\n".join(result)
    
    @staticmethod
    def container_list(containers: List[Dict[str, Any]]) -> str:
        """Template for container list output.
        
        Args:
            containers: List of container data dictionaries
            
        Returns:
            Formatted container list string
        """
        if not containers:
            return f"{ProxmoxTheme.RESOURCES['container']} No containers found"
            
        result = [f"{ProxmoxTheme.RESOURCES['container']} Containers"]
        
        for container in containers:
            memory = container.get("memory", {})
            memory_used = memory.get("used", 0)
            memory_total = memory.get("total", 0)
            memory_percent = (memory_used / memory_total * 100) if memory_total > 0 else 0
            
            result.extend([
                "",  # Empty line between containers
                f"{ProxmoxTheme.RESOURCES['container']} {container['name']} (ID: {container['vmid']})",
                f"  - Status: {container['status'].upper()}",
                f"  - Node: {container['node']}",
                f"  - CPU Cores: {container.get('cpus', 'N/A')}",
                f"  - Memory: {ProxmoxFormatters.format_bytes(memory_used)} / "
                f"{ProxmoxFormatters.format_bytes(memory_total)} ({memory_percent:.1f}%)"
            ])
            
        return "\n".join(result)

    @staticmethod
    def cluster_status(status: Dict[str, Any]) -> str:
        """Template for cluster status output.
        
        Args:
            status: Cluster status data
            
        Returns:
            Formatted cluster status string
        """
        result = [f"{ProxmoxTheme.SECTIONS['configuration']} Proxmox Cluster"]

        if status.get("clustered") is False:
            name = "n/a (not clustered)"
            quorum = "n/a (not clustered)"
        else:
            name = status.get("name") or "unknown"
            quorate = status.get("quorum")
            quorum = "unknown" if quorate is None else ("OK" if quorate else "NOT OK")
        
        # Basic cluster info
        result.extend([
            "",
            f"  - Name: {name}",
            f"  - Quorum: {quorum}",
            f"  - Nodes: {status.get('nodes', 0)}",
        ])
        
        # Add resource count if available
        resources = status.get('resources', [])
        if resources:
            result.append(f"  - Resources: {len(resources)}")
        
        return "\n".join(result)
