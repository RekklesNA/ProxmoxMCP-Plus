"""Plugin-ready registry and exposure policy for MCP tool registration."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Protocol, TypeVar, get_type_hints
from contextvars import ContextVar
from contextlib import asynccontextmanager
from functools import partial, wraps
import inspect
import time
import anyio
from proxmox_mcp.security.access import authorize_client, client_principal
from proxmox_mcp.security.resources import validate_segment

from .tool_catalog import BUILTIN_TOOL_NAMES

ToolFunction = TypeVar("ToolFunction", bound=Callable[..., Any])
approval_context: ContextVar[str | None] = ContextVar("operation_approval", default=None)


def _async_dispatch(func: Callable[..., Any], authorize: Callable[[str, dict[str, Any]], None] | None = None, tool_name: str | None = None,
                    acquire: Callable[[str, dict[str, Any]], Any] | None = None) -> Callable[..., Any]:
    """Offload blocking tools and expose uniform operation approval metadata."""
    hints = get_type_hints(func, include_extras=True)
    signature = inspect.signature(func)
    extra_approval = "approval_token" not in signature.parameters
    parameters = [p.replace(annotation=hints.get(p.name, p.annotation)) for p in signature.parameters.values()]
    if extra_approval:
        index = next((i for i, p in enumerate(parameters) if p.kind == inspect.Parameter.VAR_KEYWORD), len(parameters))
        parameters.insert(index, inspect.Parameter("approval_token", inspect.Parameter.KEYWORD_ONLY, default=None, annotation=str | None))

    @wraps(func)
    async def dispatch(*args: Any, **kwargs: Any) -> Any:
        approval = kwargs.pop("approval_token", None) if extra_approval else kwargs.get("approval_token")
        token = approval_context.set(approval)
        try:
            arguments = signature.bind(*args, **kwargs).arguments
            if authorize is not None:
                authorize(tool_name or func.__name__, dict(arguments))
            for key in ("node", "target_node", "storage", "snapname"):
                if arguments.get(key) is not None:
                    validate_segment(arguments[key])
            async def invoke() -> Any:
                if inspect.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                return await anyio.to_thread.run_sync(partial(func, *args, **kwargs))
            if acquire is None:
                return await invoke()
            async with acquire(tool_name or func.__name__, dict(arguments)):
                return await invoke()
        finally:
            approval_context.reset(token)

    dispatch.__annotations__ = hints
    setattr(dispatch, "__signature__", signature.replace(parameters=parameters, return_annotation=hints.get("return", signature.return_annotation)))
    return dispatch


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
        self._server: Any = None
        self._limiters: dict[str, anyio.CapacityLimiter] = {}

    @asynccontextmanager
    async def _acquire(self, tool: str, arguments: dict[str, Any]) -> Any:
        if self._server is None:
            yield
            return
        server = self._server
        target = "all" if tool == "list_targets" else server.target_registry.resolve(arguments.get("target")).name
        limiter = self._limiters.setdefault(target, anyio.CapacityLimiter(server.config.mcp.worker_limit))
        start = time.perf_counter()
        async with limiter:
            server.metrics.observe("dispatch_queue", (time.perf_counter() - start) * 1000, True, target=target)
            yield

    def _authorize(self, tool: str, arguments: dict[str, Any]) -> None:
        if self._server is None:
            return
        server = self._server
        policies = server.config.mcp.client_permissions
        if not policies:
            return
        principal = client_principal(server.config.mcp.transport)
        target = None if tool == "list_targets" else server.target_registry.resolve(arguments.get("target")).name
        authorize_client(policies, principal, tool, target)

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
                )(_async_dispatch(func, self._authorize, tool_name, self._acquire))
                self.registered_tools.add(tool_name)
            return func

        return decorator

    def register_all(self, server: object) -> None:
        self._server = server
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
