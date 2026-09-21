"""Runtime-catalog-backed Code Mode for the Proxmox MCP server."""
from __future__ import annotations

import ast
import asyncio
import json
from typing import Any

from mcp.server.fastmcp.exceptions import ToolError
from pydantic_core import to_jsonable_python

_SOURCE_LIMIT = 64_000


def _safe_error() -> dict[str, Any]:
    return {"success": False, "error": "Code Mode execution failed."}


def _schema(tool: Any) -> dict[str, Any]:
    model = getattr(getattr(tool, "fn_metadata", None), "arg_model", None)
    if model is None:
        return {"type": "object", "properties": {}}
    try:
        return model.model_json_schema()
    except Exception:
        return {"type": "object", "properties": {}}


def _source_allowed(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, TypeError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Raise)):
            return False
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {
            "__import__", "compile", "eval", "exec", "open", "input", "globals", "locals", "vars",
        }:
            return False
    return True


class CodeMode:
    """Registers the three public Code Mode tools and guards hidden dispatch."""

    def __init__(self, server: Any) -> None:
        self.server = server
        # Snapshot only domain tools registered after exposure/capability filtering.
        self.domain_tools = dict(server.mcp._tool_manager._tools)
        self._dispatch = server.mcp.call_tool
        self._execution_slots = asyncio.Semaphore(2)

    def register(self) -> None:
        mcp = self.server.mcp

        @mcp.tool(name="proxmox_code_search", description="Search Proxmox MCP tools by name or description.")
        async def code_search(query: str, category: str | None = None, limit: int = 10) -> dict[str, Any]:
            query_l = query.lower().strip()
            limit = max(1, min(limit, 20))
            tools = self._runtime_tools()
            results = []
            for name, tool in tools.items():
                item = {"name": name, "description": tool.description or ""}
                if name not in tools:
                    continue
                haystack = f"{name} {item.get('description', '')}".lower()
                if query_l and query_l not in haystack:
                    continue
                if category and not name.startswith(category):
                    continue
                results.append(item)
            return {"success": True, "data": results[:limit]}

        @mcp.tool(name="proxmox_code_get_schema", description="Return exact input schemas for discovered Proxmox tools.")
        async def code_get_schema(names: list[str]) -> dict[str, Any]:
            tools = self._runtime_tools()
            if not names or any(name not in tools for name in names):
                return {"success": False, "error": "Unknown or unavailable Proxmox tool."}
            return {"success": True, "data": {name: _schema(tools[name]) for name in names}}

        @mcp.tool(name="proxmox_code_execute", description="Execute sandboxed async code using call_tool(name, arguments).")
        async def code_execute(code: str) -> dict[str, Any]:
            return await self.execute(code)

        self._guard_dispatch()

    def _runtime_tools(self) -> dict[str, Any]:
        return self.domain_tools

    def _guard_dispatch(self) -> None:
        mcp = self.server.mcp
        original_call = mcp.call_tool
        original_list = mcp.list_tools
        tool_manager = mcp._tool_manager
        original_manager_list = tool_manager.list_tools
        public = frozenset({"proxmox_code_search", "proxmox_code_get_schema", "proxmox_code_execute"})

        async def guarded_call(name: str, arguments: dict[str, Any]) -> Any:
            if name not in public:
                raise ToolError("Direct domain tool calls are unavailable in code_mode; use Code Mode tools.")
            return await original_call(name, arguments)

        async def guarded_list(*args: Any, **kwargs: Any) -> list[Any]:
            return [tool for tool in await original_list(*args, **kwargs) if getattr(tool, "name", None) in public]

        def guarded_manager_list(*args: Any, **kwargs: Any) -> list[Any]:
            return [tool for tool in original_manager_list(*args, **kwargs) if getattr(tool, "name", None) in public]

        mcp.call_tool = guarded_call
        mcp.list_tools = guarded_list
        tool_manager.list_tools = guarded_manager_list
        # FastMCP registered bound handlers during initialization; update both
        # protocol entry points, not just the Python instance attributes.
        mcp._mcp_server.list_tools()(guarded_list)
        mcp._mcp_server.call_tool(validate_input=False)(guarded_call)

    async def execute(self, code: str) -> dict[str, Any]:
        if not isinstance(code, str) or len(code) > _SOURCE_LIMIT or not _source_allowed(code):
            return {"success": False, "error": "Code Mode source is invalid or exceeds the configured limit."}
        try:
            from pydantic_monty import AsyncMonty, CollectStreams
        except Exception:
            return _safe_error()
        calls = 0
        original_call = self._dispatch

        async def call_tool(name: str, arguments: dict[str, Any] | None = None) -> Any:
            nonlocal calls
            if not isinstance(name, str) or name not in self._runtime_tools() or name in {
                "proxmox_code_search", "proxmox_code_get_schema", "proxmox_code_execute",
            }:
                raise ToolError("Code Mode can invoke only available domain tools.")
            calls += 1
            if calls > 25:
                raise RuntimeError("tool call limit exceeded")
            if arguments is not None and not isinstance(arguments, dict):
                raise ToolError("Tool arguments must be an object.")
            # MCP results contain Pydantic content blocks, which cannot cross
            # the sandbox boundary directly. Preserve their wire representation.
            result = to_jsonable_python(await original_call(name, {} if arguments is None else arguments))
            if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 1_000_000:
                raise RuntimeError("tool result limit exceeded")
            return result

        try:
            streams = CollectStreams(max_bytes=16_000)
            async with self._execution_slots, asyncio.timeout(30), AsyncMonty(min_processes=1, max_processes=1, max_checkouts_per_worker=1, request_timeout=30) as pool:
                async with pool.checkout(limits={"max_duration_secs": 30, "max_memory": 100_000_000, "max_recursion_depth": 100, "max_suspensions": 128}) as session:
                    result = await session.feed_run(code, external_lookup={"call_tool": call_tool}, print_callback=streams)
            if len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 16_000:
                return {"success": False, "error": "Code Mode execution exceeded a configured safety limit."}
            return {"success": True, "data": {"result": result}}
        except Exception:
            return _safe_error()


def install_code_mode(server: Any) -> CodeMode:
    mode = CodeMode(server)
    mode.register()
    return mode
