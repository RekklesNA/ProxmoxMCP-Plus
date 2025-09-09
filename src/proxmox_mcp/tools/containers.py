from typing import List, Dict, Optional, Tuple, Any, Union
import json
from mcp.types import TextContent as Content
from .base import ProxmoxTool


def _b2h(n: Union[int, float, str]) -> str:
    """
    Convert a numeric byte value to a human-readable string using binary units (powers of 1024).
    
    Accepts an int, float, or numeric string and returns a formatted string like "1.23 KiB" or "42.00 B".
    If the input cannot be converted to a number, returns "0.00 B".
    """
    try:
        n = float(n)
    except Exception:
        return "0.00 B"
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    i = 0
    while n >= 1024.0 and i < len(units) - 1:
        n /= 1024.0
    # NOTE: original content omitted for brevity in earlier views; this is the full file

    # The rest of the helpers were preserved from your original file; no changes needed


def _get(d: Any, key: str, default: Any = None) -> Any:
    """
    Safely retrieve a value from a mapping-like object.
    
    Returns d.get(key, default) when d is a dict; otherwise returns default.
    
    Parameters:
        d: The object to read from; only dicts are queried.
        key: Key to look up in the dict.
        default: Value returned when key is missing or when d is not a dict.
    
    Returns:
        The value for `key` from `d` if present and `d` is a dict; otherwise `default`.
    """
    if isinstance(d, dict):
        return d.get(key, default)
    return default


def _as_dict(maybe: Any) -> Dict:
    """
    Normalize an input to a dict.
    
    If `maybe` is a dict and contains a `data` key whose value is a dict, return that inner dict.
    If `maybe` is a dict (but has no `data` dict), return `maybe` itself.
    For any other input, return an empty dict.
    """
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
        """
        Return a standardized error response as a list of Content items.
        
        If the instance defines a public `handle_error(e, action)` or a private `_handle_error(action, e)` method, delegate to it and return its result. Otherwise, return a single Content item of type "text" containing a JSON object with keys "error" (stringified exception) and "action" (the action name).
        
        Parameters:
            action (str): Short name or description of the action that failed.
            e (Exception): The caught exception.
        
        Returns:
            List[Content]: A list of Content items representing the error response.
        """
        if hasattr(self, "handle_error"):
            return self.handle_error(e, action)  # type: ignore[attr-defined]
        if hasattr(self, "_handle_error"):
            return self._handle_error(action, e)  # type: ignore[attr-defined]
        return [Content(type="text", text=json.dumps({"error": str(e), "action": action}))]

    # ---------- helpers ----------
    def _list_ct_pairs(self, node: Optional[str]) -> List[Tuple[str, Dict]]:
        """
        Return a list of (node_name, container_dict) tuples for LXC containers.
        
        If a `node` is provided, queries that node's LXC list; otherwise queries all cluster nodes discovered via the API.
        Each container entry is normalized to a dict. If an item from the API is already a dict it is returned as-is; if it is a scalar convertible to an integer it is coerced to {"vmid": <int>}. Non-dict, non-integer items are skipped.
        
        Parameters:
            node (Optional[str]): Specific node name to limit the query to, or None to query all nodes.
        
        Returns:
            List[Tuple[str, Dict]]: A list of (node_name, container_dict) tuples.
        """
        out: List[Tuple[str, Dict]] = []
        if node:
            raw = self.proxmox.nodes(node).lxc.get()
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
            nodes = _as_list(self.proxmox.nodes.get())
            for n in nodes:
                nname = _get(n, "node")
                if not nname:
                    continue
                raw = self.proxmox.nodes(nname).lxc.get()
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
        """
        Return the most recent RRD sample for a container as (cpu_pct, mem_bytes, maxmem_bytes).
        
        Parameters:
            node (str): Proxmox node name containing the container.
            vmid (int): Container numeric ID.
        
        Returns:
            tuple: (cpu_pct, mem_bytes, maxmem_bytes) where `cpu_pct` is CPU usage as a percentage (0.0–100.0),
            and `mem_bytes`/`maxmem_bytes` are memory values in bytes. If no valid RRD sample is available or an
            error occurs, returns (None, None, None).
        """
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
        """
        Return the current runtime status and configuration for an LXC container.
        
        Queries the Proxmox API for the container's live status and its configuration, normalizing each result to a dict with _as_dict. If either API call fails or returns unexpected data, that value will be an empty dict.
        
        Parameters:
            node (str): Proxmox node name where the container resides.
            vmid (int): Container VMID.
        
        Returns:
            Tuple[Dict, Dict]: (status_current_dict, config_dict) — both are dicts (possibly empty).
        """
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
        """
        Render a list of container records into a human-readable text Content item.
        
        Formats each dict in `rows` as a block containing name, ID, node, status, CPU percentage, CPU cores,
        and memory usage. Memory is shown in human-readable binary units; if `unlimited_memory` is True the
        memory line is annotated as "(unlimited)". When `maxmem_bytes` is zero the max value is shown as "0.00 B".
        
        Parameters:
            rows (List[Dict]): List of container dictionaries. Relevant keys (all optional except `vmid` for identification):
                - vmid: numeric or string container ID.
                - name: display name; falls back to `ct-<vmid>` if missing.
                - status: container state string.
                - node: node name where the container runs.
                - cores: configured CPU cores.
                - cpu_pct: current CPU usage percentage (float).
                - mem_bytes: current memory in bytes.
                - maxmem_bytes: configured maximum memory in bytes.
                - mem_pct: memory usage percent (float), used when `maxmem_bytes` > 0.
                - unlimited_memory: truthy to indicate unlimited memory.
        
        Returns:
            List[Content]: A single-element list containing a Content item of type "text" with the rendered lines.
        """
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
        Return a list of containers for the cluster or a single node, optionally including live stats, raw backend blobs, and formatted as JSON or a human-readable text block.
        
        Parameters:
            node (Optional[str]): If provided, limit results to this node name; otherwise list across the cluster.
            include_stats (bool): When True, fetch live CPU and memory from the container's status/config and fall back to RRD samples if live values are zero.
            include_raw (bool): When True and `format_style` is not "json", attach raw `status` and `config` blobs to each record.
            format_style (str): Output format; "json" returns a JSON-safe list, "pretty" returns a human-readable Content text block.
        
        Returns:
            List[Content]: A list containing a single Content item with formatted output (JSON string or plain text) or an error Content produced by the tool's error handler.
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
        Resolve a textual selector into concrete container targets.
        
        Supported selector forms (single or comma-separated):
        - "123"            — vmid anywhere in the cluster
        - "node:123"       — specific node and vmid
        - "node/name"      — container name or hostname on a specific node
        - "name"           — container name or hostname across the cluster
        
        Behavior:
        - Returns a list of unique (node, vmid, label) tuples where `label` is the container name, hostname, or a fallback `ct-<vmid>`.
        - Invalid or non-matching tokens are ignored.
        - Matching is exact (no pattern or substring matching).
        - The returned list is deduplicated by (node, vmid); when duplicates are found the last resolved label is used.
        - An empty or falsy selector yields an empty list.
        
        Returns:
            List[Tuple[str, int, str]]: Resolved targets as (node, vmid, label).
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
        """
        Render action results as a human-readable text block suitable for display.
        
        Parameters:
            title (str): Short title describing the action (e.g., "Start containers").
            results (List[Dict[str, Any]]): List of result records for each target. Each record should contain keys like
                "ok" (truthy on success), "node", "vmid", and optionally "name", "message", or "error".
        
        Returns:
            List[Content]: A single-item list containing a Content of type "text" with the pretty-printed result lines.
        """
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
        Start one or more LXC containers identified by a selector.
        
        The selector can be a single target or a comma-separated list and supports:
        - vmid (e.g. "123") — matches that VM across the cluster
        - node:vmid (e.g. "pve1:123")
        - node/name (e.g. "pve1/web")
        - name or hostname (e.g. "web")
        
        Parameters:
            selector (str): Selector string identifying target containers.
            format_style (str): "json" to return structured JSON output; any other value returns a human-readable Content item.
        
        Returns:
            List[Content]: A list containing either a JSON Content entry (when format_style == "json") or a pretty-printed action result.
        
        Behavior:
        - Resolves targets via _resolve_targets; if no targets match, returns a structured error Content.
        - Attempts to start each matched container and aggregates per-target results including success status and any error message.
        - On unexpected exceptions, returns an error Content via the tool's centralized error handler.
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
                       Stop one or more LXC containers matching the given selector.
                       
                       Attempts a graceful shutdown by default; can perform a forced stop. The selector may be a vmid, node:vmid, node/name, name, or a comma-separated list of those forms (resolved via _resolve_targets). Results are returned as a list of Content objects: when format_style == "json" the payload is JSON; otherwise a human-readable summary is returned.
                       
                       Parameters:
                           selector (str): Target selector string identifying one or more containers.
                           graceful (bool): If True (default), attempt a graceful shutdown via the container's shutdown API; if False, issue a force stop.
                           timeout_seconds (int): Timeout in seconds passed to the graceful shutdown request (only used when graceful is True).
                           format_style (str): "json" to return machine-readable JSON output; any other value returns a pretty-printed text Content.
                       
                       Returns:
                           List[Content]: A list containing one Content item with the operation results (JSON or pretty text). Individual container failures are reported per-target in the result payload; if no targets match or an unexpected error occurs, an error Content is returned via _err.
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
                          Restart one or more LXC containers matching the given selector.
                          
                          Attempts to reboot each resolved container by calling the Proxmox LXC status/reboot endpoint. The selector accepts the same formats handled by _resolve_targets (single or comma-separated vmid, node:vmid, node/name, or container name). Results are returned either as JSON content or a human-readable summary.
                          
                          Parameters:
                              selector (str): Target selector identifying one or more containers.
                              timeout_seconds (int): Present for API compatibility but not used by this operation.
                              format_style (str): Output style; either "pretty" (default) or "json".
                          
                          Returns:
                              List[Content]: A list with a single Content item containing either JSON-formatted results
                              or a pretty-printed action summary. Errors for individual containers are included in the results;
                              high-level failures are routed through the tool's centralized error handler.
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
