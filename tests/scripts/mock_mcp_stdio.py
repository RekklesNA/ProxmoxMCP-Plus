"""Minimal MCP stdio server used for OpenAPI proxy smoke tests."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("MockMCP")


@mcp.tool()
def ping() -> str:
    return "pong"


if __name__ == "__main__":
    import anyio

    anyio.run(mcp.run_stdio_async)
