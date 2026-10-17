"""In-memory metrics collectors for MCP tools and HTTP proxy requests."""

from __future__ import annotations

import threading
import math
from dataclasses import dataclass, field
from typing import Any

LATENCY_BUCKETS_MS = (1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000,
                     10000, 30000, 60000, 120000, 300000, math.inf)


@dataclass
class LabeledMetricSeries:
    count: int = 0
    latency_ms_sum: float = 0.0
    latency_ms_max: float = 0.0
    buckets: list[int] = field(default_factory=lambda: [0] * len(LATENCY_BUCKETS_MS))

    def observe(self, latency_ms: float) -> None:
        if not math.isfinite(latency_ms) or latency_ms < 0:
            raise ValueError("Latency must be finite and non-negative")
        self.count += 1
        self.latency_ms_sum += latency_ms
        self.latency_ms_max = max(self.latency_ms_max, latency_ms)
        for index, bound in enumerate(LATENCY_BUCKETS_MS):
            if latency_ms <= bound:
                self.buckets[index] += 1

    def quantile(self, fraction: float) -> float | None:
        """Approximate quantiles using cumulative buckets, like histogram_quantile.

        Overflow quantiles are unknown rather than an invented finite latency.
        """
        if not self.count:
            return None
        rank = fraction * self.count
        previous_count = 0
        lower = 0.0
        for bound, count in zip(LATENCY_BUCKETS_MS, self.buckets):
            if count >= rank:
                if math.isinf(bound):
                    return None
                return round(lower + (bound - lower) * (rank - previous_count) / (count - previous_count), 3)
            previous_count, lower = count, bound
        return None

    def histogram_lines(self, prefix: str, labels: str) -> list[str]:
        lines = []
        for bound, count in zip(LATENCY_BUCKETS_MS, self.buckets):
            upper = "+Inf" if math.isinf(bound) else str(bound / 1000)
            lines.append(f'{prefix}_latency_seconds_bucket{{{labels},le="{upper}"}} {count}')
        lines.extend([f"{prefix}_latency_seconds_sum{{{labels}}} {self.latency_ms_sum / 1000}",
                      f"{prefix}_latency_seconds_count{{{labels}}} {self.count}"])
        return lines

    @property
    def latency_ms_avg(self) -> float:
        if self.count == 0:
            return 0.0
        return self.latency_ms_sum / self.count


@dataclass
class ToolMetrics:
    """Thread-safe tool metrics keyed by tool name and execution status."""

    _series: dict[tuple[str, str, str], LabeledMetricSeries] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def observe(self, tool_name: str, latency_ms: float, success: bool, target: str = "default", outcome: str | None = None) -> None:
        status = outcome if outcome in {"success", "error", "denied", "partial", "submitted"} else ("success" if success else "error")
        with self._lock:
            self._entry(tool_name, status, target).observe(latency_ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            grouped: dict[str, Any] = {}
            for (tool_name, status, target), series in sorted(self._series.items()):
                grouped.setdefault(tool_name, {}).setdefault(status, {}).setdefault(target, {
                    "calls": 0, "latency_ms_sum": 0.0, "latency_ms_avg": 0.0, "latency_ms_max": 0.0,
                })
                item = grouped[tool_name][status][target]
                item["latency_ms_p95"] = series.quantile(0.95)
                item["latency_ms_p99"] = series.quantile(0.99)
                item["calls"] += series.count
                item["latency_ms_sum"] += series.latency_ms_sum
                item["latency_ms_max"] = max(item["latency_ms_max"], series.latency_ms_max)
            for statuses in grouped.values():
                for targets in statuses.values():
                    for item in targets.values():
                        item["latency_ms_sum"] = round(item["latency_ms_sum"], 3)
                        item["latency_ms_avg"] = round(item["latency_ms_sum"] / item["calls"], 3) if item["calls"] else 0.0
            return grouped

    def render_prometheus(self, prefix: str = "proxmox_mcp_tool") -> str:
        lines = [
            f"# HELP {prefix}_latency_seconds Tool latency distribution in seconds",
            f"# TYPE {prefix}_latency_seconds histogram",
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
            for (tool_name, status, target), series in sorted(self._series.items()):
                tool_label = self._escape_label(tool_name)
                status_label = self._escape_label(status)
                target_label = self._escape_label(target)
                labels = f'tool="{tool_label}",status="{status_label}",target="{target_label}"'
                lines.extend(series.histogram_lines(prefix, labels))
                lines.extend(
                    [
                        f"{prefix}_calls_total{{{labels}}} {series.count}",
                        f"{prefix}_latency_ms_sum{{{labels}}} {round(series.latency_ms_sum, 3)}",
                        f"{prefix}_latency_ms_max{{{labels}}} {round(series.latency_ms_max, 3)}",
                        f"{prefix}_latency_ms_avg{{{labels}}} {round(series.latency_ms_avg, 3)}",
                    ]
                )
        return "\n".join(lines) + "\n"

    def _entry(self, tool_name: str, status: str, target: str) -> LabeledMetricSeries:
        return self._series.setdefault((tool_name, status, target), LabeledMetricSeries())

    @staticmethod
    def _escape_label(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


@dataclass
class HttpRequestMetrics:
    """HTTP request metrics keyed by route, method, and status code."""

    _series: dict[tuple[str, str, str], LabeledMetricSeries] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def observe(self, route: str, method: str, status_code: int, latency_ms: float) -> None:
        route_key = route or "/"
        method_key = method.upper()
        if method_key not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE", "CONNECT"}:
            method_key = "OTHER"
        status_key = str(status_code)
        with self._lock:
            self._entry(route_key, method_key, status_key).observe(latency_ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            rows: list[dict[str, Any]] = []
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
                        "latency_ms_p95": series.quantile(0.95),
                        "latency_ms_p99": series.quantile(0.99),
                    }
                )
            return {"requests": rows}

    def render_prometheus(self, prefix: str = "proxmox_mcp_http") -> str:
        lines = [
            f"# HELP {prefix}_latency_seconds HTTP proxy latency distribution in seconds",
            f"# TYPE {prefix}_latency_seconds histogram",
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
                lines.extend(series.histogram_lines(prefix, labels))
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
