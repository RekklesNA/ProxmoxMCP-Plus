# Download an LXC template

Use `download_template` to download an LXC OS template to a specific Proxmox node using its REST API. This does not require SSH.

## Example

1. Find storage on the destination node that supports `vztmpl` (normally `local`, not `local-lvm`).
2. Obtain the template's actual HTTPS download URL from a trusted distributor and optionally its SHA-256 digest.
3. Call:

```json
{
  "node": "six",
  "storage": "local",
  "url": "https://example.org/templates/debian-13-standard.tar.zst",
  "filename": "debian-13-standard.tar.zst",
  "checksum": null,
  "checksum_algorithm": "sha256",
  "approval_token": "<token-if-required-by-target-policy>"
}
```

4. Poll the returned `job_id` using `poll_job` until the task completes successfully.
5. Verify the archive using `list_templates(node="six", storage="local")`.
6. Supply the returned volume ID (`local:vztmpl/...`) to `create_container`.

The URL above is illustrative, not an actual template download source. For production use, verify the publisher and checksum. Successful submission only means the download task started; it does not mean the archive is present.

## Behavior

- Downloads use the Proxmox `/nodes/{node}/storage/{storage}/download-url` API with `content=vztmpl`.
- Only `.tar.gz`, `.tar.xz`, or `.tar.zst` filenames are accepted. Paths are rejected.
- The download URL must use HTTPS without embedded credentials.
- Background job tracking retains the UPID; cancellation uses the native task DELETE endpoint. No automatic or `retry_job` resubmission is supported. An uncertain POST requires inspection before another call.
- The tool requires observed active/enabled `vztmpl` storage and rejects an already listed destination filename. These reads do not reserve space/name or exclude concurrent uploads; Proxmox reports storage exhaustion asynchronously.
- The Proxmox token must be able to read storage/template inventory and invoke the native download endpoint, including its storage/network permissions.
- The target high-risk/read-only/client policy applies. Add `download_template` to custom high-risk operation lists. Default audit-only mode does not require approval.
- HTTPS does not prevent server-side access to internal addresses or redirects. Restrict callers and choose trusted publishers.
- A successful submission includes `task_id` and optional `job_id`; local tracking failure preserves the task ID.

API source: [native download-url implementation](https://github.com/proxmox/pve-storage/blob/75b36a49f57fa7119a45bb69118c8c6eb58102d7/src/PVE/API2/Storage/Status.pm#L739).
