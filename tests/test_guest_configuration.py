"""Guest provisioning regressions: payloads, preservation and policy boundaries."""
import json
from unittest.mock import Mock

import pytest

from proxmox_mcp.tools.containers import ContainerTools
from proxmox_mcp.tools.guest_config import container_network, vm_media
from proxmox_mcp.tools.vm import VMTools


def test_vm_mount_eject_and_bridge_preserve_other_devices():
    api = Mock()
    config = api.nodes.return_value.qemu.return_value.config
    config.get.return_value = {"ide2": "local-lvm:cloudinit,media=cdrom", "net0": "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,tag=20,firewall=1", "digest": "abc"}
    result = VMTools(api).update_vm_config("pve", "101", iso_volume="local:iso/debian.iso", network_bridge="vmbr2", boot_order="ide3;scsi0")
    config.put.assert_called_once_with(ide3="local:iso/debian.iso,media=cdrom", net0="virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr2,tag=20,firewall=1", boot="order=ide3;scsi0", digest="abc")
    assert "ide2" not in json.loads(result[0].text)["applied"]
    config.reset_mock()
    VMTools(api).update_vm_config("pve", "101", iso_volume="none")
    config.put.assert_called_once_with(ide3="none,media=cdrom", digest="abc")


@pytest.mark.parametrize("current", ["local:disk.qcow2", "local:cloudinit,media=cdrom"])
def test_vm_rejects_overwriting_data_or_cloudinit(current):
    api = Mock()
    config = api.nodes.return_value.qemu.return_value.config
    config.get.return_value = {"ide3": current}
    with pytest.raises(ValueError, match="Refusing to replace"):
        VMTools(api).update_vm_config("pve", "101", iso_volume="local:iso/debian.iso")
    config.put.assert_not_called()


@pytest.mark.parametrize("kwargs", [{"iso_volume": "/etc/passwd"}, {"iso_volume": "local:iso/foo.iso,backup=0"}, {"iso_volume": "local:iso/a.iso", "cdrom_device": "scsi0,delete=1"}, {"boot_order": "scsi0;scsi0"}, {"boot_order": "bad"}])
def test_invalid_media_options(kwargs):
    with pytest.raises(ValueError):
        vm_media(kwargs.get("iso_volume"), kwargs.get("cdrom_device", "ide3"), kwargs.get("boot_order"))


@pytest.mark.parametrize("iso", [None, "local:iso/debian.iso"])
def test_vm_creation_adds_iso_only_when_requested(iso):
    api = Mock()
    api.nodes.return_value.qemu.return_value.config.get.side_effect = Exception("does not exist")
    api.nodes.return_value.storage.get.return_value = [{"storage":"local","content":"images,iso","type":"dir"}]
    VMTools(api).create_vm("pve", "101", "test", 1, 1024, 10, iso_volume=iso)
    payload = api.nodes.return_value.qemu.create.call_args.kwargs
    assert payload["ide2"] == "local:cloudinit"
    assert payload["boot"] == ("order=ide3;scsi0" if iso else "order=scsi0")
    assert ("ide3" in payload) == bool(iso)


def test_container_network_preserves_unspecified_fields_and_digest():
    api = Mock()
    config = api.nodes.return_value.lxc.return_value.config
    config.get.return_value = {"net1": "name=eth1,bridge=vmbr0,ip=dhcp,hwaddr=AA:BB:CC:DD:EE:FF,tag=42,firewall=1,mtu=9000", "digest": "abc"}
    ContainerTools(api).update_container_network("pve", "101", network_bridge="vmbr2", ip="10.2.0.5/24", gw="10.2.0.1", interface="net1")
    payload = config.put.call_args.kwargs
    assert payload["digest"] == "abc"
    for fragment in ["name=eth1", "bridge=vmbr2", "ip=10.2.0.5/24", "gw=10.2.0.1", "hwaddr=AA:BB:CC:DD:EE:FF", "tag=42", "firewall=1", "mtu=9000"]:
        assert fragment in payload["net1"].split(",")


def test_dynamic_ip_removes_stale_gateway_and_ipv6_is_independent():
    result = container_network("name=eth0,bridge=vmbr0,ip=10.0.0.2/24,gw=10.0.0.1,ip6=fd00::2/64,gw6=fd00::1", ip="dhcp")
    assert ",gw=" not in result
    assert "gw6=fd00::1" in result
    assert "ip=dhcp" in result
    assert "gw6=" not in container_network(result, gw6="")


@pytest.mark.parametrize("kwargs", [{"ip":"10.0.0.2"}, {"ip":"fd00::2/64"}, {"ip6":"10.0.0.2/24"}, {"gw":"10.0.0.1"}, {"ip":"dhcp", "gw":"10.0.0.1"}, {"network_bridge":"vmbr0,tag=1"}, {"gw6":"10.0.0.1"}])
def test_invalid_network_inputs(kwargs):
    with pytest.raises(ValueError):
        container_network(**kwargs)


@pytest.mark.parametrize("kwargs", [{}, {"interface":"net32", "ip":"dhcp"}])
def test_invalid_network_edit_does_not_write(kwargs):
    api = Mock()
    with pytest.raises(ValueError):
        ContainerTools(api).update_container_network("pve", "101", **kwargs)
    api.nodes.assert_not_called()


@pytest.mark.parametrize("static", [False, True])
def test_create_container_retains_dhcp_default_and_supports_static(static):
    api = Mock()
    api.nodes.get.return_value = [{"node":"pve"}]
    tools = ContainerTools(api)
    tools._list_ct_pairs = Mock(return_value=[])
    kwargs = {"ip":"10.0.0.2/24", "gw":"10.0.0.1", "ip6":"fd00::2/64", "gw6":"fd00::1"} if static else {}
    tools.create_container("pve", "101", "local:vztmpl/debian.tar.zst", storage="local-lvm", network_bridge="vmbr2", **kwargs)
    network = api.nodes.return_value.lxc.create.call_args.kwargs["net0"]
    assert "bridge=vmbr2" in network
    assert ("ip=10.0.0.2/24" if static else "ip=dhcp") in network
    if static:
        assert "gw6=fd00::1" in network
