"""Exercise the real sandbox and MCP protocol, without a live Proxmox host."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolRequest, ListToolsRequest

from proxmox_mcp.code_mode import install_code_mode


@pytest.fixture
def mode():
    mcp = FastMCP("sandbox-test")

    @mcp.tool(description="List cluster nodes")
    def get_nodes(target: str = "default") -> list[dict]:
        return [{"node": "pve", "target": target}]

    @mcp.tool()
    def protected_action(approval_token: str | None = None) -> str:
        if approval_token != "approved":
            raise ValueError("approval required; secret detail")
        return "done"

    return install_code_mode(SimpleNamespace(mcp=mcp))


async def protocol_call(mode, name, arguments):
    handler = mode.server.mcp._mcp_server.request_handlers[CallToolRequest]
    return (await handler(CallToolRequest(method="tools/call", params={"name": name, "arguments": arguments}))).root


@pytest.mark.asyncio
async def test_protocol_hides_and_blocks_domain_tools(mode):
    handler = mode.server.mcp._mcp_server.request_handlers[ListToolsRequest]
    result = (await handler(ListToolsRequest(method="tools/list"))).root
    assert {t.name for t in result.tools} == {"proxmox_code_search", "proxmox_code_get_schema", "proxmox_code_execute"}
    result = await protocol_call(mode, "get_nodes", {})
    assert result.isError
    assert "Direct domain tool" in result.content[0].text


@pytest.mark.asyncio
async def test_search_schema_and_execution_without_repository_manifest(mode, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = await protocol_call(mode, "proxmox_code_search", {"query": "cluster"})
    assert 'get_nodes' in result.content[0].text
    result = await protocol_call(mode, "proxmox_code_get_schema", {"names": ["get_nodes"]})
    assert 'target' in result.content[0].text
    result = await mode.execute('await call_tool("get_nodes", {"target": "second"})')
    assert result["success"]
    assert "second" in json.dumps(result)
    assert (await mode.execute('1 + 1'))["data"]["result"] == 2


@pytest.mark.asyncio
async def test_unknown_filtered_and_recursive_tools_are_unavailable(mode):
    for name in ["not_registered", "proxmox_code_execute"]:
        result = await mode.execute(f'await call_tool("{name}", {{}})')
        assert not result["success"]
    result = await protocol_call(mode, "proxmox_code_get_schema", {"names": ["proxmox_code_execute"]})
    assert "Unknown or unavailable" in result.content[0].text


@pytest.mark.asyncio
async def test_policy_validation_and_exception_redaction(mode):
    assert not (await mode.execute('await call_tool("get_nodes", {"target": []})'))["success"]
    result = await mode.execute('await call_tool("protected_action", {})')
    assert not result["success"]
    assert "secret" not in json.dumps(result)
    result = await mode.execute('await call_tool("protected_action", {"approval_token":"approved"})')
    assert result["success"]


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ['import os', 'open("/etc/passwd")', '"x" * 17000', '"x" * 200000000', 'await call_tool("get_nodes", [])', 'for i in range(26):\n    await call_tool("get_nodes", {})'])
async def test_limits_and_forbidden_access(mode, code):
    assert not (await mode.execute(code))["success"]


@pytest.mark.asyncio
async def test_concurrent_execution_does_not_enable_direct_calls(mode):
    good, direct = await asyncio.gather(mode.execute('await call_tool("get_nodes", {})'), protocol_call(mode, "get_nodes", {}))
    assert good["success"]
    assert direct.isError
