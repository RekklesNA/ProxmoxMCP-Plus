"""Unit tests for the VM provisioning tools: get_next_vmid, update_vm_config, get_vm_ip_addresses."""

import json
import urllib.parse
from unittest.mock import Mock, patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from proxmoxer.core import ResourceException

from proxmox_mcp.server import ProxmoxMCPServer
from proxmox_mcp.tools.vm import VMTools

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGtestkeytestkeytestkeytestkeytestkeytestkey ci@host"


def _payload(content):
    return json.loads(content[0].text)


def test_get_next_vmid_returns_cluster_nextid():
    proxmox = Mock()
    proxmox.cluster.nextid.get.return_value = 105
    tools = VMTools(proxmox)

    assert _payload(tools.get_next_vmid()) == {"vmid": "105"}


def test_update_vm_config_sends_only_supplied_fields_and_encodes_sshkeys():
    proxmox = Mock()
    vm_api = proxmox.nodes.return_value.qemu.return_value
    vm_api.config.get.return_value = {"name": "clone-105"}
    tools = VMTools(proxmox)

    result = _payload(
        tools.update_vm_config(
            "pve", "105", memory=4096, ciuser="hola", sshkeys=f"{KEY}\n\n{KEY}\n", ipconfig0="ip=dhcp"
        )
    )

    vm_api.config.put.assert_called_once_with(
        memory=4096,
        ciuser="hola",
        sshkeys=urllib.parse.quote(f"{KEY}\n{KEY}", safe=""),
        ipconfig0="ip=dhcp",
    )
    assert result["applied"]["sshkeys"] == "2 key(s)"
    assert result["applied"]["memory"] == 4096
    assert any("next boot" in note for note in result["notes"])
    assert any("pending" in note for note in result["notes"])


def test_update_vm_config_refuses_empty_change_set():
    tools = VMTools(Mock())
    with pytest.raises(ValueError, match="at least one setting"):
        tools.update_vm_config("pve", "105")


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"memory": 8}, "memory must be at least 16"),
        ({"cores": 0}, "cores must be at least 1"),
        ({"sshkeys": "not a key"}, "OpenSSH public keys"),
        ({"sshkeys": "   \n"}, "at least one public key"),
        ({"ciuser": "Root User"}, "valid Unix user name"),
        ({"ipconfig0": "10.0.0.5"}, "ipconfig0 must look like"),
        ({"name": "bad_name!"}, "valid DNS label"),
    ],
)
def test_update_vm_config_validates_inputs_before_calling_proxmox(kwargs, message):
    proxmox = Mock()
    tools = VMTools(proxmox)
    with pytest.raises(ValueError, match=message):
        tools.update_vm_config("pve", "105", **kwargs)
    proxmox.nodes.return_value.qemu.return_value.config.put.assert_not_called()


def test_update_vm_config_reports_missing_vm():
    proxmox = Mock()
    proxmox.nodes.return_value.qemu.return_value.config.put.side_effect = Exception("Configuration file 'nodes/pve/qemu-server/105.conf' does not exist")
    tools = VMTools(proxmox)
    with pytest.raises(ValueError, match="VM 105 not found on node pve"):
        tools.update_vm_config("pve", "105", memory=2048)


def test_get_vm_ip_addresses_flattens_guest_agent_interfaces():
    proxmox = Mock()
    vm_api = proxmox.nodes.return_value.qemu.return_value
    vm_api.agent.return_value.get.return_value = {
        "result": [
            {"name": "lo", "ip-addresses": [{"ip-address": "127.0.0.1", "ip-address-type": "ipv4", "prefix": 8}]},
            {
                "name": "eth0",
                "hardware-address": "bc:24:11:aa:bb:cc",
                "ip-addresses": [
                    {"ip-address": "fe80::be24:11ff:feaa:bbcc", "ip-address-type": "ipv6", "prefix": 64},
                    {"ip-address": "10.0.0.57", "ip-address-type": "ipv4", "prefix": 24},
                ],
            },
        ]
    }
    tools = VMTools(proxmox)

    result = _payload(tools.get_vm_ip_addresses("pve", "105"))

    vm_api.agent.assert_called_once_with("network-get-interfaces")
    assert result["primary_ip"] == "10.0.0.57"
    assert result["interfaces"] == [
        {"name": "eth0", "mac": "bc:24:11:aa:bb:cc", "ipv4": ["10.0.0.57"], "ipv6": ["fe80::be24:11ff:feaa:bbcc"]}
    ]


@pytest.mark.parametrize("message", [
    "QEMU guest agent is not running",
    "QEMU guest agent is not enabled",
    "VM 105 is not running",
    "VM 105 qmp command 'guest-network-get-interfaces' failed - got timeout",
])
def test_get_vm_ip_addresses_explains_a_silent_guest_agent(message):
    proxmox = Mock()
    proxmox.nodes.return_value.qemu.return_value.agent.return_value.get.side_effect = Exception(message)
    tools = VMTools(proxmox)
    with pytest.raises(ValueError, match="Guest agent on VM 105 did not answer"):
        tools.get_vm_ip_addresses("pve", "105")


def test_update_vm_config_does_not_require_config_read_permission():
    proxmox = Mock()
    config_api = proxmox.nodes.return_value.qemu.return_value.config
    config_api.get.side_effect = ResourceException(
        403, "Forbidden", "Permission check failed (/vms/105, VM.Audit)"
    )

    result = _payload(VMTools(proxmox).update_vm_config("pve", "105", memory=4096))

    assert result["applied"] == {"memory": 4096}
    config_api.get.assert_not_called()
    config_api.put.assert_called_once_with(memory=4096)


def test_update_vm_config_preserves_write_permission_error():
    proxmox = Mock()
    config_api = proxmox.nodes.return_value.qemu.return_value.config
    config_api.put.side_effect = ResourceException(
        403, "Forbidden", "Permission check failed (/vms/105, VM.Config.Memory)"
    )
    with pytest.raises(RuntimeError, match=r"403.*VM.Config.Memory"):
        VMTools(proxmox).update_vm_config("pve", "105", memory=4096)
    config_api.get.assert_not_called()


@pytest.mark.parametrize("status, reason, detail", [
    (403, "Forbidden", "Permission check failed (/vms/105, VM.GuestAgent.Audit)"),
    (401, "Unauthorized", "Authentication failed for /agent/network-get-interfaces"),
    (500, "Internal Server Error", "Unexpected failure in /agent/network-get-interfaces"),
])
def test_get_vm_ip_addresses_preserves_api_errors(status, reason, detail):
    proxmox = Mock()
    proxmox.nodes.return_value.qemu.return_value.agent.return_value.get.side_effect = (
        ResourceException(status, reason, detail)
    )
    with pytest.raises(RuntimeError) as exc_info:
        VMTools(proxmox).get_vm_ip_addresses("pve", "105")
    assert str(status) in str(exc_info.value)
    assert detail in str(exc_info.value)
    assert "did not answer" not in str(exc_info.value)


@pytest.fixture
def provisioning_server(tmp_path):
    path = tmp_path / "provisioning.json"
    strict_policy = {
        "high_risk_mode": "enforce",
        "high_risk_require_approval_token": True,
        "high_risk_approval_token": "strict-approval",
    }
    path.write_text(json.dumps({
        "targets": {
            "default": {
                "host": "default.invalid",
                "auth": {"user": "u", "token_name": "t", "token_value": "v"},
            },
            "strict": {
                "host": "strict.invalid",
                "auth": {"user": "u", "token_name": "t", "token_value": "v"},
                "command_policy": strict_policy,
            },
            "readonly": {
                "host": "readonly.invalid", "readonly": True,
                "auth": {"user": "u", "token_name": "t", "token_value": "v"},
                "command_policy": strict_policy,
            },
        },
        "jobs": {"sqlite_path": str(tmp_path / "jobs.sqlite3")},
    }))
    apis = {host: Mock() for host in ("default.invalid", "strict.invalid", "readonly.invalid")}
    with patch("proxmox_mcp.core.proxmox.ProxmoxAPI", side_effect=lambda host, **kw: apis[host]):
        server = ProxmoxMCPServer(str(path))
        try:
            for api in apis.values():
                api.reset_mock()
            yield server, apis
        finally:
            server.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("custom_operations", [False, True])
@pytest.mark.parametrize("token", [None, "wrong-approval", "strict-approval"])
async def test_update_vm_config_enforces_selected_target_approval(provisioning_server, custom_operations, token):
    server, apis = provisioning_server
    if custom_operations:
        server.target_command_policies["strict"].config.high_risk_operations = ["update_vm_config"]
    args = {"target": "strict", "node": "pve", "vmid": "105", "sshkeys": KEY}
    if token is not None:
        args["approval_token"] = token
    if token != "strict-approval":
        with pytest.raises(ToolError, match="requires an approval token"):
            await server.mcp.call_tool("update_vm_config", args)
        apis["strict.invalid"].nodes.assert_not_called()
    else:
        result = _payload(await server.mcp.call_tool("update_vm_config", args))
        assert result["applied"] == {"sshkeys": "1 key(s)"}
        apis["strict.invalid"].nodes.return_value.qemu.return_value.config.put.assert_called_once_with(
            sshkeys=urllib.parse.quote(KEY, safe="")
        )
        assert token not in json.dumps(result)
    apis["default.invalid"].nodes.assert_not_called()
    apis["readonly.invalid"].nodes.assert_not_called()


@pytest.mark.asyncio
async def test_update_vm_config_default_policy_remains_usable_without_token(provisioning_server):
    server, apis = provisioning_server
    result = _payload(await server.mcp.call_tool(
        "update_vm_config", {"target": "default", "node": "pve", "vmid": "105", "memory": 4096}
    ))
    assert result["applied"] == {"memory": 4096}
    apis["default.invalid"].nodes.return_value.qemu.return_value.config.put.assert_called_once_with(memory=4096)
    apis["strict.invalid"].nodes.assert_not_called()


@pytest.mark.asyncio
async def test_update_vm_config_approval_cannot_override_readonly_target(provisioning_server):
    server, apis = provisioning_server
    with pytest.raises(ToolError, match="read-only"):
        await server.mcp.call_tool("update_vm_config", {
            "target": "readonly", "node": "pve", "vmid": "105", "memory": 4096,
            "approval_token": "strict-approval",
        })
    apis["readonly.invalid"].nodes.assert_not_called()


@pytest.mark.asyncio
async def test_provisioning_reads_remain_available_on_readonly_target(provisioning_server):
    server, apis = provisioning_server
    api = apis["readonly.invalid"]
    api.cluster.nextid.get.return_value = 105
    api.nodes.return_value.qemu.return_value.agent.return_value.get.return_value = {"result": []}
    assert _payload(await server.mcp.call_tool("get_next_vmid", {"target": "readonly"})) == {"vmid": "105"}
    assert _payload(await server.mcp.call_tool(
        "get_vm_ip_addresses", {"target": "readonly", "node": "pve", "vmid": "105"}
    ))["interfaces"] == []
