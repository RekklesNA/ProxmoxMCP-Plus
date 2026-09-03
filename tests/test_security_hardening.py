import asyncio
import json
import logging
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi import FastAPI

from proxmox_mcp.openapi_proxy import RateLimitMiddleware
from proxmox_mcp.services.builtin_tool_plugins import (
    BackupToolsPlugin,
    ContainerToolsPlugin,
    CoreToolsPlugin,
    ImageToolsPlugin,
    JobsToolsPlugin,
    LogToolsPlugin,
    SnapshotToolsPlugin,
    VMToolsPlugin,
)
from proxmox_mcp.services.tool_catalog import BUILTIN_TOOL_NAMES
from proxmox_mcp.services.tool_registry import ToolExposurePolicy, ToolRegistry
from proxmox_mcp.tools.base import ProxmoxTool
from proxmox_mcp.tools.console.container_manager import ContainerConsoleManager
from proxmox_mcp.tools.console.manager import VMConsoleManager


ROOT = Path(__file__).resolve().parent.parent


class _FakeMCP:
    def __init__(self):
        self.tools: set[str] = set()

    def tool(self, *args, **kwargs):
        def decorator(func):
            self.tools.add(func.__name__)
            return func

        return decorator


def test_manifest_declares_all_registered_tools():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    manifest_tools = {tool["name"] for tool in manifest["tools"]}

    fake_mcp = _FakeMCP()
    tool_registry = ToolRegistry(
        fake_mcp,
        ToolExposurePolicy(known_tools=BUILTIN_TOOL_NAMES),
    )
    fake_server = SimpleNamespace(
        mcp=fake_mcp,
        tool_registry=tool_registry,
        config=SimpleNamespace(ssh=SimpleNamespace(user="root")),
        logger=Mock(),
    )
    for plugin in (
        CoreToolsPlugin(),
        JobsToolsPlugin(),
        VMToolsPlugin(),
        ContainerToolsPlugin(),
        SnapshotToolsPlugin(),
        ImageToolsPlugin(),
        BackupToolsPlugin(),
        LogToolsPlugin(),
    ):
        plugin.register(fake_server)

    registered_tools = fake_mcp.tools

    assert registered_tools
    assert registered_tools == tool_registry.registered_tools
    assert BUILTIN_TOOL_NAMES == manifest_tools
    assert registered_tools - manifest_tools == set()
    assert manifest_tools - registered_tools == set()


def test_tool_error_logging_strips_control_characters(caplog):
    tool = ProxmoxTool(Mock())
    caplog.set_level(logging.ERROR, logger=tool.logger.name)

    with pytest.raises(RuntimeError):
        tool._handle_error("delete\nvm", RuntimeError("bad\r\nsecret"))

    assert "deletevm" in caplog.text
    assert "badsecret" in caplog.text
    assert "delete\nvm" not in caplog.text
    assert "bad\r\nsecret" not in caplog.text


def test_rate_limiter_sweeps_expired_empty_buckets():
    middleware = RateLimitMiddleware(FastAPI(), requests_per_minute=10)
    middleware._buckets = {
        "stale-a": deque([1.0]),
        "stale-b": deque([2.0]),
        "active": deque([99.0]),
    }

    middleware._sweep_buckets(window_start=60.0)

    assert set(middleware._buckets) == {"active"}


def test_container_command_logging_redacts_command(caplog):
    proxmox = MagicMock()
    proxmox.nodes.return_value.lxc.return_value.status.current.get.return_value = {
        "status": "running"
    }
    ssh_cfg = MagicMock()
    ssh_cfg.user = "root"
    ssh_cfg.port = 22
    ssh_cfg.key_file = "/fake/key"
    ssh_cfg.password = None
    ssh_cfg.host_overrides = {}
    ssh_cfg.use_sudo = False
    ssh_cfg.known_hosts_file = None
    ssh_cfg.strict_host_key_checking = True
    ssh_cfg.prefer_ssh_client = False
    manager = ContainerConsoleManager(proxmox, ssh_cfg)

    stdout = MagicMock()
    stdout.read.return_value = b"secret-output\n"
    stdout.channel.recv_exit_status.return_value = 0
    stderr = MagicMock()
    stderr.read.return_value = b""
    client = MagicMock()
    client.exec_command.return_value = (MagicMock(), stdout, stderr)

    caplog.set_level(logging.INFO, logger="proxmox-mcp.ct-console")
    with patch("proxmox_mcp.tools.console.container_manager.paramiko.SSHClient", return_value=client):
        result = manager.execute_command("pve1", "101", "echo super-secret")

    assert result["output"] == "secret-output\n"
    assert "super-secret" not in caplog.text
    assert "secret-output" not in caplog.text


def test_container_system_ssh_logging_redacts_command(caplog):
    proxmox = MagicMock()
    proxmox.nodes.return_value.lxc.return_value.status.current.get.return_value = {
        "status": "running"
    }
    ssh_cfg = MagicMock()
    ssh_cfg.user = "root"
    ssh_cfg.port = 22
    ssh_cfg.key_file = "/fake/key"
    ssh_cfg.password = None
    ssh_cfg.host_overrides = {}
    ssh_cfg.use_sudo = False
    ssh_cfg.known_hosts_file = None
    ssh_cfg.strict_host_key_checking = True
    ssh_cfg.prefer_ssh_client = True
    manager = ContainerConsoleManager(proxmox, ssh_cfg)

    completed = MagicMock()
    completed.returncode = 0
    completed.stdout = "secret-output\n"
    completed.stderr = ""

    caplog.set_level(logging.DEBUG, logger="proxmox-mcp.ct-console")
    with patch(
        "proxmox_mcp.tools.console.container_manager.subprocess.run",
        return_value=completed,
    ):
        result = manager.execute_command("pve1", "101", "echo super-secret")

    assert result["output"] == "secret-output\n"
    assert "super-secret" not in caplog.text
    assert "secret-output" not in caplog.text
    assert "pct exec" not in caplog.text


def test_vm_command_logging_redacts_command_and_output(caplog):
    proxmox = MagicMock()
    proxmox.nodes.return_value.qemu.return_value.status.current.get.return_value = {
        "status": "running"
    }
    endpoint = Mock()
    exec_endpoint = Mock()
    exec_endpoint.post.return_value = {"pid": 123}
    status_endpoint = Mock()
    status_endpoint.get.return_value = {
        "out-data": "secret-output",
        "err-data": "secret-error",
        "exitcode": 0,
        "exited": 1,
    }
    endpoint.side_effect = lambda action: exec_endpoint if action == "exec" else status_endpoint
    proxmox.nodes.return_value.qemu.return_value.agent = endpoint
    manager = VMConsoleManager(proxmox)

    caplog.set_level(logging.DEBUG, logger="proxmox-mcp.vm-console")
    result = asyncio.run(manager.execute_command("pve1", "100", "echo super-secret"))

    assert result["output"] == "secret-output"
    assert "super-secret" not in caplog.text
    assert "secret-output" not in caplog.text
    assert "secret-error" not in caplog.text
