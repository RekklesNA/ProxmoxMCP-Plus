"""Minimal metrics hooks with no-op fallback."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolMetrics:
    """No-op metrics collector placeholder for future OTel/Prom integration."""

    def record_call(self, tool_name: str) -> None:
        return None

    def record_error(self, tool_name: str) -> None:
        return None

    def record_latency_ms(self, tool_name: str, latency_ms: float) -> None:
        return None
