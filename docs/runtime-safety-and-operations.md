# Runtime safety and operations

Native SSE and Streamable HTTP startup requires `MCP_API_KEY` by default.
`MCP_ALLOW_UNAUTHENTICATED_HTTP=true` explicitly delegates authentication to an
external access control layer. OAuth uses PostgreSQL and accepts the API key only
on the consent page. Keep the legacy OAuth metadata table during rolling upgrades
and rollback windows; this runtime leaves its schema and values untouched.

## Authorization

The shared dispatch path checks current tool exposure, target access, target
read-only status, command policy and high-risk operation policy. These checks also
apply when retrying or reconciling the original operation behind a job.
`command_policy.mode` controls guest commands; `require_approval_token` controls
their additional approval requirement. `high_risk_mode=enforce` activates operation
restrictions, and `high_risk_require_approval_token` requires the configured
high-risk token. The default high-risk mode remains `audit_only` for compatibility.
Set both modes explicitly for remote production deployments.

Approval tokens can be passed as MCP arguments. For direct OpenAPI job control,
prefer the `X-Approval-Token` header; reconciliation also accepts a JSON body. Legacy
retry query parameters remain supported but may enter proxy access logs.

Optional grants live in `mcp.client_permissions`:

```json
{
  "mcp": {
    "client_permissions": {
      "oauth-client-id": {"tools": ["get_nodes", "get_vms"], "targets": ["lab"]},
      "_local": {"tools": ["*"], "targets": ["lab"]},
      "_shared_key": {"tools": ["get_nodes"], "targets": ["lab"]}
    }
  }
}
```

With no grants configured, existing authorization behavior is preserved. Once
grants are configured, principals without a grant are denied; `*` explicitly
grants all tools or targets. OAuth uses the registered client ID, STDIO uses
`_local`, and native shared-key HTTP uses `_shared_key`. Direct OpenAPI job routes
use `_api_key` or `_anonymous`. The OpenAPI bridge runs a STDIO child under `_local`;
it does not forward individual callers' OAuth identity. Use separate instances
and restricted child grants when distinct users require distinct bridge rights.
These are client grants, not a claim of end-user identity verification.

Command allowlist patterns match the entire command. Use anchored expressions,
escape regex whitespace as `\\s` in JSON, and consider shell metacharacters and
program-specific options. A regex allowlist cannot provide a general shell sandbox.
VM command tools accept `guest_os="posix"` (default) or `"windows"` and send explicit
shell argv independently of the server operating system.

## Asynchronous tasks and recovery

Task-producing operations return structured `status="submitted"`, `task_id` and
`job_id` alongside the existing readable response. Submission does not establish
completion; use `poll_job` and inspect the terminal status. Forced guest deletion
waits for the stop task to finish successfully before submitting deletion.
Incremental container resize tasks are tracked but cannot be automatically retried.

Job lists return summaries. `poll_job(include_audit=false)` avoids loading historical
audit rows and returns only events added during that poll. For direct OpenAPI
clients, retrieve history with `GET /jobs/{job_id}/audit?after_id=0&limit=100`;
advance `after_id` using the last event ID. The default poll retains complete history
for compatibility. `get_job` also retains history.

SQLite retry claims use transactions and a bounded lease. Expired claims, interrupted
submissions, connection failures and timeouts enter `needs_reconciliation` rather
than automatically repeating an uncertain mutation. Inspect the Proxmox task
history before calling `reconcile_job`: attach a verified UPID on the original node,
or explicitly confirm no task was submitted. A concurrent state change is preserved
and the discarded submission UPID remains in the audit log.

Configure `jobs.audit_retention_days` to bound audit retention; the default preserves
all history. The in-memory job cache is capped at 500 entries. Recipes containing
secrets are redacted on disk and can be retried only while their original in-process
callback is retained. Restart or cache eviction requires a new explicitly authorized
operation. Docker Compose persists SQLite in the `proxmox-jobs` volume at `/app/data`;
`PROXMOX_JOBS_SQLITE_PATH` can override file configuration too.

## Capacity and health

`mcp.worker_limit` bounds concurrent calls per target (default 8, range 1–128), with
queue latency recorded separately. Blocking Proxmox and SSH work runs outside the
event loop. Calls sharing a Requests session are serialized for connection safety.
Container statistics use bounded prefetch, coalesced duplicate requests and a short
cache. OAuth performs indexed, bounded expiry cleanup every five minutes.
SSH stdout and stderr are each capped at 1 MiB and report truncation and timeout.
Strict host-key checking is honored by OpenSSH; Paramiko rejects unknown keys.
Owned tunnel processes drain bounded stderr, use keepalives and retry with backoff.

`/livez` checks process liveness; `/readyz` checks service readiness. `list_targets`
performs a cached, non-destructive reachability probe for each authorized target.
Neither process liveness nor cached reachability proves every guest operation works.

Automatic storage selection checks node inventory, content capability, active/enabled
status and known available capacity. Unknown capacity is left for Proxmox to enforce.
Cloud-init disks are supported on eligible image storage, including LVM.
Partial inventories carry completeness warnings and cannot authorize destructive
resource selection. Deletion checks a fresh inventory, exact volume identity, content
type and backup protection before sending a request.

Code Mode worker reuse remains opt-in through `MCP_CODE_MODE_POOL_REUSE=true`.
It reduces worker startup overhead while preserving a fresh sandbox session per
request. Measure actual workload latency and capacity before enabling it.

Runtime dependencies are pinned with hashes in `requirements/runtime.lock`.
CI publishes coverage, resolved dependency evidence and a CycloneDX SBOM. Container
publication includes provenance and SBOM attestations. Release verification includes
the built package, PyPI, MCP Registry and native ARM64 container health.
