"""
VM-related tools for Proxmox MCP.

This module provides tools for managing and interacting with Proxmox VMs:
- Listing all VMs across the cluster with their status
- Retrieving detailed VM information including:
  * Resource allocation (CPU, memory)
  * Runtime status
  * Node placement
- Executing commands within VMs via QEMU guest agent
- Handling VM console operations
- VM power management (start, stop, shutdown, reset)
- VM creation with customizable specifications

The tools implement fallback mechanisms for scenarios where
detailed VM information might be temporarily unavailable.
"""
import json
from typing import Any, Dict, List, Optional
from mcp.types import TextContent as Content
from proxmox_mcp.models import ToolResult
from proxmox_mcp.tools.base import ProxmoxTool
from proxmox_mcp.tools.console.manager import VMConsoleManager


def _as_dict(maybe: Any) -> Dict:
    """Return dict; unwrap {'data': dict}; else {}."""
    if isinstance(maybe, dict):
        data = maybe.get("data")
        if isinstance(data, dict):
            return data
        return maybe
    return {}

class VMTools(ProxmoxTool):
    """Tools for managing Proxmox VMs.
    
    Provides functionality for:
    - Retrieving cluster-wide VM information
    - Getting detailed VM status and configuration
    - Executing commands within VMs
    - Managing VM console operations
    - VM power management (start, stop, shutdown, reset)
    - VM creation with customizable specifications
    
    Implements fallback mechanisms for scenarios where detailed
    VM information might be temporarily unavailable. Integrates
    with QEMU guest agent for VM command execution.
    """

    def __init__(
        self,
        proxmox_api: Any,
        command_policy: Optional[Any] = None,
        metrics: Optional[Any] = None,
        job_store: Optional[Any] = None,
    ):
        """Initialize VM tools.

        Args:
            proxmox_api: Initialized ProxmoxAPI instance
        """
        super().__init__(proxmox_api, metrics=metrics, job_store=job_store)
        self.console_manager = VMConsoleManager(proxmox_api)
        self.command_policy = command_policy

    # ---------- error / output ----------
    def _json_fmt(self, data: Any) -> List[Content]:
        """Return raw JSON string (never touch project formatters)."""
        return [Content(type="text", text=json.dumps(data, indent=2, sort_keys=True))]

    def _err(self, action: str, e: Exception) -> List[Content]:
        self._handle_error(action, e)

    def _get_cluster_vm_inventory(self) -> Optional[list[dict[str, Any]]]:
        try:
            resources = self.proxmox.cluster.resources.get(type="vm")
        except Exception as error:
            self.logger.debug("Cluster VM inventory unavailable, falling back to node scan: %s", error)
            return None
        if not isinstance(resources, list):
            return None

        result: list[dict[str, Any]] = []
        for vm in resources:
            if not isinstance(vm, dict) or vm.get("type") != "qemu":
                continue
            vmid = vm.get("vmid")
            if vmid is None:
                resource_id = str(vm.get("id", ""))
                if "/" in resource_id:
                    vmid = resource_id.rsplit("/", 1)[-1]
            if vmid is None:
                continue
            result.append({
                "vmid": vmid,
                "name": vm.get("name") or f"VM-{vmid}",
                "status": vm.get("status", "unknown"),
                "node": vm.get("node", "unknown"),
                "cpus": vm.get("maxcpu", vm.get("cpus", "N/A")),
                "memory": {
                    "used": vm.get("mem", 0),
                    "total": vm.get("maxmem", 0),
                },
            })
        return result if result else None

    def get_vm_config(self, node: str, vmid: str) -> List[Content]:
        """Return the full configuration of a QEMU virtual machine.

        Parameters:
            node: Proxmox node name.
            vmid: VM ID as a string.
        """
        try:
            config = _as_dict(self.proxmox.nodes(node).qemu(vmid).config.get())
            config.setdefault("vmid", vmid)
            return self._json_fmt(config)
        except Exception as e:
            return self._err("get_vm_config", e)

    def get_vms(self) -> List[Content]:
        """List all virtual machines across the cluster with detailed status.

        Retrieves comprehensive information for each VM including:
        - Basic identification (ID, name)
        - Runtime status (running, stopped)
        - Resource allocation and usage:
          * CPU cores
          * Memory allocation and usage
        - Node placement
        
        Implements a fallback mechanism that returns basic information
        if detailed configuration retrieval fails for any VM.

        Returns:
            List of Content objects containing formatted VM information:
            {
                "vmid": "100",
                "name": "vm-name",
                "status": "running/stopped",
                "node": "node-name",
                "cpus": core_count,
                "memory": {
                    "used": bytes,
                    "total": bytes
                }
            }

        Raises:
            RuntimeError: If the cluster-wide VM query fails
        """
        cluster_inventory = self._get_cluster_vm_inventory()
        if cluster_inventory is not None:
            return self._format_response(cluster_inventory, "vms")

        try:
            nodes = self.proxmox.nodes.get()
        except Exception as e:
            self._handle_error("get VMs", e)

        result = []
        try:
            for node in nodes:
                node_name = node.get("node") if isinstance(node, dict) else None
                if not node_name:
                    self.logger.warning(
                        "Skipping unexpected node entry while gathering VM list: %s",
                        node,
                    )
                    continue
                try:
                    vms = self.proxmox.nodes(node_name).qemu.get()
                except Exception as node_error:
                    self.logger.warning(
                        "Skipping node %s while gathering VM list: %s", node_name, node_error
                    )
                    continue

                for vm in vms:
                    vmid = vm["vmid"]
                    # Get VM config for CPU cores
                    try:
                        config = self.proxmox.nodes(node_name).qemu(vmid).config.get()
                        result.append({
                            "vmid": vmid,
                            "name": vm["name"],
                            "status": vm["status"],
                            "node": node_name,
                            "cpus": config.get("cores", "N/A"),
                            "memory": {
                                "used": vm.get("mem", 0),
                                "total": vm.get("maxmem", 0)
                            }
                        })
                    except Exception:
                        # Fallback if can't get config
                        result.append({
                            "vmid": vmid,
                            "name": vm["name"],
                            "status": vm["status"],
                            "node": node_name,
                            "cpus": "N/A",
                            "memory": {
                                "used": vm.get("mem", 0),
                                "total": vm.get("maxmem", 0)
                            }
                        })
        except Exception as e:
            self._handle_error("get VMs", e)

        return self._format_response(result, "vms")

    def get_vm_info(self, node: str, vmid: str) -> List[Content]:
        """Return comprehensive VM info including CPU, RAM, disks, network, and IP addresses.

        Combines data from VM config, status, and QEMU guest agent.
        """
        try:
            config = _as_dict(self.proxmox.nodes(node).qemu(vmid).config.get())
            status = _as_dict(self.proxmox.nodes(node).qemu(vmid).status.current.get())

            vm_name = config.get("name") or status.get("name") or f"VM-{vmid}"
            vm_status = status.get("status", "unknown")

            # --- CPU ---
            cpu_info: Dict[str, Any] = {
                "cores": config.get("cores", "N/A"),
                "sockets": config.get("sockets", 1),
                "type": config.get("cpu", "default"),
            }
            cpu_frac = status.get("cpu")
            if cpu_frac is not None:
                try:
                    cpu_info["cpu_pct"] = round(float(cpu_frac) * 100.0, 2)
                except Exception:
                    pass

            # --- Memory ---
            memory_mib = config.get("memory")
            memory_info: Dict[str, Any] = {
                "total_mib": memory_mib if memory_mib is not None else "N/A",
            }
            mem_used = status.get("mem")
            max_mem = status.get("maxmem")
            if mem_used is not None:
                try:
                    memory_info["used_bytes"] = int(mem_used)
                except Exception:
                    pass
            if max_mem is not None:
                try:
                    memory_info["total_bytes"] = int(max_mem)
                except Exception:
                    pass
            if memory_info.get("used_bytes") and memory_info.get("total_bytes"):
                try:
                    memory_info["used_pct"] = round(
                        memory_info["used_bytes"] / memory_info["total_bytes"] * 100.0, 2
                    )
                except Exception:
                    pass

            # --- Disks ---
            disk_prefixes = ("scsi", "virtio", "ide", "sata")
            disks: List[Dict[str, Any]] = []
            for key, value in config.items():
                if not isinstance(value, str):
                    continue
                if not key.startswith(disk_prefixes):
                    continue
                bus = key.rstrip("0123456789")
                index = key[len(bus):]
                if not index.isdigit():
                    continue
                parts = value.split(",")
                disk_path = parts[0]
                disk_entry: Dict[str, Any] = {
                    "bus": key,
                    "type": "cdrom" if key.startswith("ide") else "disk",
                }
                if ":" in disk_path:
                    storage, vol = disk_path.split(":", 1)
                    disk_entry["storage"] = storage
                    disk_entry["volume"] = vol
                for p in parts[1:]:
                    if p.startswith("size="):
                        disk_entry["size"] = p.split("=", 1)[1]
                    elif p.startswith("format="):
                        disk_entry["format"] = p.split("=", 1)[1]
                    elif p == "media=cdrom":
                        disk_entry["type"] = "cdrom"
                if key.startswith("ide") and ("media=cdrom" not in value or "cloudinit" in value):
                    disk_entry["type"] = "cloudinit" if "cloudinit" in value else "cdrom"
                disks.append(disk_entry)

            # --- Network (config) ---
            net_interfaces: List[Dict[str, Any]] = []
            for key, value in config.items():
                if not key.startswith("net") or not isinstance(value, str):
                    continue
                index = key[3:]
                if not index.isdigit():
                    continue
                iface: Dict[str, Any] = {"id": key}
                parts = [p.strip() for p in value.split(",")]
                for p in parts:
                    if "=" in p:
                        k, v = p.split("=", 1)
                        if k == "bridge":
                            iface["bridge"] = v
                        elif k == "mac":
                            iface["mac_address"] = v
                        elif k == "tag":
                            iface["vlan_tag"] = int(v)
                        elif k == "rate":
                            iface["rate_limit"] = v
                        elif k == "firewall":
                            iface["firewall"] = v
                    elif p in ("virtio", "e1000", "rtl8139", "vmxnet3"):
                        iface["model"] = p
                net_interfaces.append(iface)

            # --- Network (QEMU agent IP) ---
            agent_info: Optional[List[Dict[str, Any]]] = None
            if vm_status == "running":
                try:
                    raw_agent = self.proxmox.nodes(node).qemu(vmid).agent("network-get-interfaces").get()
                    agent_data = raw_agent
                    if isinstance(agent_data, dict):
                        agent_data = agent_data.get("result") or agent_data.get("data") or agent_data
                    if isinstance(agent_data, list):
                        agent_info = []
                        for iface in agent_data:
                            if not isinstance(iface, dict):
                                continue
                            name = iface.get("name", "unknown")
                            if name == "lo":
                                continue
                            entry: Dict[str, Any] = {
                                "name": name,
                                "mac_address": iface.get("hardware-address", ""),
                            }
                            ip_list: List[Dict[str, Any]] = []
                            for ip in iface.get("ip-addresses", []):
                                if not isinstance(ip, dict):
                                    continue
                                ip_entry: Dict[str, Any] = {
                                    "version": 4 if "ipv4" in str(ip.get("ip-address-type", "")).lower() else 6,
                                    "address": ip.get("ip-address", ""),
                                }
                                prefix = ip.get("prefix")
                                if prefix is not None:
                                    try:
                                        ip_entry["prefix"] = int(prefix)
                                    except Exception:
                                        pass
                                ip_list.append(ip_entry)
                            if ip_list:
                                entry["ip_addresses"] = ip_list
                            agent_info.append(entry)
                        if not agent_info:
                            agent_info = None
                except Exception as e:
                    self.logger.debug(
                        "QEMU guest agent not available for VM %s on %s: %s", vmid, node, e
                    )
            else:
                self.logger.debug("Skipping agent network query for stopped VM %s", vmid)

            result = {
                "vmid": vmid,
                "name": vm_name,
                "node": node,
                "status": vm_status,
                "cpu": cpu_info,
                "memory": memory_info,
                "disks": disks,
                "network": {
                    "interfaces": net_interfaces,
                    "ip_info": agent_info,
                },
            }
            return self._json_fmt(result)

        except Exception as e:
            return self._err("get_vm_info", e)

    def create_vm(
        self,
        node: str,
        vmid: str,
        name: str,
        cpus: int,
        memory: int,
        disk_size: int,
        storage: Optional[str] = None,
        ostype: Optional[str] = None,
        network_bridge: Optional[str] = None,
    ) -> List[Content]:
        """Create a new virtual machine with specified configuration.
        
        Args:
            node: Host node name (e.g., 'pve')
            vmid: New VM ID number (e.g., '200')
            name: VM name (e.g., 'my-new-vm')
            cpus: Number of CPU cores (e.g., 1, 2, 4)
            memory: Memory size in MB (e.g., 2048 for 2GB)
            disk_size: Disk size in GB (e.g., 10, 20, 50)
            storage: Storage name (e.g., 'local-lvm', 'vm-storage'). If None, will auto-detect
            ostype: OS type (e.g., 'l26' for Linux, 'win10' for Windows). Default: 'l26'
            network_bridge: Network bridge name (e.g., 'vmbr0'). If None, defaults to 'vmbr0'
            
        Returns:
            List of Content objects containing creation result
            
        Raises:
            ValueError: If VM ID already exists or invalid parameters
            RuntimeError: If VM creation fails
        """
        try:
            # Check if VM ID already exists
            try:
                self.proxmox.nodes(node).qemu(vmid).config.get()
                raise ValueError(f"VM {vmid} already exists on node {node}")
            except Exception as e:
                if "does not exist" not in str(e).lower():
                    raise e
            
            # Get storage information
            storage_list = self.proxmox.nodes(node).storage.get()
            storage_info = {}
            for s in storage_list:
                storage_info[s["storage"]] = s
            
            # Auto-detect storage if not specified
            if storage is None:
                # Prefer local-lvm for VM images first
                for s in storage_list:
                    if s["storage"] == "local-lvm" and "images" in s.get("content", ""):
                        storage = s["storage"]
                        break
                if storage is None:
                    # Then try vm-storage 
                    for s in storage_list:
                        if s["storage"] == "vm-storage" and "images" in s.get("content", ""):
                            storage = s["storage"]
                            break
                if storage is None:
                    # Fallback to any storage that supports images
                    for s in storage_list:
                        if "images" in s.get("content", ""):
                            storage = s["storage"]
                            break
                    if storage is None:
                        raise ValueError("No suitable storage found for VM images")
            
            # Validate storage exists and supports images
            if storage not in storage_info:
                raise ValueError(f"Storage '{storage}' not found on node {node}")
            
            if "images" not in storage_info[storage].get("content", ""):
                raise ValueError(f"Storage '{storage}' does not support VM images")
            
            # Determine appropriate disk format based on storage type
            storage_type = storage_info[storage]["type"]
            
            if storage_type in ["lvm", "lvmthin"]:
                # LVM storages use raw format and no cloudinit
                disk_format = "raw"
                vm_config_storage = {
                    "scsi0": f"{storage}:{disk_size},format={disk_format}",
                }
            elif storage_type in ["dir", "nfs", "cifs"]:
                # File-based storages can use qcow2
                disk_format = "qcow2"
                vm_config_storage = {
                    "scsi0": f"{storage}:{disk_size},format={disk_format}",
                    "ide2": f"{storage}:cloudinit",
                }
            else:
                # Default to raw for unknown storage types
                disk_format = "raw"
                vm_config_storage = {
                    "scsi0": f"{storage}:{disk_size},format={disk_format}",
                }
            
            # Set default OS type
            if ostype is None:
                ostype = "l26"  # Linux 2.6+ kernel

            if not network_bridge:
                network_bridge = "vmbr0"
            
            # Prepare VM configuration
            vm_config = {
                "vmid": vmid,
                "name": name,
                "cores": cpus,
                "memory": memory,
                "ostype": ostype,
                "scsihw": "virtio-scsi-pci",
                "boot": "order=scsi0",
                "agent": "1",  # Enable QEMU guest agent
                "vga": "std",
                "net0": f"virtio,bridge={network_bridge}",
            }
            
            # Add storage configuration
            vm_config.update(vm_config_storage)
            
            # Create the VM
            task_result = self.proxmox.nodes(node).qemu.create(**vm_config)
            job = self._register_background_job(
                tool_name="create_vm",
                summary=f"Create VM {vmid} ({name}) on {node}",
                node=node,
                upid=task_result,
                metadata={"vmid": vmid, "name": name},
                retry_spec={"kind": "vm.create", "params": {"node": node, "vm_config": vm_config}},
                retry_factory=lambda: self.proxmox.nodes(node).qemu.create(**vm_config),
                cancel_factory=lambda upid: self.proxmox.nodes(node).tasks(upid).status.stop.post(),
            )
            
            cloudinit_note = ""
            if storage_type in ["lvm", "lvmthin"]:
                cloudinit_note = "\n  - Note: LVM storage does not support cloud-init images"
            
            result_text = f"""VM {vmid} created successfully

VM Configuration:
  - Name: {name}
  - Node: {node}
  - VM ID: {vmid}
  - CPU Cores: {cpus}
  - Memory: {memory} MB ({memory/1024:.1f} GB)
  - Disk: {disk_size} GB ({storage}, {disk_format} format)
  - Storage Type: {storage_type}
  - OS Type: {ostype}
  - Network: virtio (bridge={network_bridge})
  - QEMU Agent: Enabled{cloudinit_note}

Task ID: {task_result}
Job ID: {job["job_id"] if job else "n/a"}

Next steps:
  1. Upload an ISO to install the operating system
  2. Start the VM using start_vm tool
  3. Access the console to complete OS installation"""
            
            return [Content(type="text", text=result_text)]
            
        except ValueError as e:
            raise e
        except Exception as e:
            self._handle_error(f"create VM {vmid}", e)

    def clone_vm(
        self,
        node: str,
        source_vmid: str,
        target_vmid: str,
        name: Optional[str] = None,
        target_node: Optional[str] = None,
        full: bool = True,
        storage: Optional[str] = None,
        pool: Optional[str] = None,
        snapname: Optional[str] = None,
    ) -> List[Content]:
        """Clone an existing virtual machine."""
        destination_node = target_node or node

        try:
            source_status = self.proxmox.nodes(node).qemu(source_vmid).status.current.get()
        except Exception as e:
            if "does not exist" in str(e).lower() or "not found" in str(e).lower():
                raise ValueError(f"Source VM {source_vmid} not found on node {node}")
            self._handle_error(f"lookup source VM {source_vmid}", e)

        source_name = source_status.get("name", f"VM-{source_vmid}")

        try:
            self.proxmox.nodes(destination_node).qemu(target_vmid).config.get()
            raise ValueError(f"Target VM ID {target_vmid} already exists on node {destination_node}")
        except ValueError:
            raise
        except Exception as e:
            if "does not exist" not in str(e).lower() and "not found" not in str(e).lower():
                self._handle_error(f"check target VM {target_vmid}", e)

        clone_payload: dict[str, Any] = {
            "newid": int(target_vmid),
            "full": 1 if full else 0,
        }
        if name:
            clone_payload["name"] = name
        if target_node:
            clone_payload["target"] = target_node
        if storage:
            clone_payload["storage"] = storage
        if pool:
            clone_payload["pool"] = pool
        if snapname:
            clone_payload["snapname"] = snapname

        try:
            task_result = self.proxmox.nodes(node).qemu(source_vmid).clone.post(**clone_payload)
        except Exception as e:
            self._handle_error(f"clone VM {source_vmid} -> {target_vmid}", e)

        job = self._register_background_job(
            tool_name="clone_vm",
            summary=f"Clone VM {source_vmid} to {target_vmid} on {node}",
            node=node,
            upid=task_result,
            metadata={
                "source_vmid": source_vmid,
                "target_vmid": target_vmid,
                "source_node": node,
                "target_node": destination_node,
                "full": full,
                "name": name,
            },
            retry_spec={"kind": "vm.clone", "params": {"node": node, "source_vmid": source_vmid, "clone_payload": clone_payload}},
            retry_factory=lambda: self.proxmox.nodes(node).qemu(source_vmid).clone.post(**clone_payload),
            cancel_factory=lambda upid: self.proxmox.nodes(node).tasks(upid).status.stop.post(),
        )

        result_text = f"""VM clone initiated successfully

Clone Configuration:
  - Source VM: {source_vmid} ({source_name})
  - Source Node: {node}
  - Target VM ID: {target_vmid}
  - Target Node: {destination_node}
  - Clone Type: {"full" if full else "linked"}"""

        if name:
            result_text += f"\n  - Target Name: {name}"
        if storage:
            result_text += f"\n  - Storage: {storage}"
        if pool:
            result_text += f"\n  - Pool: {pool}"
        if snapname:
            result_text += f"\n  - Snapshot: {snapname}"

        result_text += f"\n\nTask ID: {task_result}\nJob ID: {job['job_id'] if job else 'n/a'}"

        return [Content(type="text", text=result_text)]

    def start_vm(self, node: str, vmid: str) -> List[Content]:
        """Start a virtual machine.
        
        Args:
            node: Host node name (e.g., 'pve1', 'proxmox-node2')
            vmid: VM ID number (e.g., '100', '101')
            
        Returns:
            List of Content objects containing operation result
            
        Raises:
            ValueError: If VM is not found
            RuntimeError: If start operation fails
        """
        try:
            # Check if VM exists and get current status
            vm_status = self.proxmox.nodes(node).qemu(vmid).status.current.get()
            current_status = vm_status.get("status")
            
            if current_status == "running":
                result_text = f"VM {vmid} is already running"
            else:
                # Start the VM
                task_result = self.proxmox.nodes(node).qemu(vmid).status.start.post()
                job = self._register_background_job(
                    tool_name="start_vm",
                    summary=f"Start VM {vmid} on {node}",
                    node=node,
                    upid=task_result,
                    metadata={"vmid": vmid},
                    retry_spec={"kind": "vm.start", "params": {"node": node, "vmid": vmid}},
                    retry_factory=lambda: self.proxmox.nodes(node).qemu(vmid).status.start.post(),
                    cancel_factory=lambda upid: self.proxmox.nodes(node).tasks(upid).status.stop.post(),
                )
                result_text = (
                    f"VM {vmid} start initiated successfully\n"
                    f"Task ID: {task_result}\n"
                    f"Job ID: {job['job_id'] if job else 'n/a'}"
                )
                
            return [Content(type="text", text=result_text)]
            
        except Exception as e:
            if "does not exist" in str(e).lower() or "not found" in str(e).lower():
                raise ValueError(f"VM {vmid} not found on node {node}")
            self._handle_error(f"start VM {vmid}", e)

    def stop_vm(self, node: str, vmid: str) -> List[Content]:
        """Stop a virtual machine (force stop).
        
        Args:
            node: Host node name (e.g., 'pve1', 'proxmox-node2') 
            vmid: VM ID number (e.g., '100', '101')
            
        Returns:
            List of Content objects containing operation result
            
        Raises:
            ValueError: If VM is not found
            RuntimeError: If stop operation fails
        """
        try:
            # Check if VM exists and get current status
            vm_status = self.proxmox.nodes(node).qemu(vmid).status.current.get()
            current_status = vm_status.get("status")
            
            if current_status == "stopped":
                result_text = f"VM {vmid} is already stopped"
            else:
                # Stop the VM
                task_result = self.proxmox.nodes(node).qemu(vmid).status.stop.post()
                job = self._register_background_job(
                    tool_name="stop_vm",
                    summary=f"Stop VM {vmid} on {node}",
                    node=node,
                    upid=task_result,
                    metadata={"vmid": vmid},
                    retry_spec={"kind": "vm.stop", "params": {"node": node, "vmid": vmid}},
                    retry_factory=lambda: self.proxmox.nodes(node).qemu(vmid).status.stop.post(),
                    cancel_factory=lambda upid: self.proxmox.nodes(node).tasks(upid).status.stop.post(),
                )
                result_text = (
                    f"VM {vmid} stop initiated successfully\n"
                    f"Task ID: {task_result}\n"
                    f"Job ID: {job['job_id'] if job else 'n/a'}"
                )
                
            return [Content(type="text", text=result_text)]
            
        except Exception as e:
            if "does not exist" in str(e).lower() or "not found" in str(e).lower():
                raise ValueError(f"VM {vmid} not found on node {node}")
            self._handle_error(f"stop VM {vmid}", e)

    def shutdown_vm(self, node: str, vmid: str) -> List[Content]:
        """Shutdown a virtual machine gracefully.
        
        Args:
            node: Host node name (e.g., 'pve1', 'proxmox-node2')
            vmid: VM ID number (e.g., '100', '101')
            
        Returns:
            List of Content objects containing operation result
            
        Raises:
            ValueError: If VM is not found
            RuntimeError: If shutdown operation fails
        """
        try:
            # Check if VM exists and get current status
            vm_status = self.proxmox.nodes(node).qemu(vmid).status.current.get()
            current_status = vm_status.get("status")
            
            if current_status == "stopped":
                result_text = f"VM {vmid} is already stopped"
            else:
                # Shutdown the VM gracefully
                task_result = self.proxmox.nodes(node).qemu(vmid).status.shutdown.post()
                job = self._register_background_job(
                    tool_name="shutdown_vm",
                    summary=f"Shutdown VM {vmid} on {node}",
                    node=node,
                    upid=task_result,
                    metadata={"vmid": vmid},
                    retry_spec={"kind": "vm.shutdown", "params": {"node": node, "vmid": vmid}},
                    retry_factory=lambda: self.proxmox.nodes(node).qemu(vmid).status.shutdown.post(),
                    cancel_factory=lambda upid: self.proxmox.nodes(node).tasks(upid).status.stop.post(),
                )
                result_text = (
                    f"VM {vmid} graceful shutdown initiated\n"
                    f"Task ID: {task_result}\n"
                    f"Job ID: {job['job_id'] if job else 'n/a'}"
                )
                
            return [Content(type="text", text=result_text)]
            
        except Exception as e:
            if "does not exist" in str(e).lower() or "not found" in str(e).lower():
                raise ValueError(f"VM {vmid} not found on node {node}")
            self._handle_error(f"shutdown VM {vmid}", e)

    def reset_vm(self, node: str, vmid: str) -> List[Content]:
        """Reset (restart) a virtual machine.
        
        Args:
            node: Host node name (e.g., 'pve1', 'proxmox-node2')
            vmid: VM ID number (e.g., '100', '101')
            
        Returns:
            List of Content objects containing operation result
            
        Raises:
            ValueError: If VM is not found
            RuntimeError: If reset operation fails
        """
        try:
            # Check if VM exists and get current status
            vm_status = self.proxmox.nodes(node).qemu(vmid).status.current.get()
            current_status = vm_status.get("status")
            
            if current_status == "stopped":
                result_text = f"Cannot reset VM {vmid}: VM is currently stopped\nUse start_vm to start it first"
            else:
                # Reset the VM
                task_result = self.proxmox.nodes(node).qemu(vmid).status.reset.post()
                job = self._register_background_job(
                    tool_name="reset_vm",
                    summary=f"Reset VM {vmid} on {node}",
                    node=node,
                    upid=task_result,
                    metadata={"vmid": vmid},
                    retry_spec={"kind": "vm.reset", "params": {"node": node, "vmid": vmid}},
                    retry_factory=lambda: self.proxmox.nodes(node).qemu(vmid).status.reset.post(),
                    cancel_factory=lambda upid: self.proxmox.nodes(node).tasks(upid).status.stop.post(),
                )
                result_text = (
                    f"VM {vmid} reset initiated successfully\n"
                    f"Task ID: {task_result}\n"
                    f"Job ID: {job['job_id'] if job else 'n/a'}"
                )
                
            return [Content(type="text", text=result_text)]
            
        except Exception as e:
            if "does not exist" in str(e).lower() or "not found" in str(e).lower():
                raise ValueError(f"VM {vmid} not found on node {node}")
            self._handle_error(f"reset VM {vmid}", e)

    async def execute_command(
        self,
        node: str,
        vmid: str,
        command: str,
        approval_token: Optional[str] = None,
    ) -> List[Content]:
        """Execute a command in a VM via QEMU guest agent.

        Uses the QEMU guest agent to execute commands within a running VM.
        Requires:
        - VM must be running
        - QEMU guest agent must be installed and running in the VM
        - Command execution permissions must be enabled

        Args:
            node: Host node name (e.g., 'pve1', 'proxmox-node2')
            vmid: VM ID number (e.g., '100', '101')
            command: Shell command to run (e.g., 'uname -a', 'systemctl status nginx')

        Returns:
            List of Content objects containing formatted command output:
            {
                "success": true/false,
                "output": "command output",
                "error": "error message if any"
            }

        Raises:
            ValueError: If VM is not found, not running, or guest agent is not available
            RuntimeError: If command execution fails due to permissions or other issues
        """
        try:
            if self.command_policy is not None:
                decision = self.command_policy.evaluate(command, approval_token=approval_token)
                if not decision.allowed:
                    policy_result = ToolResult(
                        success=False,
                        code=decision.code,
                        message="Command execution blocked by policy",
                        data={"reason": decision.message},
                    )
                    return [
                        Content(
                            type="text",
                            text=policy_result.model_dump_json(indent=2),
                        )
                    ]

            exec_result = await self.console_manager.execute_command(node, vmid, command)
            # Use the command output formatter from ProxmoxFormatters
            from proxmox_mcp.formatting import ProxmoxFormatters
            formatted = ProxmoxFormatters.format_command_output(
                success=exec_result["success"],
                command=command,
                output=exec_result["output"],
                error=exec_result.get("error")
            )
            return [Content(type="text", text=formatted)]
        except Exception as e:
            self._handle_error(f"execute command on VM {vmid}", e)

    def delete_vm(
        self,
        node: str,
        vmid: str,
        force: bool = False,
        approval_token: Optional[str] = None,
    ) -> List[Content]:
        """Delete/remove a virtual machine completely.
        
        This will permanently delete the VM and all its associated data including:
        - VM configuration
        - Virtual disks
        - Snapshots
        
        WARNING: This operation cannot be undone!
        
        Args:
            node: Host node name (e.g., 'pve1', 'proxmox-node2')
            vmid: VM ID number (e.g., '100', '101')
            force: Force deletion even if VM is running (will stop first)
            
        Returns:
            List of Content objects containing deletion result
            
        Raises:
            ValueError: If VM is not found or is running and force=False
            RuntimeError: If deletion fails
        """
        _ = approval_token
        try:
            # Check if VM exists and get current status
            try:
                vm_status = self.proxmox.nodes(node).qemu(vmid).status.current.get()
                current_status = vm_status.get("status")
                vm_name = vm_status.get("name", f"VM-{vmid}")
            except Exception as e:
                if "does not exist" in str(e).lower() or "not found" in str(e).lower():
                    raise ValueError(f"VM {vmid} not found on node {node}")
                raise e
            
            # Check if VM is running
            if current_status == "running":
                if not force:
                    raise ValueError(f"VM {vmid} ({vm_name}) is currently running. "
                                   f"Please stop it first or use force=True to stop and delete.")
                else:
                    # Force stop the VM first
                    self.proxmox.nodes(node).qemu(vmid).status.stop.post()
                    result_text = f"Stopping VM {vmid} ({vm_name}) before deletion...\n"
            else:
                result_text = f"Deleting VM {vmid} ({vm_name})...\n"
            
            # Delete the VM
            task_result = self.proxmox.nodes(node).qemu(vmid).delete()
            job = self._register_background_job(
                tool_name="delete_vm",
                summary=f"Delete VM {vmid} ({vm_name}) on {node}",
                node=node,
                upid=task_result,
                metadata={"vmid": vmid, "force": force},
                retry_spec={"kind": "vm.delete", "params": {"node": node, "vmid": vmid}},
                retry_factory=lambda: self.proxmox.nodes(node).qemu(vmid).delete(),
                cancel_factory=lambda upid: self.proxmox.nodes(node).tasks(upid).status.stop.post(),
            )
            
            result_text += f"""VM {vmid} ({vm_name}) deletion initiated successfully

WARNING: This operation will permanently remove:
  - VM configuration
  - All virtual disks
  - All snapshots
  - Cannot be undone

Task ID: {task_result}
Job ID: {job["job_id"] if job else "n/a"}

VM {vmid} ({vm_name}) is being deleted from node {node}"""
            
            return [Content(type="text", text=result_text)]
            
        except ValueError as e:
            raise e
        except Exception as e:
            self._handle_error(f"delete VM {vmid}", e)

    def update_vm(
        self,
        node: str,
        vmid: str,
        cores: Optional[int] = None,
        sockets: Optional[int] = None,
        cpu_type: Optional[str] = None,
        vcpus: Optional[int] = None,
        memory: Optional[int] = None,
        balloon: Optional[int] = None,
        disks: Optional[Dict[str, str]] = None,
        disk_resize: Optional[Dict[str, str]] = None,
        disk_delete: Optional[List[str]] = None,
        net0: Optional[str] = None,
        net1: Optional[str] = None,
        net2: Optional[str] = None,
        net3: Optional[str] = None,
        onboot: Optional[bool] = None,
        agent: Optional[bool] = None,
        boot: Optional[str] = None,
        bios: Optional[str] = None,
        ostype: Optional[str] = None,
        tags: Optional[str] = None,
        description: Optional[str] = None,
        startup: Optional[str] = None,
        scsihw: Optional[str] = None,
        vga: Optional[str] = None,
        tablet: Optional[bool] = None,
        kvm: Optional[bool] = None,
        machine: Optional[str] = None,
        nameserver: Optional[str] = None,
        searchdomain: Optional[str] = None,
        extra_config: Optional[Dict[str, str]] = None,
    ) -> List[Content]:
        """Update configuration of a virtual machine.

        VM must be stopped before modifying configuration.

        Args:
            node: Proxmox node name
            vmid: VM ID number
            cores: Number of CPU cores
            sockets: Number of CPU sockets
            cpu_type: CPU emulation type
            vcpus: Number of hotplugged vCPUs
            memory: Memory size in MB
            balloon: Balloon minimum memory in MB
            disks: Dict of disk configs to add/update
            disk_resize: Dict of disks to resize
            disk_delete: List of disk IDs to remove
            net0-net3: Network interface configs
            onboot: Start VM at boot
            agent: QEMU guest agent
            boot: Boot order
            bios: BIOS type
            ostype: OS type
            tags: VM tags
            description: Description text
            startup: Startup order
            scsihw: SCSI controller
            vga: VGA type
            tablet: USB tablet
            kvm: KVM hardware virtualization
            machine: Machine type
            nameserver: DNS nameserver
            searchdomain: DNS search domain
            extra_config: Additional Proxmox config keys

        Returns:
            List of Content objects with update result

        Raises:
            ValueError: If VM is running or not found
            RuntimeError: If update fails
        """
        try:
            vm_status = self.proxmox.nodes(node).qemu(vmid).status.current.get()
            if vm_status.get("status") == "running":
                raise ValueError(
                    f"VM {vmid} is currently running on node {node}. "
                    "Configuration changes can only be made on stopped VMs. "
                    "Use stop_vm or shutdown_vm to stop it first."
                )

            vm_name = vm_status.get("name", f"VM-{vmid}")

            config_params: Dict[str, Any] = {}
            changes: List[str] = []

            if cores is not None:
                config_params["cores"] = cores
                changes.append(f"cores={cores}")
            if sockets is not None:
                config_params["sockets"] = sockets
                changes.append(f"sockets={sockets}")
            if cpu_type is not None:
                config_params["cpu"] = cpu_type
                changes.append(f"cpu={cpu_type}")
            if vcpus is not None:
                config_params["vcpus"] = vcpus
                changes.append(f"vcpus={vcpus}")
            if memory is not None:
                config_params["memory"] = memory
                changes.append(f"memory={memory}MiB")
            if balloon is not None:
                config_params["balloon"] = balloon
                changes.append(f"balloon={balloon}")
            if disks is not None:
                config_params.update(disks)
                for k, v in disks.items():
                    changes.append(f"{k}={v}")
            if net0 is not None:
                config_params["net0"] = net0
                changes.append(f"net0={net0}")
            if net1 is not None:
                config_params["net1"] = net1
                changes.append(f"net1={net1}")
            if net2 is not None:
                config_params["net2"] = net2
                changes.append(f"net2={net2}")
            if net3 is not None:
                config_params["net3"] = net3
                changes.append(f"net3={net3}")
            if onboot is not None:
                config_params["onboot"] = 1 if onboot else 0
                changes.append(f"onboot={onboot}")
            if agent is not None:
                config_params["agent"] = 1 if agent else 0
                changes.append(f"agent={agent}")
            if boot is not None:
                config_params["boot"] = boot
                changes.append(f"boot={boot}")
            if bios is not None:
                config_params["bios"] = bios
                changes.append(f"bios={bios}")
            if ostype is not None:
                config_params["ostype"] = ostype
                changes.append(f"ostype={ostype}")
            if tags is not None:
                config_params["tags"] = tags
                changes.append(f"tags={tags}")
            if description is not None:
                config_params["description"] = description
                changes.append(f"description={description}")
            if startup is not None:
                config_params["startup"] = startup
                changes.append(f"startup={startup}")
            if scsihw is not None:
                config_params["scsihw"] = scsihw
                changes.append(f"scsihw={scsihw}")
            if vga is not None:
                config_params["vga"] = vga
                changes.append(f"vga={vga}")
            if tablet is not None:
                config_params["tablet"] = 1 if tablet else 0
                changes.append(f"tablet={tablet}")
            if kvm is not None:
                config_params["kvm"] = 1 if kvm else 0
                changes.append(f"kvm={kvm}")
            if machine is not None:
                config_params["machine"] = machine
                changes.append(f"machine={machine}")
            if nameserver is not None:
                config_params["nameserver"] = nameserver
                changes.append(f"nameserver={nameserver}")
            if searchdomain is not None:
                config_params["searchdomain"] = searchdomain
                changes.append(f"searchdomain={searchdomain}")
            if extra_config is not None:
                config_params.update(extra_config)
                for k, v in extra_config.items():
                    changes.append(f"{k}={v}")

            applied: List[str] = list(changes)
            errors: List[str] = []

            if config_params:
                try:
                    self.proxmox.nodes(node).qemu(vmid).config.put(**config_params)
                except Exception as e:
                    errors.append(f"config update failed: {e}")

            if disk_delete:
                for disk_id in disk_delete:
                    try:
                        self.proxmox.nodes(node).qemu(vmid).config.put(**{disk_id: "none"})
                        applied.append(f"deleted {disk_id}")
                    except Exception as e:
                        errors.append(f"delete {disk_id} failed: {e}")

            job_id_str = "n/a"
            if disk_resize:
                for disk_id, size_str in disk_resize.items():
                    try:
                        upid = self.proxmox.nodes(node).qemu(vmid).resize.put(
                            disk=disk_id, size=size_str
                        )
                        job = self._register_background_job(
                            tool_name="update_vm",
                            summary=f"Resize {disk_id} on VM {vmid} ({vm_name}) on {node}",
                            node=node,
                            upid=upid,
                            metadata={"vmid": vmid, "disk": disk_id, "size": size_str},
                            retry_spec={
                                "kind": "vm.config.update",
                                "params": {
                                    "node": node,
                                    "vmid": vmid,
                                    "disk": disk_id,
                                    "size": size_str,
                                },
                            },
                            retry_factory=lambda: self.proxmox.nodes(node).qemu(vmid).resize.put(
                                disk=disk_id, size=size_str,
                            ),
                            cancel_factory=lambda upid: self.proxmox.nodes(node).tasks(upid).status.stop.post(),
                        )
                        job_id_str = job["job_id"] if job else "n/a"
                        applied.append(f"{disk_id}+={size_str}")
                    except Exception as e:
                        errors.append(f"resize {disk_id} failed: {e}")

            result_lines = [f"VM {vmid} ({vm_name}) configuration update on {node}"]
            if applied:
                result_lines.append(f"Applied: {', '.join(applied)}")
            if errors:
                result_lines.append(f"Errors: {'; '.join(errors)}")
            if not applied and not errors:
                result_lines.append("No changes requested")

            if disk_resize:
                result_lines.append(f"Job ID: {job_id_str}")

            return [Content(type="text", text="\n".join(result_lines))]

        except ValueError as e:
            raise e
        except Exception as e:
            self._handle_error(f"update VM {vmid}", e)
