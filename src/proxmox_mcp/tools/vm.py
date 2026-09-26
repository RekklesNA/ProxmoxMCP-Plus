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
from proxmox_mcp.tools.guest_config import bridge_name, parse_device, vm_media
import json
import re
import urllib.parse
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

    def set_vm_description(
        self, node: str, vmid: str, description: str
    ) -> List[Content]:
        """Set/replace the description (Notes field in the UI) of a QEMU VM.

        Uses PUT /nodes/{node}/qemu/{vmid}/config. Pass an empty string to
        clear the notes.

        Parameters:
            node: Proxmox node name.
            vmid: VM ID as a string.
            description: New notes text (replaces any existing notes).
        """
        try:
            self.proxmox.nodes(node).qemu(vmid).config.put(description=description)
            return self._json_fmt({"vmid": vmid, "node": node, "description": description})
        except Exception as e:
            return self._err("set_vm_description", e)

    def get_next_vmid(self) -> List[Content]:
        """Return the next free VM/CT ID from the cluster (GET /cluster/nextid)."""
        try:
            next_id = self.proxmox.cluster.nextid.get()
            return self._json_fmt({"vmid": str(next_id)})
        except Exception as e:
            return self._err("get_next_vmid", e)

    def update_vm_config(
        self,
        node: str,
        vmid: str,
        memory: Optional[int] = None,
        cores: Optional[int] = None,
        sockets: Optional[int] = None,
        name: Optional[str] = None,
        sshkeys: Optional[str] = None,
        ciuser: Optional[str] = None,
        ipconfig0: Optional[str] = None,
        nameserver: Optional[str] = None,
        searchdomain: Optional[str] = None,
        tags: Optional[str] = None,
        approval_token: Optional[str] = None,
        iso_volume: Optional[str] = None,
        cdrom_device: str = "ide3",
        boot_order: Optional[str] = None,
        network_bridge: Optional[str] = None,
    ) -> List[Content]:
        """Update sizing and cloud-init settings of an existing QEMU VM.

        Uses PUT /nodes/{node}/qemu/{vmid}/config with only the fields that
        were supplied. Cloud-init fields (sshkeys, ciuser, ipconfig0,
        nameserver, searchdomain) take effect at the guest's next boot;
        sizing changes on a running VM are applied as pending changes.

        The ``sshkeys`` value is URL-encoded before it is sent: the Proxmox
        API expects the *value* of that field to be percent-encoded on top of
        the form encoding of the request (the same quirk `qm set --sshkeys`
        hides), and a raw key is rejected with "invalid format".
        """
        # Approval is enforced by the target-aware tool wrapper, not the PVE API.
        _ = approval_token
        payload: Dict[str, Any] = {}
        if memory is not None:
            if memory < 16:
                raise ValueError("memory must be at least 16 MiB")
            payload["memory"] = int(memory)
        if cores is not None:
            if cores < 1:
                raise ValueError("cores must be at least 1")
            payload["cores"] = int(cores)
        if sockets is not None:
            if sockets < 1:
                raise ValueError("sockets must be at least 1")
            payload["sockets"] = int(sockets)
        if name is not None:
            if not re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?", name):
                raise ValueError("name must be a valid DNS label (letters, digits and hyphens)")
            payload["name"] = name
        if sshkeys is not None:
            keys = [line.strip() for line in sshkeys.splitlines() if line.strip()]
            if not keys:
                raise ValueError("sshkeys must contain at least one public key")
            for key in keys:
                if not re.match(r"^(ssh-(rsa|ed25519|dss)|ecdsa-sha2-nistp\d+|sk-(ssh-ed25519|ecdsa-sha2-nistp256)@openssh\.com) [A-Za-z0-9+/=]+", key):
                    raise ValueError("sshkeys must be OpenSSH public keys, one per line")
            payload["sshkeys"] = urllib.parse.quote("\n".join(keys), safe="")
        if ciuser is not None:
            if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", ciuser):
                raise ValueError("ciuser must be a valid Unix user name")
            payload["ciuser"] = ciuser
        if ipconfig0 is not None:
            if not re.fullmatch(r"(ip=[^,\s]+|ip6=[^,\s]+|gw=[^,\s]+|gw6=[^,\s]+)(,(ip=[^,\s]+|ip6=[^,\s]+|gw=[^,\s]+|gw6=[^,\s]+))*", ipconfig0):
                raise ValueError("ipconfig0 must look like 'ip=dhcp' or 'ip=10.0.0.5/24,gw=10.0.0.1'")
            payload["ipconfig0"] = ipconfig0
        if nameserver is not None:
            payload["nameserver"] = nameserver
        if searchdomain is not None:
            payload["searchdomain"] = searchdomain
        if tags is not None:
            payload["tags"] = tags
        media = vm_media(iso_volume, cdrom_device, boot_order)
        if network_bridge is not None:
            bridge_name(network_bridge)
        if media or network_bridge is not None:
            current = self.proxmox.nodes(node).qemu(vmid).config.get()
            payload.update(vm_media(iso_volume, cdrom_device, boot_order, current))
            if network_bridge is not None:
                if not current.get("net0"):
                    raise ValueError("VM has no net0 interface to update")
                network = parse_device(current["net0"])
                network["bridge"] = network_bridge
                payload["net0"] = ",".join(f"{key}={value}" for key, value in network.items())
            if current.get("digest"):
                payload["digest"] = current["digest"]
        if not payload:
            raise ValueError("update_vm_config needs at least one setting to change")

        try:
            self.proxmox.nodes(node).qemu(vmid).config.put(**payload)
        except Exception as e:
            if "does not exist" in str(e).lower() or "not found" in str(e).lower():
                raise ValueError(f"VM {vmid} not found on node {node}") from e
            return self._err("update_vm_config", e)

        applied = {key: value for key, value in payload.items() if key != "digest"}
        if "sshkeys" in applied:
            applied["sshkeys"] = f"{len(keys)} key(s)"
        cloud_init_fields = {"sshkeys", "ciuser", "ipconfig0", "nameserver", "searchdomain"}
        notes = []
        if cloud_init_fields & payload.keys():
            notes.append("cloud-init settings are applied by the guest at its next boot")
        if {"memory", "cores", "sockets"} & payload.keys():
            notes.append("sizing changes on a running VM stay pending until it is restarted")
        return self._json_fmt({"vmid": vmid, "node": node, "applied": applied, "notes": notes})

    def get_vm_ip_addresses(self, node: str, vmid: str) -> List[Content]:
        """Return the guest's interfaces and addresses via the QEMU guest agent.

        Uses GET /nodes/{node}/qemu/{vmid}/agent/network-get-interfaces, so the
        VM must be running with the guest agent active. Loopback is skipped;
        ``primary_ip`` is the first non-loopback IPv4 address.
        """
        try:
            raw = self.proxmox.nodes(node).qemu(vmid).agent("network-get-interfaces").get()
        except Exception as e:
            message = str(e).lower()
            # ACL names and request URLs also contain "agent"; preserve those errors.
            if getattr(e, "status_code", None) in {401, 403}:
                return self._err("get_vm_ip_addresses", e)
            unavailable = re.search(
                r"\b(?:qemu )?guest agent (?:is )?(?:not running|not enabled|not responding)\b"
                r"|\bvm \d+ (?:is )?not running\b"
                r"|\bguest-(?:ping|network-get-interfaces)\b.*\b(?:timed out|timeout)\b",
                message,
            )
            if unavailable:
                raise ValueError(
                    f"Guest agent on VM {vmid} did not answer; the VM must be running with qemu-guest-agent active"
                ) from e
            return self._err("get_vm_ip_addresses", e)

        result_list = raw.get("result") if isinstance(raw, dict) else raw
        interfaces: List[Dict[str, Any]] = []
        primary_ip: Optional[str] = None
        for iface in result_list or []:
            if not isinstance(iface, dict):
                continue
            iface_name = iface.get("name")
            if iface_name == "lo":
                continue
            entry: Dict[str, Any] = {"name": iface_name, "ipv4": [], "ipv6": []}
            mac = iface.get("hardware-address")
            if mac:
                entry["mac"] = mac
            for addr in iface.get("ip-addresses") or []:
                ip = addr.get("ip-address")
                if not ip:
                    continue
                kind = "ipv6" if addr.get("ip-address-type") == "ipv6" else "ipv4"
                entry[kind].append(ip)
                if kind == "ipv4" and primary_ip is None and not ip.startswith("127."):
                    primary_ip = ip
            interfaces.append(entry)
        return self._json_fmt({"vmid": vmid, "node": node, "interfaces": interfaces, "primary_ip": primary_ip})

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
        pool: Optional[str] = None,
        iso_volume: Optional[str] = None,
        cdrom_device: str = "ide3",
        boot_order: Optional[str] = None,
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
            pool: Proxmox resource pool to create the VM in. If None, no pool is specified
            
        Returns:
            List of Content objects containing creation result
            
        Raises:
            ValueError: If VM ID already exists or invalid parameters
            RuntimeError: If VM creation fails
        """
        media = vm_media(iso_volume, cdrom_device, boot_order)
        if iso_volume == "none":
            raise ValueError("Use an ISO volume ID when creating a VM")
        if network_bridge is not None:
            bridge_name(network_bridge)
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
            if iso_volume is not None and boot_order is None:
                media["boot"] = f"order={cdrom_device};scsi0"
            # Never replace the disk or cloud-init drive created above.
            vm_media(iso_volume, cdrom_device, boot_order, vm_config)
            vm_config.update(media)

            if pool:
                vm_config["pool"] = pool
            
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
                cancel_factory=lambda upid: self.proxmox.nodes(node).tasks(upid).delete(),
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
            cancel_factory=lambda upid: self.proxmox.nodes(node).tasks(upid).delete(),
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
                    cancel_factory=lambda upid: self.proxmox.nodes(node).tasks(upid).delete(),
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
                    cancel_factory=lambda upid: self.proxmox.nodes(node).tasks(upid).delete(),
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
                    cancel_factory=lambda upid: self.proxmox.nodes(node).tasks(upid).delete(),
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
                    cancel_factory=lambda upid: self.proxmox.nodes(node).tasks(upid).delete(),
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
                cancel_factory=lambda upid: self.proxmox.nodes(node).tasks(upid).delete(),
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
