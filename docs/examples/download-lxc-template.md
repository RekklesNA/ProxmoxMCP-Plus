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
  "checksum_algorithm": "sha256"
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
- Background job tracking, cancellation and retry follow the existing storage download contract.
- Target storage must support LXC template content and have sufficient space.
