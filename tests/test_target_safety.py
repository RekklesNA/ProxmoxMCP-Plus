import json

from unittest.mock import patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from proxmox_mcp.server import ProxmoxMCPServer


def _readonly_config(path):
    path.write_text(json.dumps({
        "targets": {
            "safe": {
                "host": "safe.example",
                "port": 8006,
                "readonly": True,
                "auth": {"user": "safe@pve", "token_name": "token", "token_value": "secret-value"},
            },
        },
        "jobs": {"sqlite_path": str(path.with_suffix(".sqlite3"))},
    }))


@pytest.mark.asyncio
async def test_readonly_target_rejects_mutation_before_api_call(tmp_path):
    config_path = tmp_path / "readonly.json"
    _readonly_config(config_path)
    with patch("proxmox_mcp.core.proxmox.ProxmoxAPI") as proxmox_api:
        server = ProxmoxMCPServer(str(config_path))
        try:
            with pytest.raises(ToolError, match="read-only"):
                await server.mcp.call_tool(
                    "start_vm", {"target": "safe", "node": "pve1", "vmid": "100"}
                )
            proxmox_api.return_value.nodes.assert_not_called()
        finally:
            server.close()


def test_named_target_without_ssh_does_not_inherit_global_ssh(tmp_path):
    config_path = tmp_path / "global-ssh.json"
    config_path.write_text(json.dumps({
        "targets": {
            "without-ssh": {
                "host": "a.example",
                "auth": {"user": "u", "token_name": "t", "token_value": "v"},
            },
            "with-ssh": {
                "host": "b.example",
                "auth": {"user": "u", "token_name": "t", "token_value": "v"},
                "ssh": {"user": "target-user", "key_file": str(tmp_path / "target-key")},
            },
        },
        "ssh": {"user": "legacy-global", "key_file": str(tmp_path / "global-key")},
        "jobs": {"sqlite_path": str(tmp_path / "jobs.sqlite3")},
    }))
    with patch("proxmox_mcp.core.proxmox.ProxmoxAPI"):
        server = ProxmoxMCPServer(str(config_path))
        try:
            assert server.target_tools("without-ssh").container_tools.console_manager is None
            assert server.target_tools("with-ssh").container_tools.console_manager is not None
        finally:
            server.close()
