"""In-memory metrics collectors for MCP tools and HTTP proxy requests."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LabeledMetricSeries:
    count: int = 0
    latency_ms_sum: float = 0.0
    latency_ms_max: float = 0.0

    def observe(self, latency_ms: float) -> None:
        self.count += 1
        self.latency_ms_sum += latency_ms
        self.latency_ms_max = max(self.latency_ms_max, latency_ms)

    @property
    def latency_ms_avg(self) -> float:
        if self.count == 0:
            return 0.0
        return self.latency_ms_sum / self.count


@dataclass
class ToolMetrics:
    """Thread-safe tool metrics keyed by tool name and execution status."""

    _series: dict[tuple[str, str], LabeledMetricSeries] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def observe(self, tool_name: str, latency_ms: float, success: bool) -> None:
        status = "success" if success else "error"
        with self._lock:
            self._entry(tool_name, status).observe(latency_ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            grouped: dict[str, dict[str, dict[str, float | int]]] = {}
            for (tool_name, status), series in sorted(self._series.items()):
                grouped.setdefault(tool_name, {})[status] = {
                    "calls": series.count,
                    "latency_ms_sum": round(series.latency_ms_sum, 3),
                    "latency_ms_avg": round(series.latency_ms_avg, 3),
                    "latency_ms_max": round(series.latency_ms_max, 3),
                }
            return grouped

    def render_prometheus(self, prefix: str = "proxmox_mcp_tool") -> str:
        lines = [
            f"# HELP {prefix}_calls_total Total number of tool calls by status",
            f"# TYPE {prefix}_calls_total counter",
            f"# HELP {prefix}_latency_ms_sum Total tool latency in milliseconds by status",
            f"# TYPE {prefix}_latency_ms_sum counter",
            f"# HELP {prefix}_latency_ms_max Maximum observed tool latency in milliseconds by status",
            f"# TYPE {prefix}_latency_ms_max gauge",
            f"# HELP {prefix}_latency_ms_avg Average observed tool latency in milliseconds by status",
            f"# TYPE {prefix}_latency_ms_avg gauge",
        ]
        with self._lock:
            for (tool_name, status), series in sorted(self._series.items()):
                tool_label = self._escape_label(tool_name)
                status_label = self._escape_label(status)
                labels = f'tool="{tool_label}",status="{status_label}"'
                lines.extend(
                    [
                        f"{prefix}_calls_total{{{labels}}} {series.count}",
                        f"{prefix}_latency_ms_sum{{{labels}}} {round(series.latency_ms_sum, 3)}",
                        f"{prefix}_latency_ms_max{{{labels}}} {round(series.latency_ms_max, 3)}",
                        f"{prefix}_latency_ms_avg{{{labels}}} {round(series.latency_ms_avg, 3)}",
                    ]
                )
        return "\n".join(lines) + "\n"

    def _entry(self, tool_name: str, status: str) -> LabeledMetricSeries:
        return self._series.setdefault((tool_name, status), LabeledMetricSeries())

    @staticmethod
    def _escape_label(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')


@dataclass
class HttpRequestMetrics:
    """HTTP request metrics keyed by route, method, and status code."""

    _series: dict[tuple[str, str, str], LabeledMetricSeries] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def observe(self, route: str, method: str, status_code: int, latency_ms: float) -> None:
        route_key = route or "/"
        method_key = method.upper()
        status_key = str(status_code)
        with self._lock:
            self._entry(route_key, method_key, status_key).observe(latency_ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            rows: list[dict[str, float | int | str]] = []
            for (route, method, status), series in sorted(self._series.items()):
                rows.append(
                    {
                        "route": route,
                        "method": method,
                        "status": status,
                        "calls": series.count,
                        "latency_ms_sum": round(series.latency_ms_sum, 3),
                        "latency_ms_avg": round(series.latency_ms_avg, 3),
                        "latency_ms_max": round(series.latency_ms_max, 3),
                    }
                )
            return {"requests": rows}

    def render_prometheus(self, prefix: str = "proxmox_mcp_http") -> str:
        lines = [
            f"# HELP {prefix}_requests_total Total HTTP proxy requests by route, method, and status code",
            f"# TYPE {prefix}_requests_total counter",
            f"# HELP {prefix}_latency_ms_sum Total HTTP proxy latency in milliseconds",
            f"# TYPE {prefix}_latency_ms_sum counter",
            f"# HELP {prefix}_latency_ms_max Maximum HTTP proxy latency in milliseconds",
            f"# TYPE {prefix}_latency_ms_max gauge",
            f"# HELP {prefix}_latency_ms_avg Average HTTP proxy latency in milliseconds",
            f"# TYPE {prefix}_latency_ms_avg gauge",
        ]
        with self._lock:
            for (route, method, status), series in sorted(self._series.items()):
                labels = (
                    f'route="{ToolMetrics._escape_label(route)}",'
                    f'method="{ToolMetrics._escape_label(method)}",'
                    f'status="{ToolMetrics._escape_label(status)}"'
                )
                lines.extend(
                    [
                        f"{prefix}_requests_total{{{labels}}} {series.count}",
                        f"{prefix}_latency_ms_sum{{{labels}}} {round(series.latency_ms_sum, 3)}",
                        f"{prefix}_latency_ms_max{{{labels}}} {round(series.latency_ms_max, 3)}",
                        f"{prefix}_latency_ms_avg{{{labels}}} {round(series.latency_ms_avg, 3)}",
                    ]
                )
        return "\n".join(lines) + "\n"

    def _entry(self, route: str, method: str, status: str) -> LabeledMetricSeries:
        return self._series.setdefault((route, method, status), LabeledMetricSeries())
