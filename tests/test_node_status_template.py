"""Node status rendering against the shape /nodes/{node}/status actually returns."""
from proxmox_mcp.formatting.templates import ProxmoxTemplates


def test_node_status_displays_zero_available_memory():
    out = ProxmoxTemplates.node_status("pve1", {"memory": {"available": 0}})
    assert "Memory Available: 0.00 B" in out

# Trimmed from a live Proxmox VE 9.2 response.
LIVE_STATUS = {
    "status": "online",
    "uptime": 22416,
    "cpu": 0.0737179510843123,
    "wait": 0.00314075128483602,
    "loadavg": ["0.92", "0.76", "0.73"],
    "cpuinfo": {
        "cpus": 8,
        "cores": 4,
        "sockets": 1,
        "mhz": "3511.125",
        "model": "Intel(R) Core(TM) i5-8260U CPU @ 1.60GHz",
    },
    "memory": {"total": 67286204416, "used": 20938321920, "available": 46347882496},
    "swap": {"total": 8589930496, "used": 0},
    "rootfs": {"total": 100861726720, "used": 33731584000},
}


def test_node_status_renders_cpu_memory_and_disk_detail():
    out = ProxmoxTemplates.node_status("pve1", LIVE_STATUS)

    assert "- Status: ONLINE" in out
    assert "- CPU Cores: 8" in out
    assert "- CPU Model: Intel(R) Core(TM) i5-8260U CPU @ 1.60GHz" in out
    assert "- CPU Layout: 4 cores / 1 sockets @ 3511 MHz" in out
    assert "- CPU Usage: 7.4% (iowait 0.3%)" in out
    assert "- Load Average: 0.92, 0.76, 0.73" in out
    assert "- Memory Available: 43.16 GB" in out
    assert "- Swap: 0.00 B / 8.00 GB (0.0%)" in out
    # "rootfs" is this endpoint's name for the root filesystem; before this the
    # template only looked for "disk" and so never rendered the line.
    assert "- Disk: 31.41 GB / 93.93 GB (33.4%)" in out


def test_node_status_still_accepts_the_node_list_disk_key():
    out = ProxmoxTemplates.node_status(
        "pve1", {"status": "online", "disk": {"total": 2048, "used": 1024}}
    )

    assert "- Disk: 1.00 KB / 2.00 KB (50.0%)" in out


def test_node_status_omits_sections_absent_from_the_payload():
    out = ProxmoxTemplates.node_status("pve1", {})

    assert "Node: pve1" in out
    assert "- Status: UNKNOWN" in out
    assert "- CPU Cores: N/A" in out
    for absent in ("CPU Model", "CPU Layout", "CPU Usage", "Load Average", "Swap", "Disk"):
        assert absent not in out


def test_node_status_tolerates_unusable_values():
    out = ProxmoxTemplates.node_status(
        "pve1",
        {
            "status": "online",
            "cpuinfo": {"cpus": 2, "cores": 2, "mhz": "not-a-number"},
            "cpu": None,
            "swap": {"total": 0, "used": 0},
        },
    )

    assert "- CPU Layout: 2 cores" in out
    assert "MHz" not in out
    assert "CPU Usage" not in out
    assert "Swap" not in out
