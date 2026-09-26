"""Regression coverage for responsive SSH tools and bridge discovery."""
import asyncio
import json
import threading
from unittest.mock import Mock, patch

import pytest
from mcp.types import CallToolRequest, ListToolsRequest

from proxmox_mcp.server import ProxmoxMCPServer


@pytest.fixture
def instance(tmp_path):
    config = {
        "targets": {
            name: {"host": name, "auth": {"user": "u", "token_name": "t", "token_value": "v"},
                   "readonly": name == "readonly", "ssh": {"user": "root"}}
            for name in ("first", "second", "readonly")
        },
        "command_policy": {"mode": "audit_only"},
        "jobs": {"sqlite_path": str(tmp_path / "jobs.sqlite3")},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    apis = {name: Mock() for name in config["targets"]}
    with patch("proxmox_mcp.core.proxmox.ProxmoxAPI", side_effect=lambda **kw: apis[kw["host"]]):
        server = ProxmoxMCPServer(str(path))
    yield server, apis
    server.close()


async def call(server, name, args):
    handler = server.mcp._mcp_server.request_handlers[CallToolRequest]
    return (await handler(CallToolRequest(method="tools/call", params={"name": name, "arguments": args}))).root


@pytest.mark.asyncio
async def test_slow_console_does_not_block_mcp(instance):
    server, apis = instance
    entered, release = threading.Event(), threading.Event()
    worker_finished = threading.Event()

    def slow(*args, **kwargs):
        entered.set()
        release.wait(2)  # bounded fail-safe so the old implementation cannot hang pytest
        worker_finished.set()
        return {"success": False, "code": "COMMAND_TIMEOUT", "error": "timeout"}

    tools = server.target_tools("second").container_tools
    tools._resolve_targets = Mock(return_value=[("pve", 101, "ct")])
    tools.console_manager.execute_command = Mock(side_effect=slow)
    apis["first"].nodes.get.return_value = []
    pending = asyncio.create_task(call(server, "execute_container_command", {
        "target": "second", "selector": "101", "command": "sleep 120"}))
    try:
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert entered.is_set()
        handler = server.mcp._mcp_server.request_handlers[ListToolsRequest]
        listed = await asyncio.wait_for(handler(ListToolsRequest(method="tools/list")), 0.5)
        assert listed.root.tools
        result = await asyncio.wait_for(call(server, "get_nodes", {"target": "first"}), 0.5)
        assert not result.isError
        assert not worker_finished.is_set(), "SSH call blocked the MCP event loop"
    finally:
        release.set()
        result = await pending
    assert "COMMAND_TIMEOUT" in result.content[0].text
    assert not (await call(server, "get_nodes", {"target": "first"})).isError


@pytest.mark.asyncio
async def test_bridges_selected_readonly_target_and_errors(instance):
    server, apis = instance
    bridges = [{"iface": "vmbr0", "type": "bridge", "active": 1},
               {"iface": "ovsbr0", "type": "OVSBridge"},
               {"iface": "vnet1", "type": "vnet"}]
    apis["readonly"].nodes.return_value.network.get.return_value = bridges
    result = await call(server, "list_bridges", {"node": "pve", "target": "readonly"})
    assert not result.isError
    assert json.loads(result.content[0].text) == bridges
    apis["readonly"].nodes.return_value.network.get.assert_called_once_with(type="any_bridge")
    apis["first"].nodes.assert_not_called()
    apis["readonly"].nodes.return_value.network.get.side_effect = PermissionError("403 denied")
    assert (await call(server, "list_bridges", {"node": "pve", "target": "readonly"})).isError
    assert (await call(server, "list_bridges", {"node": "pve"})).isError


@pytest.mark.asyncio
async def test_console_readonly_policy_prevents_dispatch(instance):
    server, _ = instance
    manager = server.target_tools("readonly").container_tools.console_manager
    manager.execute_command = Mock()
    result = await call(server, "execute_container_command", {
        "selector": "101", "command": "echo test", "target": "readonly"})
    assert result.isError
    manager.execute_command.assert_not_called()


@pytest.mark.asyncio
async def test_console_command_policy_still_blocks_in_worker(instance):
    server, _ = instance
    tools = server.target_tools("second").container_tools
    tools.command_policy.evaluate = Mock(return_value=Mock(allowed=False, code="POLICY_DENIED", message="denied"))
    tools.console_manager.execute_command = Mock()
    result = await call(server, "execute_container_command", {
        "selector": "101", "command": "echo test", "target": "second", "approval_token": "test-token"})
    assert "POLICY_DENIED" in result.content[0].text
    tools.command_policy.evaluate.assert_called_once_with("echo test", approval_token="test-token")
    tools.console_manager.execute_command.assert_not_called()


@pytest.mark.asyncio
async def test_slow_console_over_real_stdio(tmp_path):
    """A real client can list/call tools while the child server is executing SSH."""
    import os
    import sys
    from pathlib import Path
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    config = tmp_path / "stdio-config.json"
    config.write_text(json.dumps({
        "proxmox": {"host": "pve"},
        "auth": {"user": "u", "token_name": "t", "token_value": "v"},
        "ssh": {"user": "root"},
        "command_policy": {"mode": "audit_only"},
        "jobs": {"sqlite_path": str(tmp_path / "stdio.sqlite3")},
    }))
    script = tmp_path / "server.py"
    script.write_text('''
import sys, time
from pathlib import Path
from unittest.mock import Mock, patch
from proxmox_mcp.server import ProxmoxMCPServer
root = Path(sys.argv[1])
with patch("proxmox_mcp.core.proxmox.ProxmoxAPI") as factory:
    factory.return_value.nodes.get.return_value = []
    server = ProxmoxMCPServer(str(root / "stdio-config.json"))
tools = server.target_tools(None).container_tools
tools._resolve_targets = Mock(return_value=[("pve", 101, "ct")])
def slow(*args):
    (root / "entered").touch()
    deadline = time.monotonic() + 10
    while not (root / "release").exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    return {"success": False, "code": "COMMAND_TIMEOUT", "error": "timeout"}
tools.console_manager.execute_command = slow
server.mcp.run(transport="stdio")
''')
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent.parent / "src"))
    for key in ("MCP_TOOL_ALLOWLIST", "MCP_TOOL_DENYLIST", "MCP_CODE_MODE"):
        env.pop(key, None)
    params = StdioServerParameters(command=sys.executable, args=[str(script), str(tmp_path)], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            pending = asyncio.create_task(session.call_tool("execute_container_command", {
                "selector": "101", "command": "sleep 120"}))
            try:
                for _ in range(200):
                    if (tmp_path / "entered").exists():
                        break
                    await asyncio.sleep(0.01)
                assert (tmp_path / "entered").exists()
                assert (await asyncio.wait_for(session.list_tools(), 2)).tools
                assert not (await asyncio.wait_for(session.call_tool("get_nodes", {}), 2)).isError
                assert not pending.done()
            finally:
                (tmp_path / "release").touch()
                result = await pending
            assert "COMMAND_TIMEOUT" in result.content[0].text
            assert not (await session.call_tool("get_nodes", {})).isError
