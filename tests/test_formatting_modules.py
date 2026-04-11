"""Tests for formatting modules."""

import pytest
from proxmox_mcp.formatting.theme import ProxmoxTheme
from proxmox_mcp.formatting.colors import ProxmoxColors
from proxmox_mcp.formatting.formatters import ProxmoxFormatters
from proxmox_mcp.formatting.components import ProxmoxComponents


class TestProxmoxTheme:
    """Test ProxmoxTheme class."""

    def test_theme_has_status_emojis(self):
        """Test theme has status emojis defined."""
        assert 'online' in ProxmoxTheme.STATUS
        assert 'offline' in ProxmoxTheme.STATUS
        assert 'running' in ProxmoxTheme.STATUS
        assert 'stopped' in ProxmoxTheme.STATUS

    def test_theme_has_resource_emojis(self):
        """Test theme has resource emojis defined."""
        assert 'node' in ProxmoxTheme.RESOURCES
        assert 'vm' in ProxmoxTheme.RESOURCES
        assert 'container' in ProxmoxTheme.RESOURCES
        assert 'storage' in ProxmoxTheme.RESOURCES

    def test_theme_has_action_emojis(self):
        """Test theme has action emojis defined."""
        assert 'success' in ProxmoxTheme.ACTIONS
        assert 'error' in ProxmoxTheme.ACTIONS
        assert 'command' in ProxmoxTheme.ACTIONS

    def test_theme_has_section_emojis(self):
        """Test theme has section emojis defined."""
        assert 'header' in ProxmoxTheme.SECTIONS
        assert 'details' in ProxmoxTheme.SECTIONS

    def test_get_status_emoji_existing(self):
        """Test getting emoji for existing status."""
        emoji = ProxmoxTheme.get_status_emoji('online')
        assert emoji == '🟢'

    def test_get_status_emoji_unknown(self):
        """Test getting emoji for unknown status."""
        emoji = ProxmoxTheme.get_status_emoji('unknown_status')
        assert emoji == ProxmoxTheme.STATUS['unknown']

    def test_get_resource_emoji_existing(self):
        """Test getting emoji for existing resource."""
        emoji = ProxmoxTheme.get_resource_emoji('vm')
        assert emoji == '🗃️'

    def test_get_resource_emoji_unknown(self):
        """Test getting emoji for unknown resource."""
        emoji = ProxmoxTheme.get_resource_emoji('unknown_resource')
        assert emoji == '📦'

    def test_feature_flags(self):
        """Test feature flags are set."""
        assert ProxmoxTheme.USE_EMOJI is True
        assert ProxmoxTheme.USE_COLORS is True


class TestProxmoxColors:
    """Test ProxmoxColors class."""

    def test_color_definitions(self):
        """Test color codes are defined."""
        assert ProxmoxColors.RED is not None
        assert ProxmoxColors.GREEN is not None
        assert ProxmoxColors.BLUE is not None

    def test_colorize_with_color(self):
        """Test colorizing text with color."""
        result = ProxmoxColors.colorize("test", ProxmoxColors.RED)
        assert "test" in result

    def test_colorize_with_style(self):
        """Test colorizing text with color and style."""
        result = ProxmoxColors.colorize("test", ProxmoxColors.RED, ProxmoxColors.BOLD)
        assert "test" in result

    def test_status_color_running(self):
        """Test status color for running."""
        color = ProxmoxColors.status_color('running')
        assert color == ProxmoxColors.GREEN

    def test_status_color_stopped(self):
        """Test status color for stopped."""
        color = ProxmoxColors.status_color('stopped')
        assert color == ProxmoxColors.RED

    def test_status_color_pending(self):
        """Test status color for pending."""
        color = ProxmoxColors.status_color('pending')
        assert color == ProxmoxColors.YELLOW

    def test_status_color_unknown(self):
        """Test status color for unknown."""
        color = ProxmoxColors.status_color('unknown')
        assert color == ProxmoxColors.BLUE

    def test_resource_color_vm(self):
        """Test resource color for VM."""
        color = ProxmoxColors.resource_color('vm')
        assert color == ProxmoxColors.CYAN

    def test_resource_color_storage(self):
        """Test resource color for storage."""
        color = ProxmoxColors.resource_color('storage')
        assert color == ProxmoxColors.MAGENTA

    def test_resource_color_cpu(self):
        """Test resource color for CPU."""
        color = ProxmoxColors.resource_color('cpu')
        assert color == ProxmoxColors.YELLOW

    def test_metric_color_good(self):
        """Test metric color for good value."""
        color = ProxmoxColors.metric_color(50.0)
        assert color == ProxmoxColors.GREEN

    def test_metric_color_warning(self):
        """Test metric color for warning value."""
        color = ProxmoxColors.metric_color(85.0)
        assert color == ProxmoxColors.YELLOW

    def test_metric_color_critical(self):
        """Test metric color for critical value."""
        color = ProxmoxColors.metric_color(95.0)
        assert color == ProxmoxColors.RED


class TestProxmoxFormatters:
    """Test ProxmoxFormatters class."""

    def test_format_bytes_bytes(self):
        """Test formatting bytes."""
        result = ProxmoxFormatters.format_bytes(512)
        assert "B" in result

    def test_format_bytes_kilobytes(self):
        """Test formatting kilobytes."""
        result = ProxmoxFormatters.format_bytes(1024)
        assert "KB" in result

    def test_format_bytes_megabytes(self):
        """Test formatting megabytes."""
        result = ProxmoxFormatters.format_bytes(1048576)
        assert "MB" in result

    def test_format_bytes_gigabytes(self):
        """Test formatting gigabytes."""
        result = ProxmoxFormatters.format_bytes(1073741824)
        assert "GB" in result

    def test_format_uptime_zero(self):
        """Test formatting zero uptime."""
        result = ProxmoxFormatters.format_uptime(0)
        assert result == "0m"

    def test_format_uptime_minutes(self):
        """Test formatting uptime in minutes."""
        result = ProxmoxFormatters.format_uptime(120)
        assert "2m" in result

    def test_format_uptime_hours(self):
        """Test formatting uptime in hours."""
        result = ProxmoxFormatters.format_uptime(3660)
        assert "1h" in result

    def test_format_uptime_days(self):
        """Test formatting uptime in days."""
        result = ProxmoxFormatters.format_uptime(90000)
        assert "1d" in result

    def test_format_percentage_normal(self):
        """Test formatting normal percentage."""
        result = ProxmoxFormatters.format_percentage(50.0)
        assert "50.0%" in result

    def test_format_percentage_warning(self):
        """Test formatting warning percentage."""
        result = ProxmoxFormatters.format_percentage(85.0)
        assert "85.0%" in result

    def test_format_status_running(self):
        """Test formatting running status."""
        result = ProxmoxFormatters.format_status('running')
        assert "RUNNING" in result

    def test_format_status_stopped(self):
        """Test formatting stopped status."""
        result = ProxmoxFormatters.format_status('stopped')
        assert "STOPPED" in result

    def test_format_command_output_success(self):
        """Test formatting successful command output."""
        result = ProxmoxFormatters.format_command_output(
            success=True,
            command="ls -la",
            output="total 100"
        )
        assert "SUCCESS" in result
        assert "ls -la" in result
        assert "total 100" in result

    def test_format_command_output_with_error(self):
        """Test formatting command output with error."""
        result = ProxmoxFormatters.format_command_output(
            success=False,
            command="invalid_cmd",
            output="",
            error="Command not found"
        )
        assert "FAILED" in result
        assert "Command not found" in result


class TestProxmoxComponents:
    """Test ProxmoxComponents class."""

    def test_create_table_basic(self):
        """Test creating basic table."""
        headers = ["Name", "Status"]
        rows = [
            ["vm1", "running"],
            ["vm2", "stopped"],
        ]
        result = ProxmoxComponents.create_table(headers, rows)
        assert "Name" in result
        assert "vm1" in result
        assert "running" in result

    def test_create_table_with_title(self):
        """Test creating table with title."""
        headers = ["Name"]
        rows = [["vm1"]]
        result = ProxmoxComponents.create_table(headers, rows, title="VMs")
        assert "VMs" in result

    def test_create_table_empty_rows(self):
        """Test creating table with empty rows."""
        headers = ["Name", "Status"]
        rows = []
        result = ProxmoxComponents.create_table(headers, rows)
        assert "Name" in result

    def test_create_progress_bar_half(self):
        """Test creating half progress bar."""
        result = ProxmoxComponents.create_progress_bar(50, 100)
        assert "50.0%" in result

    def test_create_progress_bar_full(self):
        """Test creating full progress bar."""
        result = ProxmoxComponents.create_progress_bar(100, 100)
        assert "100.0%" in result

    def test_create_progress_bar_zero(self):
        """Test creating zero progress bar."""
        result = ProxmoxComponents.create_progress_bar(0, 100)
        assert "0.0%" in result

    def test_create_status_badge_running(self):
        """Test creating running status badge."""
        result = ProxmoxComponents.create_status_badge('running')
        assert "RUNNING" in result

    def test_create_status_badge_stopped(self):
        """Test creating stopped status badge."""
        result = ProxmoxComponents.create_status_badge('stopped')
        assert "STOPPED" in result

    def test_create_key_value_grid(self):
        """Test creating key-value grid."""
        data = {
            "Name": "vm1",
            "Status": "running",
            "CPU": "2",
            "Memory": "4GB"
        }
        result = ProxmoxComponents.create_key_value_grid(data)
        assert "Name" in result
        assert "vm1" in result
