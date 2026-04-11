"""Plugin-ready registry for MCP tool registration."""

from __future__ import annotations

from typing import Protocol


class ToolRegistryPlugin(Protocol):
    """Contract for a pluggable tool registration module."""

    def register(self, server: object) -> None:
        """Register tools onto the given server."""


class ToolRegistry:
    """Runtime registry for loading and registering tool plugins."""

    def __init__(self) -> None:
        self._plugins: list[ToolRegistryPlugin] = []

    def add(self, plugin: ToolRegistryPlugin) -> None:
        self._plugins.append(plugin)

    def register_all(self, server: object) -> None:
        for plugin in self._plugins:
            plugin.register(server)
