"""Plugin-ready registry and exposure policy for MCP tool registration."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Protocol, TypeVar

from .tool_catalog import BUILTIN_TOOL_NAMES

ToolFunction = TypeVar("ToolFunction", bound=Callable[..., Any])


class ToolRegistryPlugin(Protocol):
    """Contract for a pluggable tool registration module."""

    def register(self, server: object) -> None:
        """Register tools onto the given server."""


class ToolExposurePolicy:
    """Decide which known tools may be registered with the MCP server."""

    def __init__(
        self,
        *,
        known_tools: Iterable[str] = (),
        allowlist: Iterable[str] | None = None,
        denylist: Iterable[str] | None = None,
    ) -> None:
        if allowlist is not None and denylist is not None:
            raise ValueError("tool allowlist and denylist are mutually exclusive")

        self.known_tools = frozenset(known_tools)
        self.allowlist = None if allowlist is None else frozenset(allowlist)
        self.denylist = None if denylist is None else frozenset(denylist)

        configured_names = (
            self.allowlist if self.allowlist is not None else self.denylist
        )
        unknown_names = (configured_names or frozenset()) - self.known_tools
        if unknown_names:
            unknown = ", ".join(sorted(unknown_names))
            raise ValueError(f"Unknown MCP tool name(s): {unknown}")

    @property
    def mode(self) -> str:
        if self.allowlist is not None:
            return "allowlist"
        if self.denylist is not None:
            return "denylist"
        return "all"

    def allows(self, tool_name: str) -> bool:
        if self.allowlist is not None:
            return tool_name in self.allowlist
        if self.denylist is not None:
            return tool_name not in self.denylist
        return True


class ToolRegistry:
    """Runtime registry for loading and registering tool plugins."""

    def __init__(
        self,
        mcp: Any | None = None,
        exposure_policy: ToolExposurePolicy | None = None,
    ) -> None:
        self._mcp = mcp
        self.exposure_policy = exposure_policy or ToolExposurePolicy(
            known_tools=BUILTIN_TOOL_NAMES
        )
        self._plugins: list[ToolRegistryPlugin] = []
        self.declared_tools: set[str] = set()
        self.registered_tools: set[str] = set()

    def add(self, plugin: ToolRegistryPlugin) -> None:
        self._plugins.append(plugin)

    def tool(
        self,
        name: str | None = None,
        description: str | None = None,
        annotations: Any | None = None,
    ) -> Callable[[ToolFunction], ToolFunction]:
        """Return a FastMCP-compatible decorator gated before registration."""

        def decorator(func: ToolFunction) -> ToolFunction:
            tool_name = name or func.__name__
            self.declared_tools.add(tool_name)
            if self.exposure_policy.allows(tool_name):
                if self._mcp is None:
                    raise RuntimeError("ToolRegistry must be bound to an MCP server")
                self._mcp.tool(
                    name=name,
                    description=description,
                    annotations=annotations,
                )(func)
                self.registered_tools.add(tool_name)
            return func

        return decorator

    def register_all(self, server: object) -> None:
        if self._mcp is None:
            self._mcp = getattr(server, "mcp")
        for plugin in self._plugins:
            plugin.register(server)

    @property
    def requested_but_unavailable(self) -> set[str]:
        """Allowlisted tools that current capability settings did not declare."""
        if self.exposure_policy.allowlist is None:
            return set()
        return set(self.exposure_policy.allowlist - self.declared_tools)
