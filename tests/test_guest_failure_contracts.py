"""Guest configuration and guest-agent failure contracts."""

import json
from unittest.mock import Mock, AsyncMock

import pytest

from proxmox_mcp.tools.vm import VMTools, _as_dict
from proxmox_mcp.tools.containers import ContainerTools
from proxmox_mcp.tools.console.manager import VMConsoleManager


def test_vm_config_updates_validate_limits_and_preserve_scalar_options():
    api = Mock()
    tool = VMTools(api)
    result = tool.update_vm_config('pve', '100', cores=2, sockets=2, name='guest', nameserver='1.1.1.1', searchdomain='lab.invalid', tags='lab')
    assert api.nodes.return_value.qemu.return_value.config.put.call_args.kwargs == dict(cores=2, sockets=2, name='guest', nameserver='1.1.1.1', searchdomain='lab.invalid', tags='lab')
    assert 'guest' in result[0].text
    with pytest.raises(ValueError):
        tool.update_vm_config('pve', '100', sockets=0)
    api.nodes.return_value.qemu.return_value.config.get.return_value = {}
    with pytest.raises(ValueError):
        tool.update_vm_config('pve', '100', network_bridge='vmbr0')
    assert _as_dict({'data': {'a': 1}}) == {'a': 1}
    assert _as_dict(None) == {}
    api.cluster.nextid.get.side_effect = RuntimeError('offline')
    with pytest.raises(RuntimeError):
        tool.get_next_vmid()


def test_vm_inventory_fallback_and_missing_agent_addresses():
    api = Mock()
    tool = VMTools(api)
    api.cluster.resources.get.return_value = [{'type': 'qemu', 'node': 'pve', 'id': 'qemu/100'}, {'type': 'qemu', 'node': 'pve'}]
    assert '100' in tool.get_vms()[0].text
    tool._cache.clear()
    api.cluster.resources.get.side_effect = RuntimeError('offline')
    api.nodes.get.return_value = [{}, {'node': 'pve'}]
    api.nodes.return_value.qemu.get.return_value = [{'vmid': 100, 'name': 'guest', 'status': 'running'}]
    api.nodes.return_value.qemu.return_value.config.get.side_effect = RuntimeError('offline')
    assert 'guest' in tool.get_vms()[0].text
    tool._cache.clear()
    api.nodes.return_value.qemu.get.side_effect = RuntimeError('offline')
    with pytest.raises(RuntimeError, match='unavailable'):
        tool.get_vms()
    api.nodes.get.side_effect = RuntimeError('offline')
    with pytest.raises(RuntimeError):
        tool.get_vms()
    api.nodes.get.side_effect = None
    api.nodes.return_value.qemu.get.side_effect = None
    api.nodes.return_value.qemu.get.return_value = [{}]
    with pytest.raises(RuntimeError):
        tool.get_vms()
    api.nodes.return_value.qemu.return_value.agent.return_value.get.return_value = {'result': [None, {'name': 'eth0', 'ip-addresses': [{}]}]}
    assert json.loads(tool.get_vm_ip_addresses('pve', '100')[0].text)['interfaces'][0]['ipv4'] == []


@pytest.mark.parametrize('message, error', [('not found', ValueError), ('offline', RuntimeError)])
def test_vm_clone_and_delete_source_errors(message, error):
    api = Mock()
    api.nodes.return_value.qemu.return_value.status.current.get.side_effect = RuntimeError(message)
    tools = VMTools(api)
    with pytest.raises(error):
        tools.clone_vm('pve', '100', '200')
    with pytest.raises(error):
        tools.delete_vm('pve', '100')


def test_vm_clone_destination_and_request_errors():
    api = Mock()
    guest = api.nodes.return_value.qemu.return_value
    guest.status.current.get.return_value = {'name': 'source'}
    tools = VMTools(api)
    for value, error in [(None, ValueError), (RuntimeError('offline'), RuntimeError)]:
        guest.config.get.side_effect = value
        with pytest.raises(error):
            tools.clone_vm('pve', '100', '200')
    guest.config.get.side_effect = RuntimeError('does not exist')
    guest.clone.post.return_value = 'UPID:pve:clone'
    result = tools.clone_vm('pve', '100', '200', name='copy', target_node='other', storage='local', pool='lab', snapname='base')
    assert guest.clone.post.call_args.kwargs == dict(newid=200, full=1, name='copy', target='other', storage='local', pool='lab', snapname='base')
    assert all(value in result[0].text for value in ['local', 'lab', 'base'])
    guest.clone.post.side_effect = RuntimeError('offline')
    with pytest.raises(RuntimeError):
        tools.clone_vm('pve', '100', '200')


def test_vm_create_rejects_collisions_and_handles_raw_capability_storage():
    api = Mock()
    guest = api.nodes.return_value.qemu.return_value
    tool = VMTools(api)
    with pytest.raises(ValueError):
        tool.create_vm('pve', '100', 'guest', 1, 512, 10)
    guest.config.get.side_effect = RuntimeError('does not exist')
    api.nodes.return_value.storage.get.return_value = [{'storage': 'rbd', 'type': 'rbd', 'content': 'images'}]
    guest.create.return_value = 'UPID:pve:create'
    assert 'rbd' in tool.create_vm('pve', '100', 'guest', 1, 512, 10, network_bridge='vmbr2')[0].text
    assert api.nodes.return_value.qemu.create.call_args.kwargs['ide2'] == 'rbd:cloudinit'
    with pytest.raises(ValueError):
        tool.create_vm('pve', '100', 'guest', 1, 512, 10, iso_volume='none')
    guest.config.get.side_effect = RuntimeError('offline')
    with pytest.raises(RuntimeError):
        tool.create_vm('pve', '100', 'guest', 1, 512, 10)


def test_container_creation_config_and_console_failures():
    api = Mock()
    tools = ContainerTools(api)
    api.cluster.resources.get.return_value = [{'type': 'lxc', 'node': 'pve', 'vmid': 100}]
    with pytest.raises(ValueError):
        tools.create_container('pve', '100', 'local:vztmpl/a.tar')
    api.cluster.resources.get.return_value = []
    api.nodes.get.return_value = [{'node': 'other'}]
    with pytest.raises(ValueError):
        tools.create_container('pve', '100', 'local:vztmpl/a.tar')
    api.nodes.get.return_value = [{'node': 'pve'}]
    api.nodes.return_value.storage.get.return_value = [{'storage': 'local', 'content': 'rootdir'}]
    api.nodes.return_value.lxc.create.return_value = 'UPID:pve:create'
    tools.create_container('pve', '100', 'local:vztmpl/a.tar', ssh_public_keys='ssh-ed25519 AAAA', pool='pool')
    assert api.nodes.return_value.lxc.create.call_args.kwargs['pool'] == 'pool'
    api.nodes.return_value.lxc.return_value.config.get.side_effect = RuntimeError('offline')
    for method in [tools.get_container_config, tools.get_container_ip]:
        with pytest.raises(RuntimeError):
            method('pve', '100')
    for method, args in [(tools.execute_command, ('100', 'uname')), (tools.update_container_ssh_keys, ('pve', '100', 'ssh-ed25519 AAAA'))]:
        with pytest.raises(RuntimeError, match='SSH'):
            method(*args)
    tools.console_manager = Mock()
    api.cluster.resources.get.return_value = []
    with pytest.raises(ValueError):
        tools.execute_command('100', 'uname')
    api.cluster.resources.get.return_value = [{'type': 'lxc', 'node': 'pve', 'vmid': 100, 'name': 'web'}, {'type': 'lxc', 'node': 'pve', 'vmid': 101, 'name': 'web'}]
    with pytest.raises(ValueError):
        tools.execute_command('web', 'uname')
    for replies in [[{'success': False}], [{'success': True}, {'success': False}]]:
        tools.console_manager.execute_command.side_effect = replies
        with pytest.raises(RuntimeError):
            tools.update_container_ssh_keys('pve', '100', 'ssh-ed25519 AAAA')
    api.nodes.return_value.lxc.return_value.config.get.side_effect = None
    api.nodes.return_value.lxc.return_value.config.get.return_value = {}
    with pytest.raises(ValueError):
        tools.update_container_network('pve', '100', network_bridge='vmbr0')


@pytest.mark.asyncio
async def test_guest_agent_polling_reports_timeout_and_unknown_status():
    manager = VMConsoleManager(Mock())
    endpoint = Mock()
    endpoint.return_value.get.return_value = {'exited': 0}
    result = await manager._wait_for_exec_status(endpoint, 1, timeout_seconds=0)
    assert result['timed_out'] is True and result['exitcode'] == -1
    endpoint.return_value.get.side_effect = [{'exited': 0}, {'exited': 1, 'exitcode': 0}]
    assert (await manager._wait_for_exec_status(endpoint, 1, poll_interval_seconds=0))['exitcode'] == 0
    endpoint.return_value.get.side_effect = None
    endpoint.return_value.get.return_value = 'unexpected'
    assert (await manager._wait_for_exec_status(endpoint, 1))['exitcode'] != 0
    endpoint.return_value.get.return_value = None
    with pytest.raises(RuntimeError):
        await manager._wait_for_exec_status(endpoint, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize('response, expected', [({'exited': 0, 'timed_out': True}, False), ({'exited': 0}, False),
    ({'exited': 1, 'exitcode': 'bad'}, False), ({'exited': 1, 'exitcode': 0, 'out-truncated': True}, True), ('unexpected', False)])
async def test_guest_agent_exit_contract(response, expected):
    api = Mock()
    api.nodes.return_value.qemu.return_value.status.current.get.return_value = {'status': 'running'}
    api.nodes.return_value.qemu.return_value.agent.return_value.get.side_effect = OSError('old agent')
    api.nodes.return_value.qemu.return_value.agent.return_value.post.return_value = {'pid': 1}
    manager = VMConsoleManager(api)
    manager._wait_for_exec_status = AsyncMock(return_value=response)
    result = await manager.execute_command('pve', '100', 'echo hello', guest_os='windows')
    assert result['success'] is expected
    assert api.nodes.return_value.qemu.return_value.agent.return_value.post.call_args.kwargs['command'] == ['cmd.exe', '/d', '/s', '/c', 'echo hello']


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [None, {}, RuntimeError('596 TLS negotiation'), RuntimeError('not found')])
async def test_guest_agent_start_failures_are_safe_errors(response):
    api = Mock()
    agent = api.nodes.return_value.qemu.return_value.agent.return_value
    api.nodes.return_value.qemu.return_value.status.current.get.return_value = {'status': 'running'}
    agent.get.return_value = {}
    if isinstance(response, Exception):
        agent.post.side_effect = response
    else:
        agent.post.return_value = response
    with pytest.raises((ValueError, RuntimeError)):
        await VMConsoleManager(api).execute_command('pve', '100', 'uname')


@pytest.mark.asyncio
async def test_guest_agent_rejects_unsupported_guest_os():
    api = Mock()
    api.nodes.return_value.qemu.return_value.status.current.get.return_value = {'status': 'running'}
    api.nodes.return_value.qemu.return_value.agent.return_value.get.return_value = {}
    with pytest.raises((ValueError, RuntimeError), match='guest_os'):
        await VMConsoleManager(api).execute_command('pve', '100', 'uname', guest_os='unsupported')
