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

## `/health` Returns `degraded`

This usually means the OpenAPI wrapper started but did not connect to the MCP subprocess yet.

Check:

- the command passed after `--` actually launches the MCP server
- the subprocess has access to `PYTHONPATH` and the config file
- stderr output from `main.py` for startup errors

## OpenAPI `/docs` Works But Tool Calls Fail

Check:

- the wrapped MCP server is starting successfully
- Proxmox auth values are correct
- the OpenAPI layer is pointing at the intended config file
- the underlying tool is actually registered in `server.py`

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
