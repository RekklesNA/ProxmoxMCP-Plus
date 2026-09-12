"""Unit tests for the VM provisioning tools: get_next_vmid, update_vm_config, get_vm_ip_addresses."""

import json
import urllib.parse
from unittest.mock import Mock

import pytest

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
    proxmox.nodes.return_value.qemu.return_value.config.get.side_effect = Exception("Configuration file 'nodes/pve/qemu-server/105.conf' does not exist")
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


def test_get_vm_ip_addresses_explains_a_silent_guest_agent():
    proxmox = Mock()
    proxmox.nodes.return_value.qemu.return_value.agent.return_value.get.side_effect = Exception(
        "QEMU guest agent is not running"
    )
    tools = VMTools(proxmox)
    with pytest.raises(ValueError, match="Guest agent on VM 105 did not answer"):
        tools.get_vm_ip_addresses("pve", "105")
