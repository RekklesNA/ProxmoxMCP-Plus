"""Tests for observability metrics module."""

import pytest
import time
from proxmox_mcp.observability.metrics import (
    ToolMetrics,
    PROMETHEUS_AVAILABLE,
)


class TestPrometheusAvailability:
    """Test prometheus availability detection."""

    def test_prometheus_is_available(self):
        """Test that prometheus is available in the environment."""
        assert PROMETHEUS_AVAILABLE is True


class TestToolMetricsBasic:
    """Test basic ToolMetrics functionality."""

    def test_create_metrics_instance(self):
        """Test creating ToolMetrics instance."""
        metrics = ToolMetrics()
        assert metrics is not None

    def test_record_call_success(self):
        """Test recording a successful tool call."""
        metrics = ToolMetrics()
        # Should not raise any errors
        metrics.record_call("test_tool")

    def test_record_call_different_tools(self):
        """Test recording calls for different tools."""
        metrics = ToolMetrics()
        metrics.record_call("start_vm")
        metrics.record_call("stop_vm")
        metrics.record_call("get_nodes")

    def test_record_error_with_type(self):
        """Test recording an error with type."""
        metrics = ToolMetrics()
        metrics.record_error("test_tool", "ValueError")
        metrics.record_error("test_tool", "RuntimeError")

    def test_record_error_default_type(self):
        """Test recording error with default type."""
        metrics = ToolMetrics()
        metrics.record_error("test_tool")

    def test_record_latency_fast(self):
        """Test recording fast latency."""
        metrics = ToolMetrics()
        metrics.record_latency_ms("test_tool", 10.5)

    def test_record_latency_slow(self):
        """Test recording slow latency."""
        metrics = ToolMetrics()
        metrics.record_latency_ms("test_tool", 5000.0)

    def test_record_api_call_success(self):
        """Test recording successful API call."""
        metrics = ToolMetrics()
        metrics.record_api_call("/nodes", "success", 0.5)

    def test_record_api_call_failure(self):
        """Test recording failed API call."""
        metrics = ToolMetrics()
        metrics.record_api_call("/nodes", "error", 1.2)

    def test_record_api_call_no_duration(self):
        """Test recording API call without duration."""
        metrics = ToolMetrics()
        metrics.record_api_call("/nodes", "success")

    def test_set_vm_count(self):
        """Test setting VM count."""
        metrics = ToolMetrics()
        metrics.set_vm_count("node1", 10)
        metrics.set_vm_count("node1", 8, "running")
        metrics.set_vm_count("node1", 2, "stopped")

    def test_set_container_count(self):
        """Test setting container count."""
        metrics = ToolMetrics()
        metrics.set_container_count("node1", 5)
        metrics.set_container_count("node1", 3, "running")

    def test_set_storage_usage(self):
        """Test setting storage usage."""
        metrics = ToolMetrics()
        metrics.set_storage_usage("node1", "local", 1073741824)
        metrics.set_storage_usage("node1", "local-lvm", 5368709120)

    def test_increment_connections(self):
        """Test incrementing connections."""
        metrics = ToolMetrics()
        metrics.increment_active_connections()

    def test_decrement_connections(self):
        """Test decrementing connections."""
        metrics = ToolMetrics()
        metrics.increment_active_connections()
        metrics.decrement_active_connections()


class TestInstrumentToolContextManager:
    """Test instrument_tool context manager."""

    def test_instrument_successful_execution(self):
        """Test instrumenting successful tool execution."""
        metrics = ToolMetrics()

        with metrics.instrument_tool("test_tool"):
            result = 1 + 1
            assert result == 2

    def test_instrument_with_exception(self):
        """Test instrumenting tool execution with exception."""
        metrics = ToolMetrics()

        with pytest.raises(ValueError):
            with metrics.instrument_tool("failing_tool"):
                raise ValueError("Test error")

    def test_instrument_multiple_tools(self):
        """Test instrumenting multiple tools."""
        metrics = ToolMetrics()

        with metrics.instrument_tool("tool1"):
            pass

        with metrics.instrument_tool("tool2"):
            pass

    def test_instrument_nested_operations(self):
        """Test instrumenting nested operations."""
        metrics = ToolMetrics()

        with metrics.instrument_tool("outer"):
            with metrics.instrument_tool("inner"):
                pass

    def test_instrument_slow_operation(self):
        """Test instrumenting slow operation."""
        metrics = ToolMetrics()

        with metrics.instrument_tool("slow_tool"):
            time.sleep(0.01)  # 10ms


class TestMetricsEdgeCases:
    """Test edge cases and special scenarios."""

    def test_record_empty_tool_name(self):
        """Test recording with empty tool name."""
        metrics = ToolMetrics()
        metrics.record_call("")
        metrics.record_error("")
        metrics.record_latency_ms("", 100.0)

    def test_record_very_long_tool_name(self):
        """Test recording with very long tool name."""
        metrics = ToolMetrics()
        long_name = "a" * 1000
        metrics.record_call(long_name)

    def test_record_negative_latency(self):
        """Test recording negative latency (should handle gracefully)."""
        metrics = ToolMetrics()
        metrics.record_latency_ms("test_tool", -1.0)

    def test_record_very_high_latency(self):
        """Test recording very high latency."""
        metrics = ToolMetrics()
        metrics.record_latency_ms("test_tool", 999999.0)

    def test_record_large_vm_count(self):
        """Test recording large VM count."""
        metrics = ToolMetrics()
        metrics.set_vm_count("node1", 999999)

    def test_record_large_storage_usage(self):
        """Test recording large storage usage."""
        metrics = ToolMetrics()
        metrics.set_storage_usage("node1", "local", 999999999999)
