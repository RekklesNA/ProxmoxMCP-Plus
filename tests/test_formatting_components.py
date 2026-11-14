from proxmox_mcp.formatting.colors import ProxmoxColors
from proxmox_mcp.formatting.components import ProxmoxComponents
from proxmox_mcp.formatting.formatters import ProxmoxFormatters
from proxmox_mcp.formatting.theme import ProxmoxTheme


def test_create_table_handles_title_and_multiline_cells(monkeypatch):
    monkeypatch.setattr(ProxmoxTheme, "USE_COLORS", False)

    table = ProxmoxComponents.create_table(
        ["Name", "Notes"],
        [["vm-100", "line 1\nline 2"], ["ct-101", "ok"]],
        title="Inventory",
    )

    assert "Inventory" in table
    assert "line 1" in table
    assert "line 2" in table
    assert "Inventory" not in ProxmoxComponents.create_table(["Name"], [["vm-100"]])
    assert "ct-101" in table


def test_progress_and_resource_usage_select_metric_colors(monkeypatch):
    monkeypatch.setattr(ProxmoxTheme, "USE_COLORS", False)

    assert ProxmoxComponents.create_progress_bar(50, 100, width=10) == "#####----- 50.0%"
    assert ProxmoxComponents.create_progress_bar(5, 0, width=4) == "---- 0.0%"

    usage = ProxmoxComponents.create_resource_usage(1024, 2048, "Memory", "[memory]")
    assert "[memory] Memory:" in usage
    assert "1.00 KB / 2.00 KB" in usage


def test_key_value_grid_and_status_badge(monkeypatch):
    monkeypatch.setattr(ProxmoxTheme, "USE_COLORS", False)

    grid = ProxmoxComponents.create_key_value_grid(
        {"Node": "pve1", "Status": "running", "VMID": "100"},
        columns=2,
    )

    assert "Node:" in grid
    assert "pve1" in grid
    assert "VMID:" in grid
    assert ProxmoxComponents.create_status_badge("running") == "[running] RUNNING"
    assert ProxmoxComponents.create_status_badge("missing") == "[unknown] MISSING"


def test_color_helpers_cover_status_resource_and_metric_branches(monkeypatch):
    monkeypatch.setattr(ProxmoxTheme, "USE_COLORS", True)

    assert ProxmoxColors.colorize("ok", ProxmoxColors.GREEN) == "\033[32mok\033[0m"
    assert ProxmoxColors.colorize("ok", ProxmoxColors.GREEN, ProxmoxColors.BOLD) == "\033[1m\033[32mok\033[0m"
    assert ProxmoxColors.status_color("running") == ProxmoxColors.GREEN
    assert ProxmoxColors.status_color("stopped") == ProxmoxColors.RED
    assert ProxmoxColors.status_color("warning") == ProxmoxColors.YELLOW
    assert ProxmoxColors.status_color("other") == ProxmoxColors.BLUE
    assert ProxmoxColors.resource_color("vm") == ProxmoxColors.CYAN
    assert ProxmoxColors.resource_color("cpu") == ProxmoxColors.YELLOW
    assert ProxmoxColors.resource_color("storage") == ProxmoxColors.MAGENTA
    assert ProxmoxColors.resource_color("other") == ProxmoxColors.BLUE
    assert ProxmoxColors.metric_color(95) == ProxmoxColors.RED
    assert ProxmoxColors.metric_color(85) == ProxmoxColors.YELLOW
    assert ProxmoxColors.metric_color(20) == ProxmoxColors.GREEN


def test_formatters_cover_common_output_shapes(monkeypatch):
    monkeypatch.setattr(ProxmoxTheme, "USE_COLORS", False)

    assert ProxmoxFormatters.format_bytes(1024 * 1024) == "1.00 MB"
    assert ProxmoxFormatters.format_uptime(90061) == "[uptime] 1d 1h 1m"
    assert ProxmoxFormatters.format_uptime(0) == "0m"
    assert ProxmoxFormatters.format_percentage(87.5) == "87.5%"
    assert ProxmoxFormatters.format_status("online") == "[online] ONLINE"
    assert "vm-100" in ProxmoxFormatters.format_resource_header("vm", "vm-100")
    assert "Details" in ProxmoxFormatters.format_section_header("Details", "details")
    assert ProxmoxFormatters.format_key_value("Node", "pve1", "[node]") == "[node] Node: pve1"

    output = ProxmoxFormatters.format_command_output(
        success=False,
        command="systemctl status app",
        output="out\n",
        error="err\n",
    )
    assert "FAILED" in output
    assert "systemctl status app" in output
    assert "err" in output


def test_theme_fallbacks():
    assert ProxmoxTheme.get_status_emoji("unknown-status") == "[unknown]"
    assert ProxmoxTheme.get_resource_emoji("not-a-resource") == ""
    assert ProxmoxTheme.get_action_emoji("not-an-action") == "[info]"
    assert ProxmoxTheme.get_section_emoji("not-a-section") == "[details]"
