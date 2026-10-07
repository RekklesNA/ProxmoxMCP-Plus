"""Guest lifecycle, inventory fallback and durable retry contracts."""

import json
from unittest.mock import Mock

import pytest

from proxmox_mcp.services.jobs import JobStore
from proxmox_mcp.tools.base import InventoryList
from proxmox_mcp.tools.containers import ContainerTools, _b2h, _get, _as_dict, _as_list
from proxmox_mcp.tools.vm import VMTools
from proxmox_mcp.tools.storage_selection import select_storage


@pytest.fixture
def lifecycle(tmp_path):
    api = Mock()
    api.cluster.resources.get.return_value = [{'type': 'lxc', 'vmid': 101, 'node': 'pve', 'name': 'web', 'status': 'stopped'}]
    api.nodes.get.return_value = [{'node': 'pve'}]
    ct = api.nodes.return_value.lxc.return_value
    ct.status.current.get.return_value = {'status': 'stopped'}
    ct.status.start.post.return_value = 'UPID:pve:start'
    ct.status.stop.post.return_value = 'UPID:pve:stop'
    ct.status.shutdown.post.return_value = 'UPID:pve:shutdown'
    ct.status.reboot.post.return_value = 'UPID:pve:reboot'
    ct.delete.return_value = 'UPID:pve:delete'
    api.nodes.return_value.tasks.return_value.status.get.return_value = {'status': 'stopped', 'exitstatus': 'ERROR'}
    api.nodes.return_value.tasks.return_value.log.get.return_value = []
    with JobStore(api, str(tmp_path / 'jobs.sqlite')) as store:
        yield api, store


def test_container_create_secret_retry_and_cancel_remain_in_process(lifecycle):
    api, store = lifecycle
    api.cluster.resources.get.return_value = []
    api.nodes.return_value.storage.get.return_value = [{'storage': 'local', 'content': 'rootdir', 'active': 1}]
    api.nodes.return_value.lxc.create.return_value = 'UPID:pve:create'
    result = ContainerTools(api, job_store=store).create_container('pve', '102', 'local:vztmpl/a.tar', password='fake-secret')
    metadata = json.loads(result[-1].text)
    assert metadata['status'] == 'submitted'
    job_id = metadata['job_id']
    assert store.poll_job(job_id)['status'] == 'failed'
    assert store.retry_job(job_id)['status'] == 'running'
    assert store.cancel_job(job_id)['status'] == 'cancel_requested'
    assert api.nodes.return_value.lxc.create.call_count == 2
    assert 'fake-secret' not in json.dumps(store.get_job(job_id))


def test_pretty_container_resource_update_reports_result(lifecycle):
    api, store = lifecycle
    result = ContainerTools(api, job_store=store).update_container_resources('pve:101', cores=2)
    assert 'Update Container Resources' in result[0].text


@pytest.mark.parametrize('operation,options,endpoint', [
    ('start_container', {}, 'start'), ('stop_container', {'graceful': True}, 'shutdown'),
    ('stop_container', {'graceful': False}, 'stop'), ('restart_container', {}, 'reboot'),
    ('delete_container', {}, None),
])
@pytest.mark.parametrize('style', ['pretty', 'json'])
def test_container_tasks_are_tracked_retried_and_cancelled(lifecycle, operation, options, endpoint, style):
    api, store = lifecycle
    tools = ContainerTools(api, job_store=store)
    result = getattr(tools, operation)('pve:101', format_style=style, **options)
    payload = json.loads(result[-1].text)
    assert payload[0]['ok'] is True
    job_id = payload[0]['job_id']
    assert store.get_job(job_id)['tool_name'] == operation
    assert store.poll_job(job_id)['status'] == 'failed'
    assert store.retry_job(job_id)['retry_count'] == 1
    assert store.cancel_job(job_id)['status'] == 'cancel_requested'
    api.nodes.return_value.tasks.return_value.delete.assert_called_once()
    action = api.nodes.return_value.lxc.return_value.delete if endpoint is None else getattr(api.nodes.return_value.lxc.return_value.status, endpoint).post
    assert action.call_count == 2


@pytest.mark.parametrize('operation, options', [('start_container', {}), ('stop_container', {}), ('restart_container', {}),
                                               ('delete_container', {}), ('update_container_resources', {'cores': 2})])
def test_empty_bulk_selection_is_an_error_and_backend_errors_are_sanitized(lifecycle, operation, options):
    api, store = lifecycle
    tools = ContainerTools(api, job_store=store)
    with pytest.raises(ValueError):
        getattr(tools, operation)('missing', **options)
    api.nodes.return_value.lxc.return_value.status.start.post.side_effect = RuntimeError('password=private')
    api.nodes.return_value.lxc.return_value.status.shutdown.post.side_effect = RuntimeError('password=private')
    api.nodes.return_value.lxc.return_value.status.reboot.post.side_effect = RuntimeError('password=private')
    api.nodes.return_value.lxc.return_value.delete.side_effect = RuntimeError('password=private')
    api.nodes.return_value.lxc.return_value.config.put.side_effect = RuntimeError('password=private')
    result = getattr(tools, operation)('web', format_style='json', **options)
    payload = json.loads(result[0].text)
    assert payload[0]['ok'] is False
    assert 'private' not in payload[0]['error']


def test_container_selector_grammar_deduplicates_and_rejects_partial_inventory(lifecycle):
    api, _ = lifecycle
    tools = ContainerTools(api)
    assert tools._resolve_targets('') == []
    assert tools._resolve_targets('pve:101,pve/web,101,web,pve:bad') == [('pve', 101, 'web')]
    partial = InventoryList()
    partial.warnings = ['pve: unavailable']
    tools._list_ct_pairs = Mock(return_value=partial)
    with pytest.raises(RuntimeError, match='incomplete'):
        tools._resolve_targets('101')


def test_container_shapes_and_inventory_fallback(lifecycle):
    api, _ = lifecycle
    assert _b2h('bad') == '0.00 B'
    assert _b2h(1024**5) == '1.00 PiB'
    assert _get(None, 'missing', 7) == 7
    assert _as_dict({'data': {'a': 1}}) == {'a': 1}
    assert _as_dict(None) == {}
    assert _as_list({'data': [1]}) == [1]
    assert _as_list({'data': None}) == []
    tools = ContainerTools(api)
    api.cluster.resources.get.return_value = [{'type': 'lxc'}, {'type': 'lxc', 'node': 'other', 'vmid': 2},
        {'type': 'lxc', 'node': 'pve', 'id': 'lxc/101'}, {'type': 'lxc', 'node': 'pve'}]
    assert tools._cluster_ct_pairs('pve') == [('pve', {'type': 'lxc', 'node': 'pve', 'id': 'lxc/101', 'vmid': '101'})]
    api.cluster.resources.get.return_value = None
    api.nodes.return_value.lxc.get.return_value = {'data': [{'vmid': 101}, 102, 'invalid']}
    assert len(tools._list_ct_pairs('pve')) == 2
    api.nodes.get.return_value = [{}, {'node': 'pve'}]
    assert len(tools._list_ct_pairs(None)) == 2
    api.nodes.return_value.lxc.get.side_effect = RuntimeError('offline')
    with pytest.raises(RuntimeError):
        tools._list_ct_pairs('pve')
    api.nodes.get.side_effect = RuntimeError('offline')
    with pytest.raises(RuntimeError):
        tools._list_ct_pairs(None)


@pytest.mark.parametrize('config', [{'ram': 256, 'cpulimit': 1.5}, {'memoryMiB': 'bad', 'cores': 'bad'}, {}, {'memory': 0}])
def test_container_stats_fallback_and_pretty_unknowns(lifecycle, config):
    api, _ = lifecycle
    guest = api.nodes.return_value.lxc.return_value
    guest.status.current.get.return_value = {'status': 'stopped'}
    guest.config.get.return_value = config
    guest.rrddata.get.return_value = [{'cpu': .5, 'mem': 0, 'maxmem': 1024**3}]
    tools = ContainerTools(api)
    result = tools.get_containers(include_stats=True, include_raw=True, format_style='json')
    payload = json.loads(result[0].text)[0]
    assert payload['cpu_pct'] == 50
    assert payload['maxmem_bytes'] > 0
    pretty = tools._render_pretty([payload, dict(payload, unlimited_memory=True)])
    assert 'Memory:' in pretty[0].text
    assert 'unlimited' in pretty[0].text


def test_container_invalid_stats_do_not_make_inventory_disappear(lifecycle):
    api, _ = lifecycle
    api.cluster.resources.get.return_value = [{'type': 'lxc', 'node': 'pve', 'vmid': 'bad', 'cpu': 'bad', 'mem': 'bad', 'maxmem': 'bad'}]
    tools = ContainerTools(api)
    assert json.loads(tools.get_containers(format_style='json')[0].text)[0]['vmid'] == 'bad'
    guest = api.nodes.return_value.lxc.return_value
    guest.status.current.get.side_effect = RuntimeError('offline')
    guest.config.get.side_effect = RuntimeError('offline')
    assert tools._status_and_config('pve', 101) == ({}, {})
    guest.rrddata.get.return_value = []
    assert tools._rrd_last('pve', 101) == (None, None, None)
    guest.rrddata.get.side_effect = RuntimeError('offline')
    assert tools._rrd_last('pve', 101) == (None, None, None)


@pytest.mark.parametrize('operation, state, endpoint', [('start_vm', 'stopped', 'start'), ('stop_vm', 'running', 'stop'),
    ('shutdown_vm', 'running', 'shutdown'), ('reset_vm', 'running', 'reset')])
def test_vm_power_task_contract(lifecycle, operation, state, endpoint):
    api, store = lifecycle
    guest = api.nodes.return_value.qemu.return_value
    guest.status.current.get.return_value = {'status': state}
    action = getattr(guest.status, endpoint).post
    action.return_value = 'UPID:pve:power'
    tools = VMTools(api, job_store=store)
    assert 'Task ID: UPID:pve:power' in getattr(tools, operation)('pve', '100')[0].text
    job_id = store.list_jobs()[0]['job_id']
    store.poll_job(job_id)
    assert store.retry_job(job_id)['retry_count'] == 1
    store.cancel_job(job_id)
    assert action.call_count == 2
    guest.status.current.get.return_value = {'status': 'running' if endpoint == 'start' else 'stopped'}
    assert 'Task ID:' not in getattr(tools, operation)('pve', '100')[0].text
    for message, expected in [('not found', ValueError), ('offline', RuntimeError)]:
        guest.status.current.get.side_effect = RuntimeError(message)
        with pytest.raises(expected):
            getattr(tools, operation)('pve', '100')


@pytest.mark.parametrize('inventory', [None, [], [{'storage': 'local', 'content': 'iso'}],
    [{'storage': 'local', 'content': 'images', 'active': False}],
    [{'storage': 'local', 'content': 'images', 'enabled': False}],
    [{'storage': 'local', 'content': 'images', 'avail': 1}], [{}]])
def test_storage_selection_refuses_unavailable_or_incompatible_capacity(inventory):
    api = Mock()
    api.nodes.return_value.storage.get.return_value = inventory
    with pytest.raises((ValueError, RuntimeError)):
        select_storage(api, 'pve', 'images', None, 10)


def test_storage_selection_prefers_eligible_local_storage():
    api = Mock()
    api.nodes.return_value.storage.get.return_value = [
        {'storage': 'local-lvm', 'content': 'images', 'active': False},
        {'storage': 'vm-storage', 'content': ['images', 'rootdir'], 'avail': 100 * 1024**3},
        {'storage': 'other', 'content': 'images,rootdir'},
    ]
    assert select_storage(api, 'pve', 'images', None, 10)['storage'] == 'vm-storage'
    assert select_storage(api, 'pve', 'rootdir', 'other', 10)['storage'] == 'other'
    with pytest.raises(ValueError):
        select_storage(api, 'pve', 'images', None, 0)
