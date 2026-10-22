"""Optional ``purge`` on guest deletion (HA resources, backup/replication jobs, ACLs)."""

import json
from unittest.mock import Mock, patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from proxmox_mcp.server import ProxmoxMCPServer
from proxmox_mcp.services.jobs import JobStore
from proxmox_mcp.tools.containers import ContainerTools
from proxmox_mcp.tools.vm import VMTools


@pytest.fixture
def api():
    api = Mock()
    vm = api.nodes.return_value.qemu.return_value
    vm.status.current.get.return_value = {'status': 'stopped', 'name': 'ha-guest'}
    vm.delete.return_value = 'UPID:pve1:qmdestroy'
    ct = api.nodes.return_value.lxc.return_value
    ct.status.current.get.return_value = {'status': 'stopped'}
    ct.delete.return_value = 'UPID:pve1:vzdestroy'
    api.nodes.return_value.tasks.return_value.status.get.return_value = {'status': 'stopped', 'exitstatus': 'ERROR'}
    api.nodes.return_value.tasks.return_value.log.get.return_value = []
    return api


@pytest.mark.parametrize('purge,expected', [(False, {}), (True, {'purge': 1})])
def test_delete_vm_sends_purge_only_when_requested(api, purge, expected):
    VMTools(api).delete_vm('pve1', '100', purge=purge)
    api.nodes.return_value.qemu.return_value.delete.assert_called_once_with(**expected)


@pytest.mark.parametrize('purge,expected', [(False, {}), (True, {'purge': 1})])
def test_delete_container_sends_purge_only_when_requested(api, purge, expected):
    tools = ContainerTools(api)
    with patch.object(tools, '_resolve_targets', return_value=[('pve1', 101, 'ha-ct')]):
        result = json.loads(tools.delete_container('101', purge=purge, format_style='json')[0].text)
    assert result[0]['ok'] is True
    api.nodes.return_value.lxc.return_value.delete.assert_called_once_with(**expected)


def test_legacy_positional_vm_approval_does_not_enable_purge(api):
    VMTools(api).delete_vm('pve1', '100', False, 'approval-token')
    api.nodes.return_value.qemu.return_value.delete.assert_called_once_with()


def test_legacy_positional_container_approval_does_not_enable_purge(api):
    tools = ContainerTools(api)
    with patch.object(tools, '_resolve_targets', return_value=[('pve1', 101, 'ha-ct')]):
        tools.delete_container('101', False, 'json', 'approval-token')
    api.nodes.return_value.lxc.return_value.delete.assert_called_once_with()


def test_delete_vm_retry_keeps_purge(api, tmp_path):
    with JobStore(api, str(tmp_path / 'jobs.sqlite')) as store:
        result = VMTools(api, job_store=store).delete_vm('pve1', '100', purge=True)
        job_id = json.loads(result[-1].text)['job_id']
        assert store.get_job(job_id)['retry_spec']['params']['purge'] is True
        assert store.poll_job(job_id)['status'] == 'failed'
        store.retry_job(job_id)
    delete = api.nodes.return_value.qemu.return_value.delete
    assert delete.call_count == 2
    assert all(call.kwargs == {'purge': 1} for call in delete.call_args_list)


def test_delete_container_retry_keeps_purge(api, tmp_path):
    with JobStore(api, str(tmp_path / 'jobs.sqlite')) as store:
        tools = ContainerTools(api, job_store=store)
        with patch.object(tools, '_resolve_targets', return_value=[('pve1', 101, 'ha-ct')]):
            result = json.loads(tools.delete_container('101', purge=True, format_style='json')[0].text)
        job_id = result[0]['job_id']
        assert store.poll_job(job_id)['status'] == 'failed'
        store.retry_job(job_id)
    delete = api.nodes.return_value.lxc.return_value.delete
    assert delete.call_count == 2
    assert all(call.kwargs == {'purge': 1} for call in delete.call_args_list)


@pytest.mark.parametrize('kind,endpoint', [('vm.delete', 'qemu'), ('ct.delete', 'lxc')])
@pytest.mark.parametrize('params,expected', [
    ({'node': 'pve1', 'vmid': '100'}, {}),  # recipe persisted before purge existed
    ({'node': 'pve1', 'vmid': '100', 'purge': False}, {}),
    ({'node': 'pve1', 'vmid': '100', 'purge': True}, {'purge': 1}),
])
def test_persisted_delete_recipe_replays_purge(api, tmp_path, kind, endpoint, params, expected):
    db_path = str(tmp_path / 'jobs.sqlite')
    with JobStore(api, db_path) as store:
        job = store.register_task(tool_name='delete', summary='historical delete', node='pve1', upid='old',
                                  retry_spec={'kind': kind, 'params': params})
        assert store.poll_job(job['job_id'])['status'] == 'failed'
    # Reopen the store to exercise the persisted handler without an in-memory factory.
    with JobStore(api, db_path) as store:
        store.retry_job(job['job_id'])
    getattr(api.nodes.return_value, endpoint).return_value.delete.assert_called_once_with(**expected)


def _ha_stop(api, guest, polls_running):
    """HA guest: the stop task is OK at once, the guest stays running for a few polls."""
    guest.status.stop.post.return_value = 'UPID:pve1:hastop'
    api.nodes.return_value.tasks.return_value.status.get.return_value = {'status': 'stopped', 'exitstatus': 'OK'}
    guest.status.current.get.side_effect = (
        [{'status': 'running', 'name': 'ha-guest'}] * (1 + polls_running) + [{'status': 'stopped'}]
    )


def test_force_delete_vm_waits_for_ha_guest_to_stop(api):
    vm = api.nodes.return_value.qemu.return_value
    _ha_stop(api, vm, polls_running=3)
    with patch('proxmox_mcp.tools.base.time.sleep'):
        VMTools(api).delete_vm('pve1', '100', force=True, purge=True)
    assert vm.status.current.get.call_count == 5
    vm.delete.assert_called_once_with(purge=1)


def test_force_delete_container_waits_for_ha_guest_to_stop(api):
    ct = api.nodes.return_value.lxc.return_value
    _ha_stop(api, ct, polls_running=3)
    tools = ContainerTools(api)
    with patch.object(tools, '_resolve_targets', return_value=[('pve1', 101, 'ha-ct')]), \
         patch('proxmox_mcp.tools.base.time.sleep'):
        result = json.loads(tools.delete_container('101', force=True, purge=True, format_style='json')[0].text)
    assert result[0]['ok'] is True
    assert ct.status.current.get.call_count == 5
    ct.delete.assert_called_once_with(purge=1)


def test_force_delete_vm_not_submitted_if_guest_never_stops(api):
    vm = api.nodes.return_value.qemu.return_value
    _ha_stop(api, vm, polls_running=10_000)
    clock = iter(range(0, 10_000, 10))
    with patch('proxmox_mcp.tools.base.time.sleep'), \
         patch('proxmox_mcp.tools.base.time.monotonic', side_effect=lambda: next(clock)):
        with pytest.raises(Exception, match='still running after stop'):
            VMTools(api).delete_vm('pve1', '100', force=True, purge=True)
    vm.delete.assert_not_called()


def test_force_delete_container_not_submitted_if_guest_never_stops(api):
    ct = api.nodes.return_value.lxc.return_value
    _ha_stop(api, ct, polls_running=10_000)
    clock = iter(range(0, 10_000, 10))
    tools = ContainerTools(api)
    with patch.object(tools, '_resolve_targets', return_value=[('pve1', 101, 'ha-ct')]), \
         patch('proxmox_mcp.tools.base.time.sleep'), \
         patch('proxmox_mcp.tools.base.time.monotonic', side_effect=lambda: next(clock)):
        result = json.loads(tools.delete_container('101', force=True, purge=True, format_style='json')[0].text)
    assert result[0]['ok'] is False
    assert 'still running after stop' in result[0]['error']
    ct.delete.assert_not_called()


@pytest.mark.parametrize('purge', [False, True])
def test_bulk_container_delete_retry_keeps_each_guest(api, tmp_path, purge):
    guests = {vmid: Mock() for vmid in (101, 102)}
    for vmid, guest in guests.items():
        guest.status.current.get.return_value = {'status': 'stopped'}
        guest.delete.return_value = f'UPID:pve1:delete-{vmid}'
    api.nodes.return_value.lxc.side_effect = guests.__getitem__
    with JobStore(api, str(tmp_path / 'bulk.sqlite')) as store:
        tools = ContainerTools(api, job_store=store)
        with patch.object(tools, '_resolve_targets', return_value=[('pve1', i, str(i)) for i in guests]):
            rows = json.loads(tools.delete_container('101,102', purge=purge, format_style='json')[0].text)
        for row in rows:
            assert row['ok'] is True
            assert store.poll_job(row['job_id'])['status'] == 'failed'
            store.retry_job(row['job_id'])
    expected = {'purge': 1} if purge else {}
    for guest in guests.values():
        assert guest.delete.call_count == 2
        assert all(call.kwargs == expected for call in guest.delete.call_args_list)


@pytest.mark.parametrize('kind', ['vm', 'ct'])
@pytest.mark.parametrize('failure', ['failed_stop', 'status_unavailable'])
def test_force_delete_does_not_destroy_after_prerequisite_error(api, kind, failure):
    guest = getattr(api.nodes.return_value, 'qemu' if kind == 'vm' else 'lxc').return_value
    _ha_stop(api, guest, polls_running=0)
    if failure == 'failed_stop':
        api.nodes.return_value.tasks.return_value.status.get.return_value['exitstatus'] = 'ERROR'
        expected = 'Prerequisite task failed'
    else:
        guest.status.current.get.side_effect = [{'status': 'running'}, RuntimeError('status unavailable')]
        expected = 'status unavailable'
    if kind == 'vm':
        with pytest.raises(RuntimeError, match=expected):
            VMTools(api).delete_vm('pve1', '100', force=True, purge=True)
    else:
        tools = ContainerTools(api)
        with patch.object(tools, '_resolve_targets', return_value=[('pve1', 101, 'ha-ct')]):
            rows = json.loads(tools.delete_container('101', force=True, purge=True, format_style='json')[0].text)
        assert rows[0]['ok'] is False
        assert expected in rows[0]['error']
    guest.delete.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['vm', 'ct'])
@pytest.mark.parametrize('policy', ['readonly', 'missing_approval', 'approved'])
async def test_mcp_purge_schema_and_target_policy(api, tmp_path, kind, policy):
    config = {
        'targets': {
            'lab': {
                'host': 'lab.example',
                'readonly': policy == 'readonly',
                'auth': {'user': 'u', 'token_name': 't', 'token_value': 'v'},
                'command_policy': {
                    'high_risk_mode': 'enforce',
                    'high_risk_require_approval_token': True,
                    'high_risk_approval_token': 'delete-approval',
                },
            },
        },
        'jobs': {'sqlite_path': str(tmp_path / 'mcp.sqlite')},
    }
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config), encoding='utf-8')
    with patch('proxmox_mcp.core.proxmox.ProxmoxAPI', return_value=api):
        server = ProxmoxMCPServer(str(path))
    name = 'delete_vm' if kind == 'vm' else 'delete_container'
    args = {'node': 'pve1', 'vmid': '100'} if kind == 'vm' else {'selector': 'pve1:101'}
    args.update({'purge': True, 'target': 'lab'})
    if policy != 'missing_approval':
        args['approval_token'] = 'delete-approval'
    try:
        schema = next(tool.inputSchema for tool in await server.mcp.list_tools() if tool.name == name)
        assert schema['properties']['purge']['type'] == 'boolean'
        assert schema['properties']['purge']['default'] is False
        assert 'purge' not in schema.get('required', [])
        toolset = server.target_toolsets['lab']
        with patch.object(toolset.container_tools, '_resolve_targets', return_value=[('pve1', 101, 'ha-ct')]):
            if policy == 'approved':
                await server.mcp.call_tool(name, args)
                guest = getattr(api.nodes.return_value, 'qemu' if kind == 'vm' else 'lxc').return_value
                guest.delete.assert_called_once_with(purge=1)
            else:
                with pytest.raises(ToolError, match='read-only' if policy == 'readonly' else 'approval'):
                    await server.mcp.call_tool(name, args)
                api.nodes.assert_not_called()
    finally:
        server.close()
