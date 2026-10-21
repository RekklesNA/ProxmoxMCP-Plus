"""Optional ``purge`` on guest deletion (HA resources, backup/replication jobs, ACLs)."""

import json
from unittest.mock import Mock, patch

import pytest

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
    with JobStore(api, str(tmp_path / 'jobs.sqlite')) as store:
        job = store.register_task(tool_name='delete', summary='historical delete', node='pve1', upid='old',
                                  retry_spec={'kind': kind, 'params': params})
        assert store.poll_job(job['job_id'])['status'] == 'failed'
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
