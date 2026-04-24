# Troubleshooting

Use this page to diagnose and recover from common failures.

## Startup Fails Before The Server Registers Tools

Check:

- `PROXMOX_MCP_CONFIG` points to a real JSON file
- required config values are present
- Python dependencies are installed
- the JSON file is valid

Common causes:

- missing `proxmox.host`
- missing auth fields
- invalid JSON syntax
- `verify_ssl=false` while `security.dev_mode=false`

## Real E2E Refuses To Start

`test_scripts/run_real_e2e.py` is intentionally stricter than normal runtime startup.

Check:

- `proxmox-config/config.live.json` exists for live testing, or `PROXMOX_MCP_E2E_CONFIG` points to one
- the live config uses a reachable Proxmox API host, not a placeholder `127.0.0.1`
- if you rely on a tunnel, that tunnel is already up or explicitly configured

The script now refuses to treat the default `proxmox-config/config.json` as a live target when it still points at a local-only API address.

## `/health` Returns `degraded`

This usually means the OpenAPI wrapper started but did not connect to the MCP subprocess yet.

Check:

- the command passed after `--` actually launches the MCP server
- the subprocess has access to `PYTHONPATH` and the config file
- stderr output from `main.py` for startup errors

If the payload shows `"jobs": {"enabled": false}`, the OpenAPI wrapper started without a local `JobStore`. In that case `/jobs` routes return `503` even if MCP tool calls still work.

## OpenAPI `/docs` Works But Tool Calls Fail

Check:

- the wrapped MCP server is starting successfully
- Proxmox auth values are correct
- the OpenAPI layer is pointing at the intended config file
- the underlying tool is actually registered in `server.py`

If only `/jobs` fails:

- confirm `PROXMOX_MCP_CONFIG` is available to the OpenAPI process
- confirm the configured `jobs.sqlite_path` is writable
- check startup logs for `JobStore initialization skipped in OpenAPI proxy`

## Job History Disappears After Restart

Check:

- `jobs.sqlite_path` points at a persistent location
- the service account can create and write that SQLite file
- your container or process supervisor is not mounting the path on ephemeral storage

On Docker or Compose, mount the directory containing `jobs.sqlite_path` to a durable host path.

## `retry_job` Returns Conflict

This means the job exists but there is no stored retry recipe or the retry handler is unavailable in the current process.

Check:

- the job was created by a built-in long-running tool, not a custom ad hoc record
- the server version still includes the retry handler for that tool family
- the persisted `retry_spec` in the job record is not null

## `cancel_job` Returns Conflict

This usually means the job has no active Proxmox `UPID` to cancel.

Common causes:

- the job completed before you tried to cancel it
- the job record was created without a cancellable Proxmox task
- the backend task ID was never available

## `execute_container_command` Is Missing

This is expected when the config has no `ssh` section.

If you expected the tool to exist:

- add the `ssh` section to the config
- restart the server
- verify the SSH user, key, host mapping, and `use_sudo` settings

## VM Command Execution Fails

`execute_vm_command` depends on QEMU Guest Agent.

Check:

- the VM is running
- the guest agent is installed
- the guest agent service is running in the VM
- the command policy is not blocking the requested command

## Container Command Execution Fails

Check:

- the target container is running
- SSH works from the MCP host to the correct Proxmox node
- the SSH key is valid
- the sudo rule for `pct exec` exists if `use_sudo=true`
- command policy is not blocking the command

Also see [Container Command Execution Guide](https://github.com/RekklesNA/ProxmoxMCP-Plus/blob/main/docs/container-command-execution.md).

## Tool Is Registered But Returns Empty Results

Possible causes:

- Proxmox API token lacks permissions for the target resource
- node or storage filters are too narrow
- the cluster contains offline nodes and only healthy nodes are being returned
- there are genuinely no matching VMs, containers, ISO files, or backups

## TLS Errors Against Proxmox API

Check:

- certificate trust on the machine running the service
- the hostname in config matches the certificate
- `verify_ssl` is not disabled unless you are explicitly in development mode

## Config Works In One Client But Not Another

Check:

- environment variables are available in that client's runtime
- the client starts the same Python interpreter and project path
- `PYTHONPATH` is set when running from source

## Useful First Checks

Start with:

1. validate the config path
2. run a read-only tool such as `get_nodes`
3. confirm `/health` in OpenAPI mode
4. inspect logs or stderr
5. verify whether the missing behavior is transport-specific or affects both MCP and OpenAPI

## What To Capture When Reporting A Problem

- exact command or tool name
- config mode used: MCP stdio or OpenAPI
- relevant log lines or stderr output
- whether the issue affects one node, one VM/container, or the whole cluster
- whether the same call works directly in Proxmox
