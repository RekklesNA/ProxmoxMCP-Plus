from typing import List, Dict, Optional, Tuple, Any, Union
import json
from mcp.types import TextContent as Content
from .base import ProxmoxTool


def _b2h(n: Union[int, float, str]) -> str:
    """bytes -> human (binary units)."""
    try:
        n = float(n)
    except Exception:
        return "0.00 B"
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    i = 0
    while n >= 1024.0 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    return f"{n:.2f} {units[i]}"

    # The rest of the helpers were preserved from your original file; no changes needed


def _get(d: Any, key: str, default: Any = None) -> Any:
    """dict.get with None guard."""
    if isinstance(d, dict):
        return d.get(key, default)
    return default


def _as_dict(maybe: Any) -> Dict:
    """Return dict; unwrap {'data': dict}; else {}."""
    if isinstance(maybe, dict):
        data = maybe.get("data")
        if isinstance(data, dict):
            return data
        return maybe
    return {}


def _as_list(maybe: Any) -> List:
    """Return list; unwrap {'data': list}; else []."""
    if isinstance(maybe, list):
        return maybe
    if isinstance(maybe, dict):
        data = maybe.get("data")
        if isinstance(data, list):
            return data
    return []


class ContainerTools(ProxmoxTool):
    """
    LXC container tools for Proxmox MCP.

    - Lists containers cluster-wide (or by node)
    - Live stats via /status/current
    - Limit fallback via /config (memory MiB, cores/cpulimit)
    - RRD fallback when live returns zeros
    - Pretty output rendered here; JSON path is raw & sanitized
    """

    # ---------- error / output ----------
    def _json_fmt(self, data: Any) -> List[Content]:
        """Return raw JSON string (never touch project formatters)."""
        return [Content(type="text", text=json.dumps(data, indent=2, sort_keys=True))]

    def _err(self, action: str, e: Exception) -> List[Content]:
        if hasattr(self, "handle_error"):
            return self.handle_error(e, action)  # type: ignore[attr-defined]
        if hasattr(self, "_handle_error"):
            return self._handle_error(action, e)  # type: ignore[attr-defined]
        return [Content(type="text", text=json.dumps({"error": str(e), "action": action}))]

    # ---------- helpers ----------
    def _list_ct_pairs(self, node: Optional[str]) -> List[Tuple[str, Dict]]:
        """Yield (node_name, ct_dict). Coerce odd shapes into dicts with vmid."""
        out: List[Tuple[str, Dict]] = []
        if node:
            try:
                raw = self.proxmox.nodes(node).lxc.get()
            except Exception as e:
                self.logger.warning(
                    "Skipping node %s while listing containers: %s", node, e
                )
                return out

            for it in _as_list(raw):
                if isinstance(it, dict):
                    out.append((node, it))
                else:
                    try:
                        vmid = int(it)
                        out.append((node, {"vmid": vmid}))
                    except Exception:
                        continue
        else:
            try:
                nodes = _as_list(self.proxmox.nodes.get())
            except Exception as e:
                self._handle_error("list containers", e)

            for n in nodes:
                nname = _get(n, "node")
                if not nname:
                    continue
                try:
                    raw = self.proxmox.nodes(nname).lxc.get()
                except Exception as node_error:
                    self.logger.warning(
                        "Skipping node %s while listing containers: %s", nname, node_error
                    )
                    continue

                for it in _as_list(raw):
                    if isinstance(it, dict):
                        out.append((nname, it))
                    else:
                        try:
                            vmid = int(it)
                            out.append((nname, {"vmid": vmid}))
                        except Exception:
                            continue
        return out

    def _rrd_last(self, node: str, vmid: int) -> Tuple[Optional[float], Optional[int], Optional[int]]:
        """Return (cpu_pct, mem_bytes, maxmem_bytes) from the most recent RRD sample."""
        try:
            rrd = _as_list(self.proxmox.nodes(node).lxc(vmid).rrddata.get(timeframe="hour", ds="cpu,mem,maxmem"))
            if not rrd or not isinstance(rrd[-1], dict):
                return None, None, None
            last = rrd[-1]
            # Proxmox RRD cpu is fraction already (0..1). Convert to percent.
            cpu_pct = float(_get(last, "cpu", 0.0) or 0.0) * 100.0
            mem_bytes = int(_get(last, "mem", 0) or 0)
            maxmem_bytes = int(_get(last, "maxmem", 0) or 0)
            return cpu_pct, mem_bytes, maxmem_bytes
        except Exception:
            return None, None, None

    def _status_and_config(self, node: str, vmid: int) -> Tuple[Dict, Dict]:
        """Return (status_current_dict, config_dict)."""
        raw_status: Dict = {}
        raw_config: Dict = {}
        try:
            raw_status = _as_dict(self.proxmox.nodes(node).lxc(vmid).status.current.get())
        except Exception:
            raw_status = {}
        try:
            raw_config = _as_dict(self.proxmox.nodes(node).lxc(vmid).config.get())
        except Exception:
            raw_config = {}
        return raw_status, raw_config

    def _render_pretty(self, rows: List[Dict]) -> List[Content]:
        lines: List[str] = ["📦 Containers", ""]
        for r in rows:
            name = r.get("name") or f"ct-{r.get('vmid')}"
            vmid = r.get("vmid")
            status = (r.get("status") or "").upper()
            node = r.get("node") or "?"
            cores = r.get("cores")
            cpu_pct = r.get("cpu_pct", 0.0)
            mem_bytes = int(r.get("mem_bytes") or 0)
            maxmem_bytes = int(r.get("maxmem_bytes") or 0)
            mem_pct = r.get("mem_pct")
            unlimited = bool(r.get("unlimited_memory", False))

            lines.append(f"📦 {name} (ID: {vmid})")
            lines.append(f"  • Status: {status}")
            lines.append(f"  • Node: {node}")
            lines.append(f"  • CPU: {cpu_pct:.1f}%")
            lines.append(f"  • CPU Cores: {cores if cores is not None else 'N/A'}")

            if unlimited:
                lines.append(f"  • Memory: {_b2h(mem_bytes)} (unlimited)")
            else:
                if maxmem_bytes > 0:
                    pct_str = f" ({mem_pct:.1f}%)" if isinstance(mem_pct, (int, float)) else ""
                    lines.append(f"  • Memory: {_b2h(mem_bytes)} / {_b2h(maxmem_bytes)}{pct_str}")
                else:
                    lines.append(f"  • Memory: {_b2h(mem_bytes)} / 0.00 B")
            lines.append("")
        return [Content(type="text", text="\n".join(lines).rstrip())]

    # ---------- tool ----------
    def get_containers(
        self,
        node: Optional[str] = None,
        include_stats: bool = True,
        include_raw: bool = False,
        format_style: str = "pretty",
    ) -> List[Content]:
        """
        List containers cluster-wide or by node.

        - `include_stats=True` fetches live CPU/mem from /status/current
        - RRD fallback is used if live returns zeros
        - `format_style='json'` returns raw JSON list (sanitized)
        - `format_style='pretty'` renders a human-friendly table
        """
        try:
            pairs = self._list_ct_pairs(node)
            rows: List[Dict] = []

            for nname, ct in pairs:
                vmid_val = _get(ct, "vmid")
                vmid_int: Optional[int] = None
                try:
                    if vmid_val is not None:
                        vmid_int = int(vmid_val)
                except Exception:
                    vmid_int = None

                rec: Dict = {
                    "vmid": str(vmid_val) if vmid_val is not None else None,
                    "name": _get(ct, "name") or _get(ct, "hostname") or (f"ct-{vmid_val}" if vmid_val is not None else "ct-?"),
                    "node": nname,
                    "status": _get(ct, "status"),
                }

                if include_stats and vmid_int is not None:
                    raw_status, raw_config = self._status_and_config(nname, vmid_int)

                    cpu_frac = float(_get(raw_status, "cpu", 0.0) or 0.0)
                    cpu_pct = round(cpu_frac * 100.0, 2)
                    mem_bytes = int(_get(raw_status, "mem", 0) or 0)
                    maxmem_bytes = int(_get(raw_status, "maxmem", 0) or 0)

                    memory_mib = 0
                    cores: Optional[Union[int, float]] = None
                    unlimited_memory = False

                    try:
                        cfg_mem = _get(raw_config, "memory")
                        if cfg_mem is None:
                            cfg_mem = _get(raw_config, "ram")
                        if cfg_mem is None:
                            cfg_mem = _get(raw_config, "maxmem")
                        if cfg_mem is None:
                            cfg_mem = _get(raw_config, "memoryMiB")
                        if cfg_mem is not None:
                            try:
                                memory_mib = int(cfg_mem)
                            except Exception:
                                memory_mib = 0
                        else:
                            memory_mib = 0

                        unlimited_memory = bool(_get(raw_config, "swap", 0) == 0 and memory_mib == 0)

                        cfg_cores = _get(raw_config, "cores")
                        cfg_cpulimit = _get(raw_config, "cpulimit")
                        if cfg_cores is not None:
                            cores = int(cfg_cores)
                        elif cfg_cpulimit is not None and float(cfg_cpulimit) > 0:
                            cores = float(cfg_cpulimit)
                    except Exception:
                        cores = None

                    # --- NEW: fallbacks for stopped / missing maxmem ---
                    status_str = str(_get(raw_status, "status") or _get(ct, "status") or "").lower()
                    
                    if status_str == "stopped":
                        try:
                            mem_bytes = 0
                        except Exception:
                            mem_bytes = 0

                    if (not maxmem_bytes or int(maxmem_bytes) == 0) and memory_mib and int(memory_mib) > 0:
                        try:
                            maxmem_bytes = int(memory_mib) * 1024 * 1024
                        except Exception:
                            maxmem_bytes = 0

                    # RRD fallback if zeros
                    if (mem_bytes == 0) or (maxmem_bytes == 0) or (cpu_pct == 0.0):
                        rrd_cpu, rrd_mem, rrd_maxmem = self._rrd_last(nname, vmid_int)
                        if cpu_pct == 0.0 and rrd_cpu is not None:
                            cpu_pct = rrd_cpu
                        if mem_bytes == 0 and rrd_mem is not None:
                            mem_bytes = rrd_mem
                        if maxmem_bytes == 0 and rrd_maxmem:
                            maxmem_bytes = rrd_maxmem
                            if memory_mib == 0:
                                try:
                                    memory_mib = int(round(maxmem_bytes / (1024 * 1024)))
                                except Exception:
                                    memory_mib = 0

                    rec.update({
                        "cores": cores,
                        "memory": memory_mib,
                        "cpu_pct": cpu_pct,
                        "mem_bytes": mem_bytes,
                        "maxmem_bytes": maxmem_bytes,
                        "mem_pct": (
                            round((mem_bytes / maxmem_bytes * 100.0), 2)
                            if (maxmem_bytes and maxmem_bytes > 0)
                            else None
                        ),
                        "unlimited_memory": unlimited_memory,
                    })

                    # For PRETTY only: allow raw blobs to be attached if requested.
                    if include_raw and format_style != "json":
                        rec["raw_status"] = raw_status
                        rec["raw_config"] = raw_config

                rows.append(rec)

            if format_style == "json":
                # JSON path must be immune to any formatter assumptions; no raw payloads.
                return self._json_fmt(rows)
            return self._render_pretty(rows)

        except Exception as e:
            return self._err("Failed to list containers", e)

    # ---------- target resolution for control ops ----------
    def _resolve_targets(self, selector: str) -> List[Tuple[str, int, str]]:
        """
        Turn a selector string into a list of (node, vmid, label).
        Supports:
          - '123' (vmid across cluster)
          - 'pve1:123' (node:vmid)
          - 'pve1/name' (node/name)
          - 'name' (by name/hostname across the cluster)
          - comma-separated list of any of the above
        """
        if not selector:
            return []
        tokens = [t.strip() for t in selector.split(",") if t.strip()]
        inventory: List[Tuple[str, Dict[str, Any]]] = self._list_ct_pairs(node=None)

        resolved: List[Tuple[str, int, str]] = []
        for tok in tokens:
            if ":" in tok and "/" not in tok:
                node, vmid_s = tok.split(":", 1)
                try:
                    vmid = int(vmid_s)
                except Exception:
                    continue
                for n, ct in inventory:
                    if n == node and int(_get(ct, "vmid", -1)) == vmid:
                        label = _get(ct, "name") or _get(ct, "hostname") or f"ct-{vmid}"
                        resolved.append((node, vmid, label))
                        break
                continue

            if "/" in tok and ":" not in tok:
                node, name = tok.split("/", 1)
                name = name.strip()
                for n, ct in inventory:
                    if n == node and (_get(ct, "name") == name or _get(ct, "hostname") == name):
                        vmid = int(_get(ct, "vmid", -1))
                        if vmid >= 0:
                            resolved.append((node, vmid, name))
                continue

            if tok.isdigit():
                vmid = int(tok)
                for n, ct in inventory:
                    if int(_get(ct, "vmid", -1)) == vmid:
                        label = _get(ct, "name") or _get(ct, "hostname") or f"ct-{vmid}"
                        resolved.append((n, vmid, label))
                continue

            name = tok
            for n, ct in inventory:
                if _get(ct, "name") == name or _get(ct, "hostname") == name:
                    vmid = int(_get(ct, "vmid", -1))
                    if vmid >= 0:
                        resolved.append((n, vmid, name))

        uniq = {}
        for n, v, lbl in resolved:
            uniq[(n, v)] = lbl
        return [(n, v, uniq[(n, v)]) for (n, v) in uniq.keys()]

    def _render_action_result(self, title: str, results: List[Dict[str, Any]]) -> List[Content]:
        """Pretty-print an action result; JSON stays raw."""
        lines = [f"📦 {title}", ""]
        for r in results:
            status = "✅ OK" if r.get("ok") else "❌ FAIL"
            node = r.get("node")
            vmid = r.get("vmid")
            name = r.get("name") or f"ct-{vmid}"
            msg = r.get("message") or r.get("error") or ""
            lines.append(f"{status} {name} (ID: {vmid}, node: {node}) {('- ' + str(msg)) if msg else ''}")
        return [Content(type="text", text="\n".join(lines).rstrip())]

    # ---------- container control tools ----------
    def start_container(self, selector: str, format_style: str = "pretty") -> List[Content]:
        """
        Start LXC containers matching `selector`.
        selector examples: '123', 'pve1:123', 'pve1/name', 'name', 'pve1:101,pve2/web'
        """
        try:
            targets = self._resolve_targets(selector)
            if not targets:
                return self._err("No containers matched the selector", ValueError(selector))

            results: List[Dict[str, Any]] = []
            for node, vmid, label in targets:
                try:
                    resp = self.proxmox.nodes(node).lxc(vmid).status.start.post()
                    results.append({"ok": True, "node": node, "vmid": vmid, "name": label, "message": resp})
                except Exception as e:
                    results.append({"ok": False, "node": node, "vmid": vmid, "name": label, "error": str(e)})

            if format_style == "json":
                return self._json_fmt(results)
            return self._render_action_result("Start Containers", results)

        except Exception as e:
            return self._err("Failed to start container(s)", e)

    def stop_container(self, selector: str, graceful: bool = True, timeout_seconds: int = 10,
                       format_style: str = "pretty") -> List[Content]:
        """
        Stop LXC containers.
        graceful=True → POST .../status/shutdown (graceful stop)
        graceful=False → POST .../status/stop (force stop)
        """
        try:
            targets = self._resolve_targets(selector)
            if not targets:
                return self._err("No containers matched the selector", ValueError(selector))

            results: List[Dict[str, Any]] = []
            for node, vmid, label in targets:
                try:
                    if graceful:
                        resp = self.proxmox.nodes(node).lxc(vmid).status.shutdown.post(timeout=timeout_seconds)
                    else:
                        resp = self.proxmox.nodes(node).lxc(vmid).status.stop.post()
                    results.append({"ok": True, "node": node, "vmid": vmid, "name": label, "message": resp})
                except Exception as e:
                    results.append({"ok": False, "node": node, "vmid": vmid, "name": label, "error": str(e)})

            if format_style == "json":
                return self._json_fmt(results)
            return self._render_action_result("Stop Containers", results)

        except Exception as e:
            return self._err("Failed to stop container(s)", e)

    def restart_container(self, selector: str, timeout_seconds: int = 10,
                          format_style: str = "pretty") -> List[Content]:
        """
        Restart LXC containers via POST .../status/reboot.
        """
        try:
            targets = self._resolve_targets(selector)
            if not targets:
                return self._err("No containers matched the selector", ValueError(selector))

            results: List[Dict[str, Any]] = []
            for node, vmid, label in targets:
                try:
                    resp = self.proxmox.nodes(node).lxc(vmid).status.reboot.post()
                    results.append({"ok": True, "node": node, "vmid": vmid, "name": label, "message": resp})
                except Exception as e:
                    results.append({"ok": False, "node": node, "vmid": vmid, "name": label, "error": str(e)})

            if format_style == "json":
                return self._json_fmt(results)
            return self._render_action_result("Restart Containers", results)

        except Exception as e:
            return self._err("Failed to restart container(s)", e)

    def create_container(
        self,
        node: str,
        vmid: str,
        ostemplate: str,
        hostname: Optional[str] = None,
        cores: int = 1,
        memory: int = 512,
        swap: int = 512,
        disk_size: int = 8,
        storage: Optional[str] = None,
        password: Optional[str] = None,
        ssh_public_keys: Optional[str] = None,
        network_bridge: str = "vmbr0",
        start_after_create: bool = False,
        unprivileged: bool = True,
    ) -> List[Content]:
        """Create a new LXC container.

        Parameters:
            node: Host node name (e.g., 'pve')
            vmid: Container ID number (e.g., '200')
            ostemplate: OS template path (e.g., 'local:vztmpl/alpine-3.19-default_20240207_amd64.tar.xz')
            hostname: Container hostname (defaults to 'ct-{vmid}')
            cores: Number of CPU cores (default: 1)
            memory: Memory size in MiB (default: 512)
            swap: Swap size in MiB (default: 512)
            disk_size: Root disk size in GB (default: 8)
            storage: Storage pool for rootfs (auto-detect if not specified)
            password: Root password (optional)
            ssh_public_keys: SSH public keys for root (optional)
            network_bridge: Network bridge (default: 'vmbr0')
            start_after_create: Start container after creation (default: False)
            unprivileged: Create unprivileged container (default: True)

        Returns:
            List[Content] with creation result
        """
        try:
            # Validate vmid doesn't already exist
            existing = self._list_ct_pairs(node=None)
            for n, ct in existing:
                if str(_get(ct, "vmid")) == str(vmid):
                    return self._err(
                        f"Container with ID {vmid} already exists on node {n}",
                        ValueError(f"VMID {vmid} already in use")
                    )

            # Validate node exists
            nodes = _as_list(self.proxmox.nodes.get())
            node_names = [_get(n, "node") for n in nodes]
            if node not in node_names:
                return self._err(
                    f"Node '{node}' not found",
                    ValueError(f"Available nodes: {', '.join(node_names)}")
                )

            # Auto-detect storage if not specified
            if not storage:
                storage_list = _as_list(self.proxmox.storage.get())
                # Prefer local-lvm, then any storage that supports rootdir/images
                for s in storage_list:
                    sname = _get(s, "storage")
                    stype = _get(s, "type")
                    content = _get(s, "content", "")
                    if sname == "local-lvm":
                        storage = sname
                        break
                    if "rootdir" in content or "images" in content:
                        storage = sname
                if not storage:
                    # Fallback to first storage
                    if storage_list:
                        storage = _get(storage_list[0], "storage", "local")
                    else:
                        storage = "local"

            # Set default hostname
            if not hostname:
                hostname = f"ct-{vmid}"

            # Build container configuration
            ct_config = {
                "vmid": int(vmid),
                "ostemplate": ostemplate,
                "hostname": hostname,
                "cores": cores,
                "memory": memory,
                "swap": swap,
                "rootfs": f"{storage}:{disk_size}",
                "net0": f"name=eth0,bridge={network_bridge},ip=dhcp",
                "unprivileged": 1 if unprivileged else 0,
                "start": 1 if start_after_create else 0,
            }

            # Add optional parameters
            if password:
                ct_config["password"] = password
            if ssh_public_keys:
                ct_config["ssh-public-keys"] = ssh_public_keys

            # Create the container
            result = self.proxmox.nodes(node).lxc.create(**ct_config)

            # Format success response
            lines = [
                "📦 Container Created Successfully",
                "",
                f"  • VMID: {vmid}",
                f"  • Hostname: {hostname}",
                f"  • Node: {node}",
                f"  • Template: {ostemplate}",
                f"  • CPU Cores: {cores}",
                f"  • Memory: {memory} MiB",
                f"  • Swap: {swap} MiB",
                f"  • Disk: {disk_size} GB on {storage}",
                f"  • Network: {network_bridge} (DHCP)",
                f"  • Unprivileged: {'Yes' if unprivileged else 'No'}",
                f"  • Auto-start: {'Yes' if start_after_create else 'No'}",
                "",
                f"Task ID: {result}",
                "",
                "Next steps:",
                f"  • Start container: start_container selector='{vmid}'",
                f"  • Check status: get_containers",
            ]
            return [Content(type="text", text="\n".join(lines))]

        except Exception as e:
            return self._err(f"Failed to create container {vmid}", e)

    def delete_container(
        self,
        selector: str,
        force: bool = False,
        format_style: str = "pretty",
    ) -> List[Content]:
        """Delete one or more LXC containers.

        Parameters:
            selector: Container selector (same grammar as start_container)
            force: Force deletion even if container is running (default: False)
            format_style: Output format ('pretty' or 'json')

        Returns:
            List[Content] with deletion results
        """
        try:
            targets = self._resolve_targets(selector)
            if not targets:
                return self._err("No containers matched the selector", ValueError(selector))

            results: List[Dict[str, Any]] = []
            for node, vmid, label in targets:
                rec: Dict[str, Any] = {"ok": True, "node": node, "vmid": vmid, "name": label}

                try:
                    # Check container status
                    status_dict = _as_dict(
                        self.proxmox.nodes(node).lxc(vmid).status.current.get()
                    )
                    current_status = _get(status_dict, "status", "").lower()

                    # Handle running container
                    if current_status == "running":
                        if not force:
                            rec["ok"] = False
                            rec["error"] = "Container is running. Use force=True to stop and delete."
                            results.append(rec)
                            continue
                        # Force stop the container first
                        self.proxmox.nodes(node).lxc(vmid).status.stop.post()
                        rec["message"] = "Stopped and deleted"
                    else:
                        rec["message"] = "Deleted"

                    # Delete the container
                    task_result = self.proxmox.nodes(node).lxc(vmid).delete()
                    rec["task_id"] = str(task_result)

                except Exception as e:
                    rec["ok"] = False
                    rec["error"] = str(e)

                results.append(rec)

            if format_style == "json":
                return self._json_fmt(results)
            return self._render_action_result("Delete Containers", results)

        except Exception as e:
            return self._err("Failed to delete container(s)", e)

    def update_container_resources(
        self,
        selector: str,
        cores: Optional[int] = None,
        memory: Optional[int] = None,
        swap: Optional[int] = None,
        disk_gb: Optional[int] = None,
        disk: str = "rootfs",
        format_style: str = "pretty",
    ) -> List[Content]:
        """Update container CPU/memory/swap limits and/or extend disk size.

        Parameters:
            selector: Container selector (same grammar as start_container)
            cores: New CPU core count
            memory: New memory limit in MiB
            swap: New swap limit in MiB
            disk_gb: Additional disk size to add in GiB
            disk: Disk identifier to resize (default 'rootfs')
            format_style: Output format ('pretty' or 'json')
        """

        try:
            targets = self._resolve_targets(selector)
            if not targets:
                return self._err("No containers matched the selector", ValueError(selector))

            results: List[Dict[str, Any]] = []
            for node, vmid, label in targets:
                rec: Dict[str, Any] = {"ok": True, "node": node, "vmid": vmid, "name": label}
                changes: List[str] = []

                try:
                    update_params: Dict[str, Any] = {}
                    if cores is not None:
                        update_params["cores"] = cores
                        changes.append(f"cores={cores}")
                    if memory is not None:
                        update_params["memory"] = memory
                        changes.append(f"memory={memory}MiB")
                    if swap is not None:
                        update_params["swap"] = swap
                        changes.append(f"swap={swap}MiB")

                    if update_params:
                        self.proxmox.nodes(node).lxc(vmid).config.put(**update_params)

                    if disk_gb is not None:
                        size_str = f"+{disk_gb}G"
                        # Use PUT for disk resize - some Proxmox versions reject POST
                        self.proxmox.nodes(node).lxc(vmid).resize.put(disk=disk, size=size_str)
                        changes.append(f"{disk}+={disk_gb}G")

                    rec["message"] = ", ".join(changes) if changes else "no changes"
                except Exception as e:
                    rec["ok"] = False
                    rec["error"] = str(e)

                results.append(rec)

            if format_style == "json":
                return self._json_fmt(results)
            return self._render_action_result("Update Container Resources", results)

        except Exception as e:
            return self._err("Failed to update container(s)", e)
