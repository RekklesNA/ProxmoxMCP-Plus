"""MCP tool annotations advertised for every built-in tool."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from proxmox_mcp.server import ProxmoxMCPServer
from proxmox_mcp.services.tool_catalog import BUILTIN_TOOL_ANNOTATIONS, BUILTIN_TOOL_NAMES
from proxmox_mcp.services.tool_wrappers import _READ_ONLY_TOOLS


def _create_server(tmp_path: Path) -> ProxmoxMCPServer:
    config = {
        "proxmox": {"host": "test.proxmox.local", "port": 8006, "verify_ssl": True, "service": "PVE"},
        "auth": {"user": "test@pve", "token_name": "test-token", "token_value": "test-secret"},
        "logging": {"level": "INFO"},
        "jobs": {"sqlite_path": str(tmp_path / "jobs.sqlite3")},
        "ssh": {"user": "root", "allow_node_commands": True},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with patch("proxmox_mcp.core.proxmox.ProxmoxAPI"):
        return ProxmoxMCPServer(str(path))


def test_every_builtin_tool_has_annotations():
    assert set(BUILTIN_TOOL_ANNOTATIONS) == BUILTIN_TOOL_NAMES


def test_read_only_hints_match_read_only_target_policy():
    read_only = {name for name, value in BUILTIN_TOOL_ANNOTATIONS.items() if value.readOnlyHint}
    assert read_only == _READ_ONLY_TOOLS | {"list_targets"}


def test_mutating_tools_declare_destructive_hint():
    for name, value in BUILTIN_TOOL_ANNOTATIONS.items():
        assert value.readOnlyHint is not None, name
        assert value.openWorldHint is not None, name
        if not value.readOnlyHint:
            assert value.destructiveHint is not None, name
            assert value.idempotentHint is not None, name


@pytest.mark.asyncio
async def test_registered_tools_advertise_annotations(tmp_path):
    server = _create_server(tmp_path)
    tools = await server.mcp.list_tools()

    assert {tool.name for tool in tools} == BUILTIN_TOOL_NAMES
    for tool in tools:
        assert tool.annotations is not None, tool.name
        assert tool.annotations == BUILTIN_TOOL_ANNOTATIONS[tool.name], tool.name
        assert tool.annotations.readOnlyHint is not None, tool.name
