"""
Prometheus-based metrics collection for ProxmoxMCP-Plus.

Provides comprehensive observability through:
- Tool call counts and success/failure rates
- Tool execution latency histograms
- Active connection tracking
- Error rate monitoring
- Resource usage metrics

All metrics are exposed via Prometheus format for scraping.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Generator

try:
    from prometheus_client import Counter, Gauge, Histogram

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

# Define metrics only if prometheus-client is available
if PROMETHEUS_AVAILABLE:
    # Tool execution metrics
    TOOL_CALLS_TOTAL = Counter(
        "proxmox_mcp_tool_calls_total",
        "Total number of tool calls",
        ["tool_name", "status"],
    )

    TOOL_EXECUTION_DURATION = Histogram(
        "proxmox_mcp_tool_duration_seconds",
        "Tool execution duration in seconds",
        ["tool_name"],
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
    )

    TOOL_ERRORS_TOTAL = Counter(
        "proxmox_mcp_tool_errors_total",
        "Total number of tool errors",
        ["tool_name", "error_type"],
    )

    # API call metrics
    PROXMOX_API_CALLS_TOTAL = Counter(
        "proxmox_mcp_api_calls_total",
        "Total number of Proxmox API calls",
        ["endpoint", "status"],
    )

    PROXMOX_API_DURATION = Histogram(
        "proxmox_mcp_api_duration_seconds",
        "Proxmox API call duration in seconds",
        ["endpoint"],
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )

    # Connection metrics
    ACTIVE_CONNECTIONS = Gauge(
        "proxmox_mcp_active_connections",
        "Number of active MCP connections",
    )

    # Resource metrics
    VM_COUNT = Gauge(
        "proxmox_mcp_vm_count",
        "Number of virtual machines",
        ["node", "status"],
    )

    CONTAINER_COUNT = Gauge(
        "proxmox_mcp_container_count",
        "Number of LXC containers",
        ["node", "status"],
    )

    STORAGE_USAGE = Gauge(
        "proxmox_mcp_storage_usage_bytes",
        "Storage usage in bytes",
        ["node", "storage"],
    )


@dataclass
class ToolMetrics:
    """
    Metrics collector for ProxmoxMCP tool execution.

    Provides comprehensive monitoring through Prometheus metrics:
    - Tool call counts with success/failure tracking
    - Execution duration histograms
    - Error rate monitoring by type
    - Performance bottleneck identification

    When prometheus-client is not available, all operations are no-ops
    to avoid breaking functionality.
    """

    _instance: "ToolMetrics | None" = field(default=None, init=False, repr=False)

    def record_call(self, tool_name: str) -> None:
        """Record a successful tool call."""
        if not PROMETHEUS_AVAILABLE:
            return
        TOOL_CALLS_TOTAL.labels(tool_name=tool_name, status="success").inc()

    def record_error(self, tool_name: str, error_type: str = "unknown") -> None:
        """Record a tool error with error type classification."""
        if not PROMETHEUS_AVAILABLE:
            return
        TOOL_ERRORS_TOTAL.labels(tool_name=tool_name, error_type=error_type).inc()
        TOOL_CALLS_TOTAL.labels(tool_name=tool_name, status="error").inc()

    def record_latency_ms(self, tool_name: str, latency_ms: float) -> None:
        """Record tool latency (stored in histogram as seconds)."""
        if not PROMETHEUS_AVAILABLE:
            return
        TOOL_EXECUTION_DURATION.labels(tool_name=tool_name).observe(latency_ms / 1000.0)

    @contextmanager
    def instrument_tool(self, tool_name: str) -> Generator[None, None, None]:
        """
        Context manager for automatic tool instrumentation.

        Usage:
            with metrics.instrument_tool("start_vm"):
                await start_vm(vm_id=100)

        Automatically tracks:
        - Call count
        - Execution duration
        - Success/failure status
        """
        if not PROMETHEUS_AVAILABLE:
            yield
            return

        start_time = time.perf_counter()
        try:
            yield
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            self.record_call(tool_name)
            self.record_latency_ms(tool_name, elapsed_ms)
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            error_type = type(e).__name__
            self.record_error(tool_name, error_type)
            self.record_latency_ms(tool_name, elapsed_ms)
            raise

    def record_api_call(
        self, endpoint: str, status: str = "success", duration_s: float = 0.0
    ) -> None:
        """Record a Proxmox API call."""
        if not PROMETHEUS_AVAILABLE:
            return
        PROXMOX_API_CALLS_TOTAL.labels(endpoint=endpoint, status=status).inc()
        if duration_s > 0:
            PROXMOX_API_DURATION.labels(endpoint=endpoint).observe(duration_s)

    def set_vm_count(self, node: str, count: int, status: str = "all") -> None:
        """Update VM count gauge for a node."""
        if not PROMETHEUS_AVAILABLE:
            return
        VM_COUNT.labels(node=node, status=status).set(count)

    def set_container_count(self, node: str, count: int, status: str = "all") -> None:
        """Update container count gauge for a node."""
        if not PROMETHEUS_AVAILABLE:
            return
        CONTAINER_COUNT.labels(node=node, status=status).set(count)

    def set_storage_usage(self, node: str, storage: str, usage_bytes: int) -> None:
        """Update storage usage gauge."""
        if not PROMETHEUS_AVAILABLE:
            return
        STORAGE_USAGE.labels(node=node, storage=storage).set(usage_bytes)

    def increment_active_connections(self) -> None:
        """Increment active connections counter."""
        if not PROMETHEUS_AVAILABLE:
            return
        ACTIVE_CONNECTIONS.inc()

    def decrement_active_connections(self) -> None:
        """Decrement active connections counter."""
        if not PROMETHEUS_AVAILABLE:
            return
        ACTIVE_CONNECTIONS.dec()
