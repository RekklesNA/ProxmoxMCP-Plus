# Multi-target Proxmox MCP design

## Goal

Extend ProxmoxMCP-Plus to serve two independent Proxmox environments through one Streamable HTTP MCP service:

- `cluster`: the existing HAProxy-backed `pve1`, `pve2`, and `pve3` cluster.
- `pl`: the independent Proxmox server at `pl.hadm.net`.

Hermes is the primary consumer. No CLI is planned.

## Configuration and compatibility

Retain the existing single-target `proxmox` + `auth` configuration. When that shape is used, all existing MCP calls remain valid and omit `target`.

Add a `targets` map whose entries contain connection, authentication, optional SSH, read-only, and policy settings. Legacy and multi-target sections must not be combined silently; loading both fails with an actionable error.

Target resolution is exact: an explicit target must match a configured name; an omitted target defaults only when exactly one target is configured; omission with multiple targets fails before any upstream request. Target names are never inferred from node names or VMIDs.

## MCP surface

Preserve existing tool names and add an optional `target` parameter to each. The schema description states that it is required when multiple targets are configured. Add read-only `list_targets`, returning deterministic, bounded, credential-free metadata and reachability. Results and errors include the resolved target.

`list_targets` reports configured target name/kind, sanitized endpoint identity, reachability, and node names. It never discovers arbitrary hosts, mutates configuration, or emits credentials, raw response bodies, or full authenticated URLs.

## Isolation and jobs

Create one `ProxmoxManager` per target. Tool dispatch resolves a target to its manager; no manager or credential state is shared across targets. Job records persist the originating target and all job operations use it, never the current default.

Per-target read-only policy rejects mutation and command execution before contacting Proxmox. Existing command-policy/high-risk checks remain active.

## Testing and acceptance

Add public-interface tests for legacy loading, one-target defaulting, multi-target required selection, invalid targets, target discovery, unreachable targets, target-aware results/errors/jobs, independent credentials/managers, read-only rejection, and secret redaction. Preserve the existing single-target suite.

Live acceptance requires authenticated read-only `get_nodes` against both `cluster` (returning pve1/pve2/pve3) and `pl`, plus concurrency and restart verification. The old service remains available for rollback until the new implementation passes.

For an externally managed SSH port forward, set `api_tunnel.enabled` to `true` and `api_tunnel.assume_external` to `true`; the configured local endpoint is then reused without starting or stopping a tunnel process. This is an explicit operator opt-in because the endpoint's remote identity cannot be verified by this process. Without `assume_external`, the local port must be free or owned by this process.
