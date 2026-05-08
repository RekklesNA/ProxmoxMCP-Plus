import sys

import pytest

from proxmox_mcp.docker_entrypoint import build_command


def test_docker_entrypoint_defaults_to_openapi():
    env = {"API_HOST": "127.0.0.1", "API_PORT": "8812"}

    command = build_command(environ=env)

    assert command == [
        sys.executable,
        "-m",
        "proxmox_mcp.openapi_proxy",
        "--host",
        "127.0.0.1",
        "--port",
        "8812",
        "--",
        sys.executable,
        "-m",
        "proxmox_mcp.server",
    ]


def test_docker_entrypoint_mcp_http_sets_streamable_defaults():
    env = {}

    command = build_command("mcp-http", environ=env)

    assert command == [sys.executable, "-m", "proxmox_mcp.server"]
    assert env["MCP_HOST"] == "0.0.0.0"
    assert env["MCP_PORT"] == "8000"
    assert env["MCP_TRANSPORT"] == "STREAMABLE_HTTP"


def test_docker_entrypoint_rejects_unknown_mode():
    with pytest.raises(ValueError, match="Unsupported PROXMOX_MCP_MODE"):
        build_command("unknown", environ={})
