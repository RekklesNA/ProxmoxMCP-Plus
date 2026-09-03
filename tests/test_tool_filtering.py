"""Tests for opt-in MCP tool exposure filtering."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from proxmox_mcp.config.loader import load_config
from proxmox_mcp.server import ProxmoxMCPServer
from proxmox_mcp.services.tool_catalog import BUILTIN_TOOL_NAMES
from proxmox_mcp.services.tool_registry import ToolExposurePolicy, ToolRegistry

ROOT = Path(__file__).resolve().parent.parent
SSH_ONLY_TOOLS = {"execute_container_command", "update_container_ssh_keys"}


@pytest.fixture(autouse=True)
def clean_tool_filter_env(monkeypatch):
    monkeypatch.delenv("MCP_TOOL_ALLOWLIST", raising=False)
    monkeypatch.delenv("MCP_TOOL_DENYLIST", raising=False)


def _write_config(
    tmp_path: Path, *, mcp: dict | None = None, ssh: dict | None = None
) -> Path:
    config: dict[str, object] = {
        "proxmox": {
            "host": "test.proxmox.local",
            "port": 8006,
            "verify_ssl": True,
            "service": "PVE",
        },
        "auth": {
            "user": "test@pve",
            "token_name": "test-token",
            "token_value": "test-secret",
        },
        "logging": {"level": "INFO"},
        "jobs": {"sqlite_path": str(tmp_path / "jobs.sqlite3")},
    }
    if mcp is not None:
        config["mcp"] = mcp
    if ssh is not None:
        config["ssh"] = ssh

    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def _create_server(config_path: Path) -> ProxmoxMCPServer:
    with patch("proxmox_mcp.core.proxmox.ProxmoxAPI"):
        return ProxmoxMCPServer(str(config_path))


async def _tool_names(server: ProxmoxMCPServer) -> set[str]:
    return {tool.name for tool in await server.mcp.list_tools()}


@pytest.mark.asyncio
async def test_unconfigured_registry_preserves_extension_tools():
    mcp = FastMCP("extension-test")
    registry = ToolRegistry(
        mcp,
        ToolExposurePolicy(known_tools=BUILTIN_TOOL_NAMES),
    )

    @registry.tool()
    def extension_tool() -> str:
        return "ok"

    assert {tool.name for tool in await mcp.list_tools()} == {"extension_tool"}


@pytest.mark.asyncio
async def test_unconfigured_filter_preserves_default_tool_surface(tmp_path):
    server = _create_server(_write_config(tmp_path))
    try:
        assert server.config.mcp.tool_allowlist is None
        assert server.config.mcp.tool_denylist is None
        assert server.tool_exposure_policy.mode == "all"
        assert await _tool_names(server) == BUILTIN_TOOL_NAMES - SSH_ONLY_TOOLS
    finally:
        server.close()


@pytest.mark.asyncio
async def test_file_allowlist_registers_only_requested_tools(tmp_path):
    config_path = _write_config(
        tmp_path,
        mcp={"tool_allowlist": [" get_nodes ", "get_vms", "get_nodes"]},
    )
    server = _create_server(config_path)
    try:
        assert server.config.mcp.tool_allowlist == ["get_nodes", "get_vms"]
        assert await _tool_names(server) == {"get_nodes", "get_vms"}
        with pytest.raises(ToolError, match="Unknown tool"):
            await server.mcp.call_tool("delete_vm", {})
    finally:
        server.close()


@pytest.mark.asyncio
async def test_file_denylist_excludes_only_requested_tools(tmp_path):
    config_path = _write_config(
        tmp_path,
        mcp={"tool_denylist": ["create_vm", "delete_vm"]},
    )
    server = _create_server(config_path)
    try:
        tool_names = await _tool_names(server)
        assert "create_vm" not in tool_names
        assert "delete_vm" not in tool_names
        assert tool_names == BUILTIN_TOOL_NAMES - SSH_ONLY_TOOLS - {
            "create_vm",
            "delete_vm",
        }
    finally:
        server.close()


@pytest.mark.asyncio
async def test_environment_filter_replaces_file_filter_mode(tmp_path, monkeypatch):
    config_path = _write_config(
        tmp_path,
        mcp={"tool_denylist": ["get_vms"]},
    )
    monkeypatch.setenv("MCP_TOOL_ALLOWLIST", " get_vms, get_nodes, get_vms ")

    server = _create_server(config_path)
    try:
        assert server.config.mcp.tool_allowlist == ["get_vms", "get_nodes"]
        assert server.config.mcp.tool_denylist is None
        assert await _tool_names(server) == {"get_nodes", "get_vms"}
    finally:
        server.close()


def test_file_allowlist_and_denylist_are_mutually_exclusive(tmp_path):
    config_path = _write_config(
        tmp_path,
        mcp={"tool_allowlist": ["get_nodes"], "tool_denylist": ["delete_vm"]},
    )

    with pytest.raises(ValueError, match="mutually exclusive"):
        load_config(str(config_path))


def test_environment_allowlist_and_denylist_are_mutually_exclusive(
    tmp_path, monkeypatch
):
    config_path = _write_config(tmp_path)
    monkeypatch.setenv("MCP_TOOL_ALLOWLIST", "get_nodes")
    monkeypatch.setenv("MCP_TOOL_DENYLIST", "delete_vm")

    with pytest.raises(ValueError, match="mutually exclusive"):
        load_config(str(config_path))


@pytest.mark.asyncio
async def test_empty_allowlist_exposes_no_tools(tmp_path):
    server = _create_server(_write_config(tmp_path, mcp={"tool_allowlist": []}))
    try:
        assert server.config.mcp.tool_allowlist == []
        assert await _tool_names(server) == set()
    finally:
        server.close()


def test_unknown_tool_name_fails_server_initialization(tmp_path):
    config_path = _write_config(
        tmp_path,
        mcp={"tool_denylist": ["delete_vn"]},
    )

    with pytest.raises(ValueError, match=r"Unknown MCP tool name\(s\): delete_vn"):
        _create_server(config_path)


def test_malformed_tool_name_fails_config_validation(tmp_path):
    config_path = _write_config(
        tmp_path,
        mcp={"tool_allowlist": ["GET_NODES"]},
    )

    with pytest.raises(ValueError, match="exact lowercase tool names"):
        load_config(str(config_path))


@pytest.mark.asyncio
async def test_allowlisted_ssh_tool_remains_unavailable_without_ssh_config(
    tmp_path, caplog
):
    server = _create_server(
        _write_config(
            tmp_path,
            mcp={"tool_allowlist": ["execute_container_command"]},
        )
    )
    try:
        assert await _tool_names(server) == set()
        assert server.tool_registry.requested_but_unavailable == {
            "execute_container_command"
        }
        assert "unavailable under the current capability config" in caplog.text
    finally:
        server.close()


@pytest.mark.asyncio
async def test_stdio_protocol_lists_only_allowlisted_tools(tmp_path):
    env = dict(os.environ)
    env.pop("PROXMOX_MCP_CONFIG", None)
    env.pop("MCP_TOOL_DENYLIST", None)
    env.update(
        {
            "PROXMOX_HOST": "test.proxmox.local",
            "PROXMOX_USER": "test@pve",
            "PROXMOX_TOKEN_NAME": "test-token",
            "PROXMOX_TOKEN_VALUE": "test-secret",
            "PROXMOX_VERIFY_SSL": "true",
            "PROXMOX_JOBS_SQLITE_PATH": str(tmp_path / "stdio-jobs.sqlite3"),
            "MCP_TRANSPORT": "STDIO",
            "MCP_TOOL_ALLOWLIST": "get_nodes,get_vms",
            "LOG_LEVEL": "WARNING",
        }
    )
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "proxmox_mcp.server"],
        env=env,
        cwd=ROOT,
    )

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.list_tools()

    assert {tool.name for tool in result.tools} == {"get_nodes", "get_vms"}
