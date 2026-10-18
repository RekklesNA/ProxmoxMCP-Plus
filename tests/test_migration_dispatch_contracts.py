"""Exercise actual FastMCP policy, target routing and migration dispatch."""

import json
from unittest.mock import patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from proxmox_mcp.server import ProxmoxMCPServer
from test_migrate_container_tool import migration_api


def make_server(tmp_path, *, readonly=False, client_tools=None):
    apis = {name: migration_api() for name in ("chosen", "other")}
    policy = {
        "high_risk_mode": "enforce", "high_risk_require_approval_token": True,
        "high_risk_approval_token": "test-approval",
    }
    targets = {
        name: {
            "host": name, "readonly": readonly, "command_policy": policy,
            "auth": {"user": "test@pve", "token_name": "test", "token_value": "test-value"},
        }
        for name in apis
    }
    config = {"targets": targets, "jobs": {"sqlite_path": str(tmp_path / "jobs.sqlite3")}}
    if client_tools is not None:
        config["mcp"] = {"client_permissions": {"_local": {"targets": ["chosen"], "tools": client_tools}}}
    path = tmp_path / "test-config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with patch("proxmox_mcp.core.proxmox.ProxmoxAPI", side_effect=lambda **kwargs: apis[kwargs["host"]]):
        server = ProxmoxMCPServer(str(path))
    return server, apis


@pytest.mark.asyncio
async def test_migration_requires_policy_token_before_any_guest_read(tmp_path):
    server, apis = make_server(tmp_path)
    try:
        with pytest.raises(ToolError, match="approval token"):
            await server.mcp.call_tool("migrate_container", {
                "target": "chosen", "node": "sam", "vmid": "115", "destination": "six",
                "confirm_migration": True,
            })
        for api in apis.values():
            api.nodes.assert_not_called()
    finally:
        server.close()


@pytest.mark.asyncio
async def test_approved_migration_submits_once_to_selected_target(tmp_path):
    server, apis = make_server(tmp_path)
    try:
        await server.mcp.call_tool("migrate_container", {
            "target": "chosen", "node": "sam", "vmid": "115", "destination": "six",
            "confirm_migration": True, "approval_token": "test-approval",
        })
        apis["chosen"].nodes.return_value.lxc.return_value.migrate.post.assert_called_once_with(target="six", restart=0)
        apis["other"].nodes.assert_not_called()
        tools = {tool.name: tool for tool in await server.mcp.list_tools()}
        assert "with_local_disks" not in tools["migrate_container"].inputSchema["properties"]
    finally:
        server.close()


@pytest.mark.asyncio
async def test_readonly_target_blocks_migration_but_allows_preflight(tmp_path):
    server, apis = make_server(tmp_path, readonly=True)
    try:
        with pytest.raises(ToolError, match="read-only"):
            await server.mcp.call_tool("migrate_container", {
                "target": "chosen", "node": "sam", "vmid": "115", "destination": "six",
                "confirm_migration": True, "approval_token": "test-approval",
            })
        apis["chosen"].nodes.assert_not_called()
        await server.mcp.call_tool("preflight_container_migration", {
            "target": "chosen", "node": "sam", "vmid": "115", "destination": "six",
        })
        apis["chosen"].nodes.return_value.lxc.return_value.migrate.post.assert_not_called()
        apis["other"].nodes.assert_not_called()
    finally:
        server.close()


@pytest.mark.asyncio
async def test_client_tool_grant_blocks_migration_even_with_approval(tmp_path):
    server, apis = make_server(tmp_path, client_tools=["preflight_container_migration"])
    try:
        with pytest.raises(ToolError, match="not authorized"):
            await server.mcp.call_tool("migrate_container", {
                "target": "chosen", "node": "sam", "vmid": "115", "destination": "six",
                "confirm_migration": True, "approval_token": "test-approval",
            })
        for api in apis.values():
            api.nodes.assert_not_called()
    finally:
        server.close()
