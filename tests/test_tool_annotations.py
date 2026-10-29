"""MCP tool annotations advertised for every built-in tool."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, call, patch

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from proxmox_mcp.server import ProxmoxMCPServer
from proxmox_mcp.services.tool_catalog import BUILTIN_TOOL_ANNOTATIONS, BUILTIN_TOOL_NAMES
from proxmox_mcp.services.tool_wrappers import _READ_ONLY_TOOLS
from proxmox_mcp.services.tool_registry import ToolRegistry
from proxmox_mcp.tools.backup import BackupTools
from proxmox_mcp.tools.containers import ContainerTools


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
    try:
        tools = await server.mcp.list_tools()
        assert {tool.name for tool in tools} == BUILTIN_TOOL_NAMES
        for tool in tools:
            assert tool.annotations is not None, tool.name
            assert tool.annotations == BUILTIN_TOOL_ANNOTATIONS[tool.name], tool.name
            assert tool.annotations.readOnlyHint is not None, tool.name
    finally:
        server.close()


def test_repeated_disk_growth_is_not_advertised_as_idempotent():
    api = Mock()
    api.nodes.return_value.lxc.return_value.resize.put.return_value = "UPID:pve:resize"
    tools = ContainerTools(api)
    with patch.object(tools, "_resolve_targets", return_value=[("pve", "101", "web")]):
        for _ in range(2):
            result = tools.update_container_resources("pve:101", disk_gb=5, format_style="json")
            assert json.loads(result[0].text)[0]["ok"] is True
    assert api.nodes.return_value.lxc.return_value.resize.put.call_args_list == [
        call(disk="rootfs", size="+5G"), call(disk="rootfs", size="+5G")]
    assert BUILTIN_TOOL_ANNOTATIONS["update_container_resources"].idempotentHint is False


@pytest.mark.parametrize("mode", ["stop", "suspend"])
def test_interrupting_backup_modes_are_advertised_as_destructive(mode):
    api = Mock()
    BackupTools(api).create_backup("pve", "101", "local", mode=mode)
    assert api.nodes.return_value.vzdump.post.call_args.kwargs["mode"] == mode
    assert BUILTIN_TOOL_ANNOTATIONS["create_backup"].destructiveHint is True


@pytest.mark.asyncio
async def test_explicit_annotations_override_builtin_defaults_and_extensions_stay_unknown():
    mcp = FastMCP("annotation-override-test")
    registry = ToolRegistry(mcp)
    override = ToolAnnotations(readOnlyHint=False, destructiveHint=True)

    @registry.tool(name="get_nodes", annotations=override)
    def renamed() -> str:
        return "ok"

    @registry.tool()
    def custom_extension() -> str:
        return "ok"

    tools = {tool.name: tool for tool in await mcp.list_tools()}
    assert tools["get_nodes"].annotations == override
    assert tools["custom_extension"].annotations is None


@pytest.mark.asyncio
async def test_explicit_name_uses_catalog_annotations():
    mcp = FastMCP("annotation-name-test")
    registry = ToolRegistry(mcp)

    @registry.tool(name="delete_vm")
    def renamed() -> str:
        return "ok"

    assert (await mcp.list_tools())[0].annotations == BUILTIN_TOOL_ANNOTATIONS["delete_vm"]


@pytest.mark.asyncio
async def test_code_mode_discovery_and_execution_advertise_different_risks(tmp_path):
    from proxmox_mcp.code_mode import install_code_mode

    server = _create_server(tmp_path)
    try:
        install_code_mode(server)
        tools = {tool.name: tool for tool in await server.mcp.list_tools()}
        assert set(tools) == {"proxmox_code_search", "proxmox_code_get_schema", "proxmox_code_execute"}
        for name in ("proxmox_code_search", "proxmox_code_get_schema"):
            assert tools[name].annotations.readOnlyHint is True
            assert tools[name].annotations.openWorldHint is False
        assert tools["proxmox_code_execute"].annotations == ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True)
    finally:
        server.close()
