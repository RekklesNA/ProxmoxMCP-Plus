"""
Tests for the Proxmox MCP server.
"""

import os
import json
import pytest
from unittest.mock import Mock, patch

from mcp.server.fastmcp.exceptions import ToolError
from proxmox_mcp.server import ProxmoxMCPServer

@pytest.fixture
def mock_env_vars(tmp_path):
    """Fixture to set up test environment variables."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "proxmox": {
            "host": "test.proxmox.com",
            "port": 8006,
            "verify_ssl": True,
            "service": "PVE",
        },
        "auth": {
            "user": "test@pve",
            "token_name": "test_token",
            "token_value": "test_value",
        },
        "logging": {
            "level": "DEBUG",
        },
    }))

    env_vars = {
        "PROXMOX_MCP_CONFIG": str(config_path),
        "PROXMOX_HOST": "test.proxmox.com",
        "PROXMOX_USER": "test@pve",
        "PROXMOX_TOKEN_NAME": "test_token",
        "PROXMOX_TOKEN_VALUE": "test_value",
        "LOG_LEVEL": "DEBUG",
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars

@pytest.fixture
def mock_proxmox():
    """Fixture to mock ProxmoxAPI."""
    with patch("proxmox_mcp.core.proxmox.ProxmoxAPI") as mock:
        mock.return_value.nodes.get.return_value = [
            {"node": "node1", "status": "online"},
            {"node": "node2", "status": "online"}
        ]
        mock.return_value.nodes.return_value.status.get.return_value = {
            "status": "online",
            "uptime": 0,
            "cpuinfo": {"cpus": 4},
            "memory": {"used": 0, "total": 0},
        }
        yield mock

@pytest.fixture
def server(mock_env_vars, mock_proxmox):
    """Fixture to create a ProxmoxMCPServer instance."""
    return ProxmoxMCPServer(os.environ["PROXMOX_MCP_CONFIG"])

def test_server_initialization(server, mock_proxmox):
    """Test server initialization with environment variables."""
    assert server.config.proxmox.host == "test.proxmox.com"
    assert server.config.auth.user == "test@pve"
    assert server.config.auth.token_name == "test_token"
    assert server.config.auth.token_value == "test_value"
    assert server.config.logging.level == "DEBUG"

    mock_proxmox.assert_called_once()

@pytest.mark.asyncio
async def test_list_tools(server):
    """Test listing available tools. Config has no ssh section, so execute_container_command must be absent."""
    tools = await server.mcp.list_tools()

    assert len(tools) > 0
    tool_names = [tool.name for tool in tools]
    assert "get_nodes" in tool_names
    assert "get_vms" in tool_names
    assert "get_containers" in tool_names
    assert "execute_vm_command" in tool_names
    assert "update_container_resources" in tool_names
    assert "execute_container_command" not in tool_names


@pytest.mark.asyncio
async def test_list_tools_with_ssh_config(mock_proxmox, tmp_path):
    """execute_container_command is registered only when an ssh section is present."""
    config_path = tmp_path / "config_ssh.json"
    config_path.write_text(json.dumps({
        "proxmox": {"host": "test.proxmox.com", "port": 8006, "verify_ssl": True, "service": "PVE"},
        "auth": {"user": "test@pve", "token_name": "test_token", "token_value": "test_value"},
        "logging": {"level": "DEBUG"},
        "ssh": {"user": "mcp-agent", "key_file": "/home/user/.ssh/proxmox_key"},
    }))

    with patch.dict(os.environ, {"PROXMOX_MCP_CONFIG": str(config_path)}):
        ssh_server = ProxmoxMCPServer(str(config_path))

    tools = await ssh_server.mcp.list_tools()
    tool_names = [tool.name for tool in tools]
    assert "execute_container_command" in tool_names

@pytest.mark.asyncio
async def test_get_nodes(server, mock_proxmox):
    """Test get_nodes tool."""
    mock_proxmox.return_value.nodes.get.return_value = [
        {"node": "node1", "status": "online"},
        {"node": "node2", "status": "online"}
    ]
    mock_proxmox.return_value.nodes.return_value.status.get.return_value = {
        "status": "online",
        "uptime": 120,
        "cpuinfo": {"cpus": 4},
        "memory": {"used": 1024, "total": 4096},
    }
    response = await server.mcp.call_tool("get_nodes", {})
    text = response[0].text
    assert "node1" in text
    assert "node2" in text

@pytest.mark.asyncio
async def test_get_node_status_missing_parameter(server):
    """Test get_node_status tool with missing parameter."""
    with pytest.raises(ToolError, match="Field required"):
        await server.mcp.call_tool("get_node_status", {})

@pytest.mark.asyncio
async def test_get_node_status(server, mock_proxmox):
    """Test get_node_status tool with valid parameter."""
    mock_proxmox.return_value.nodes.return_value.status.get.return_value = {
        "status": "running",
        "uptime": 123456
    }

    response = await server.mcp.call_tool("get_node_status", {"node": "node1"})
    text = response[0].text
    assert "Node: node1" in text
    assert "Status: RUNNING" in text

@pytest.mark.asyncio
async def test_get_node_status_offline_fallback(server, mock_proxmox):
    """Test get_node_status returns offline fallback when node is unreachable."""
    proxmox = mock_proxmox.return_value
    proxmox.nodes.return_value.status.get.side_effect = Exception("No route to host")
    proxmox.nodes.get.return_value = [
        {"node": "maserati", "status": "offline", "mem": 0, "maxmem": 0},
    ]

    response = await server.mcp.call_tool("get_node_status", {"node": "maserati"})
    text = response[0].text
    assert "Node: maserati" in text
    assert "Status: OFFLINE" in text

@pytest.mark.asyncio
async def test_get_vms(server, mock_proxmox):
    """Test get_vms tool."""
    mock_proxmox.return_value.nodes.get.return_value = [{"node": "node1", "status": "online"}]
    mock_proxmox.return_value.nodes.return_value.qemu.get.return_value = [
        {"vmid": "100", "name": "vm1", "status": "running"},
        {"vmid": "101", "name": "vm2", "status": "stopped"}
    ]

    response = await server.mcp.call_tool("get_vms", {})
    text = response[0].text
    assert "vm1" in text
    assert "vm2" in text

@pytest.mark.asyncio
async def test_get_vms_skips_offline_node(server, mock_proxmox):
    """Test get_vms tool skips nodes that error."""
    proxmox = mock_proxmox.return_value
    proxmox.nodes.get.return_value = [
        {"node": "node1", "status": "online"},
        {"node": "node2", "status": "offline"},
    ]

    node1_api = Mock()
    node1_api.qemu.get.return_value = [
        {"vmid": "100", "name": "vm1", "status": "running"},
    ]
    node1_api.qemu.return_value.config.get.return_value = {"cores": 2}

    node2_api = Mock()
    node2_api.qemu.get.side_effect = Exception("offline")

    def nodes_side_effect(node_name=None):
        if node_name == "node1":
            return node1_api
        if node_name == "node2":
            return node2_api
        return Mock()

    proxmox.nodes.side_effect = nodes_side_effect

    response = await server.mcp.call_tool("get_vms", {})
    text = response[0].text
    assert "vm1" in text
    assert "node1" in text
    assert "node2" not in text

@pytest.mark.asyncio
async def test_get_containers(server, mock_proxmox):
    """Test get_containers tool."""
    mock_proxmox.return_value.nodes.get.return_value = [{"node": "node1", "status": "online"}]
    mock_proxmox.return_value.nodes.return_value.lxc.get.return_value = [
        {"vmid": "200", "name": "container1", "status": "running"},
        {"vmid": "201", "name": "container2", "status": "stopped"}
    ]

    response = await server.mcp.call_tool("get_containers", {"payload": {"format_style": "json"}})
    result = json.loads(response[0].text)
    assert len(result) > 0
    assert result[0]["name"] == "container1"
    assert result[1]["name"] == "container2"

@pytest.mark.asyncio
async def test_get_containers_skips_offline_node(server, mock_proxmox):
    """Test get_containers tool skips nodes that error."""
    proxmox = mock_proxmox.return_value
    proxmox.nodes.get.return_value = [
        {"node": "node1", "status": "online"},
        {"node": "node2", "status": "offline"},
    ]

    node1_api = Mock()
    node1_api.lxc.get.return_value = [
        {"vmid": "200", "name": "container1", "status": "running"},
    ]

    node2_api = Mock()
    node2_api.lxc.get.side_effect = Exception("offline")

    def nodes_side_effect(node_name=None):
        if node_name == "node1":
            return node1_api
        if node_name == "node2":
            return node2_api
        return Mock()

    proxmox.nodes.side_effect = nodes_side_effect

    response = await server.mcp.call_tool("get_containers", {"payload": {}})
    text = response[0].text
    assert "container1" in text
    assert "node1" in text
    assert "node2" not in text

@pytest.mark.asyncio
async def test_update_container_resources(server, mock_proxmox):
    """Test update_container_resources tool."""
    mock_proxmox.return_value.nodes.get.return_value = [{"node": "node1", "status": "online"}]
    mock_proxmox.return_value.nodes.return_value.lxc.get.return_value = [
        {"vmid": "200", "name": "container1", "status": "running"}
    ]

    ct_api = mock_proxmox.return_value.nodes.return_value.lxc.return_value
    ct_api.config.put.return_value = {}
    ct_api.resize.put.return_value = {}

    response = await server.mcp.call_tool(
        "update_container_resources",
        {"selector": "node1:200", "cores": 2, "memory": 512, "swap": 256, "disk_gb": 1, "format_style": "json"},
    )
    result = json.loads(response[0].text)

    assert result[0]["ok"] is True
    ct_api.config.put.assert_called_with(cores=2, memory=512, swap=256)
    ct_api.resize.put.assert_called_with(disk="rootfs", size="+1G")

@pytest.mark.asyncio
async def test_get_storage(server, mock_proxmox):
    """Test get_storage tool."""
    mock_proxmox.return_value.storage.get.return_value = [
        {"storage": "local", "type": "dir"},
        {"storage": "ceph", "type": "rbd"}
    ]
    mock_proxmox.return_value.nodes.return_value.storage.return_value.status.get.return_value = {
        "used": 0,
        "total": 0,
        "avail": 0,
    }

    response = await server.mcp.call_tool("get_storage", {})
    text = response[0].text
    assert "local" in text
    assert "ceph" in text

@pytest.mark.asyncio
async def test_list_isos_skips_offline_node(server, mock_proxmox):
    """Test list_isos skips nodes that error."""
    proxmox = mock_proxmox.return_value
    proxmox.nodes.get.return_value = [
        {"node": "node1", "status": "online"},
        {"node": "node2", "status": "offline"},
    ]

    node1_api = Mock()
    node1_api.storage.get.return_value = [
        {"storage": "local", "content": "iso"},
    ]
    node1_api.storage.return_value.content.get.return_value = [
        {"volid": "local:iso/test.iso", "size": 1024},
    ]

    node2_api = Mock()
    node2_api.storage.get.side_effect = Exception("offline")

    def nodes_side_effect(node_name=None):
        if node_name == "node1":
            return node1_api
        if node_name == "node2":
            return node2_api
        return Mock()

    proxmox.nodes.side_effect = nodes_side_effect

    response = await server.mcp.call_tool("list_isos", {})
    text = response[0].text
    assert "test.iso" in text
    assert "node1" in text
    assert "node2" not in text

@pytest.mark.asyncio
async def test_list_backups_skips_offline_node(server, mock_proxmox):
    """Test list_backups skips nodes that error."""
    proxmox = mock_proxmox.return_value
    proxmox.nodes.get.return_value = [
        {"node": "node1", "status": "online"},
        {"node": "node2", "status": "offline"},
    ]

    node1_api = Mock()
    node1_api.storage.get.return_value = [
        {"storage": "local", "content": "backup"},
    ]
    node1_api.storage.return_value.content.get.return_value = [
        {"volid": "local:backup/vm-100.vma", "size": 2048, "ctime": 0, "vmid": 100},
    ]

    node2_api = Mock()
    node2_api.storage.get.side_effect = Exception("offline")

    def nodes_side_effect(node_name=None):
        if node_name == "node1":
            return node1_api
        if node_name == "node2":
            return node2_api
        return Mock()

    proxmox.nodes.side_effect = nodes_side_effect

    response = await server.mcp.call_tool("list_backups", {})
    text = response[0].text
    assert "vm-100.vma" in text
    assert "node1" in text
    assert "node2" not in text

@pytest.mark.asyncio
async def test_get_cluster_status(server, mock_proxmox):
    """Test get_cluster_status tool."""
    mock_proxmox.return_value.cluster.status.get.return_value = [
        {"type": "cluster", "name": "test-cluster", "quorate": 1},
        {"type": "node", "name": "node1"},
        {"type": "node", "name": "node2"},
    ]

    response = await server.mcp.call_tool("get_cluster_status", {})
    text = response[0].text
    assert "test-cluster" in text
    assert "Quorum: OK" in text
    assert "Nodes: 2" in text

@pytest.mark.asyncio
async def test_execute_vm_command_success(server, mock_proxmox):
    """Test successful VM command execution."""
    # Mock VM status check
    mock_proxmox.return_value.nodes.return_value.qemu.return_value.status.current.get.return_value = {
        "status": "running"
    }
    # Mock command execution
    exec_endpoint = Mock()
    exec_endpoint.post.return_value = {"pid": 123}
    status_endpoint = Mock()
    status_endpoint.get.return_value = {
        "out-data": "command output",
        "err-data": "",
        "exitcode": 0,
        "exited": 1,
    }
    mock_proxmox.return_value.nodes.return_value.qemu.return_value.agent.side_effect = (
        lambda action: exec_endpoint if action == "exec" else status_endpoint
    )

    response = await server.mcp.call_tool("execute_vm_command", {
        "node": "node1",
        "vmid": "100",
        "command": "ls -l"
    })
    text = response[0].text
    assert "Console Command Result" in text
    assert "Status: SUCCESS" in text
    assert "command output" in text

@pytest.mark.asyncio
async def test_execute_vm_command_missing_parameters(server):
    """Test VM command execution with missing parameters."""
    with pytest.raises(ToolError):
        await server.mcp.call_tool("execute_vm_command", {})

@pytest.mark.asyncio
async def test_execute_vm_command_vm_not_running(server, mock_proxmox):
    """Test VM command execution when VM is not running."""
    mock_proxmox.return_value.nodes.return_value.qemu.return_value.status.current.get.return_value = {
        "status": "stopped"
    }

    with pytest.raises(ToolError, match="not running"):
        await server.mcp.call_tool("execute_vm_command", {
            "node": "node1",
            "vmid": "100",
            "command": "ls -l"
        })

@pytest.mark.asyncio
async def test_execute_vm_command_with_error(server, mock_proxmox):
    """Test VM command execution with command error."""
    # Mock VM status check
    mock_proxmox.return_value.nodes.return_value.qemu.return_value.status.current.get.return_value = {
        "status": "running"
    }
    # Mock command execution with error
    exec_endpoint = Mock()
    exec_endpoint.post.return_value = {"pid": 456}
    status_endpoint = Mock()
    status_endpoint.get.return_value = {
        "out-data": "",
        "err-data": "command not found",
        "exitcode": 1,
        "exited": 1,
    }
    mock_proxmox.return_value.nodes.return_value.qemu.return_value.agent.side_effect = (
        lambda action: exec_endpoint if action == "exec" else status_endpoint
    )

    response = await server.mcp.call_tool("execute_vm_command", {
        "node": "node1",
        "vmid": "100",
        "command": "invalid-command"
    })
    text = response[0].text
    assert "Console Command Result" in text
    assert "Status: SUCCESS" in text
    assert "command not found" in text

@pytest.mark.asyncio
async def test_start_vm(server, mock_proxmox):
    """Test start_vm tool."""
    mock_proxmox.return_value.nodes.return_value.qemu.return_value.status.current.get.return_value = {
        "status": "stopped"
    }
    mock_proxmox.return_value.nodes.return_value.qemu.return_value.status.start.post.return_value = "UPID:taskid"

    response = await server.mcp.call_tool("start_vm", {"node": "node1", "vmid": "100"})
    assert "start initiated successfully" in response[0].text
