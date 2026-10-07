"""Storage inventory and snapshot tasks under failures and recovery."""

import json
from unittest.mock import Mock

import pytest

from proxmox_mcp.services.jobs import JobStore
from proxmox_mcp.tools import iso, snapshots, backup, storage
from proxmox_mcp.tools.iso import ISOTools
from proxmox_mcp.tools.snapshots import SnapshotTools
from proxmox_mcp.tools.backup import BackupTools
from proxmox_mcp.tools.storage import StorageTools


@pytest.fixture
def backend(tmp_path):
    api = Mock()
    api.nodes.get.return_value = [{'node': 'pve', 'status': 'online'}]
    api.nodes.return_value.storage.get.return_value = [{'storage': 'local', 'content': 'iso,vztmpl,backup'}]
    api.nodes.return_value.tasks.return_value.status.get.return_value = {'status': 'stopped', 'exitstatus': 'ERROR'}
    api.nodes.return_value.tasks.return_value.log.get.return_value = []
    with JobStore(api, str(tmp_path / 'jobs.sqlite')) as store:
        yield api, store


def assert_recoverable(store, api, tool):
    job = store.list_jobs(tool_name=tool)[0]
    assert store.poll_job(job['job_id'])['status'] == 'failed'
    assert store.retry_job(job['job_id'])['retry_count'] == 1
    assert store.cancel_job(job['job_id'])['status'] == 'cancel_requested'
    assert api.nodes.return_value.tasks.return_value.delete.called


@pytest.mark.parametrize('kind', ['qemu', 'lxc'])
@pytest.mark.parametrize('operation', ['create_snapshot', 'delete_snapshot', 'rollback_snapshot'])
def test_snapshot_jobs_survive_failure_and_reuse_correct_guest_endpoint(backend, kind, operation):
    api, store = backend
    guest = getattr(api.nodes.return_value, kind).return_value
    guest.snapshot.get.return_value = [{'name': 'base'}]
    guest.snapshot.post.return_value = 'UPID:pve:snapshot'
    guest.snapshot.return_value.delete.return_value = 'UPID:pve:delete'
    guest.snapshot.return_value.rollback.post.return_value = 'UPID:pve:rollback'
    kwargs = {'description': 'Before update', 'vmstate': True} if operation == 'create_snapshot' else {}
    result = getattr(SnapshotTools(api, job_store=store), operation)('pve', '100', 'base', vm_type=kind, **kwargs)
    assert 'Task ID: UPID:pve:' in result[0].text
    assert_recoverable(store, api, operation)
    if operation == 'create_snapshot':
        assert guest.snapshot.post.call_count == 2
        assert guest.snapshot.post.call_args.kwargs == {'snapname': 'base', 'description': 'Before update', **({'vmstate': 1} if kind == 'qemu' else {})}


def test_snapshot_listing_handles_optional_fields_and_bad_dates(backend):
    api, _ = backend
    tools = SnapshotTools(api)
    guest = api.nodes.return_value.lxc.return_value
    guest.snapshot.get.return_value = []
    assert 'No snapshots' in tools.list_snapshots('pve', '100', vm_type='lxc')[0].text
    guest.snapshot.get.return_value = {'data': [{'name': 'base', 'snaptime': 'bad', 'description': 'Before update', 'parent': 'older', 'vmstate': 1}]}
    result = tools.list_snapshots('pve', '100', vm_type='lxc')[0].text
    assert 'Created: bad' in result
    assert 'Parent: older' in result
    assert 'RAM State: Included' in result
    guest.snapshot.get.side_effect = RuntimeError('offline')
    with pytest.raises(RuntimeError):
        tools.list_snapshots('pve', '100', vm_type='lxc')
    guest.snapshot.post.side_effect = RuntimeError('offline')
    with pytest.raises(RuntimeError):
        tools.create_snapshot('pve', '100', 'base', vm_type='lxc')


def test_iso_download_and_delete_retry_revalidate_inventory(backend):
    api, store = backend
    endpoint = api.nodes.return_value.storage.return_value
    endpoint.return_value.post.return_value = 'UPID:pve:download'
    tools = ISOTools(api, job_store=store)
    assert 'Download Started' in tools.download_iso('pve', 'local', 'https://example.invalid/a.iso', 'a.iso')[0].text
    assert_recoverable(store, api, 'download_iso')
    endpoint.content.get.return_value = [{'volid': 'local:iso/a.iso', 'content': 'iso'}]
    endpoint.content.return_value.delete.return_value = 'UPID:pve:delete'
    assert 'a.iso' in tools.delete_iso('pve', 'local', 'a.iso')[0].text
    assert_recoverable(store, api, 'delete_iso')
    assert endpoint.content.get.call_count >= 2
    endpoint.return_value.post.side_effect = RuntimeError('offline')
    with pytest.raises(RuntimeError):
        tools.download_iso('pve', 'local', 'https://example.invalid/a.iso', 'a.iso')


def test_iso_and_template_inventory_preserves_completeness(backend):
    api, _ = backend
    tools = ISOTools(api)
    endpoint = api.nodes.return_value.storage.return_value
    endpoint.content.get.return_value = [{'volid': 'local:vztmpl/alpine.tar.zst', 'size': 1024}]
    assert 'alpine.tar.zst' in tools.list_templates('pve', 'local')[0].text
    endpoint.content.get.return_value = []
    for method in [tools.list_templates, tools.list_isos]:
        text = method('pve', 'local')[0].text
        assert 'No ' in text and 'pve' in text and 'local' in text
    api.nodes.get.return_value = [{}, {'node': 'pve'}]
    api.nodes.return_value.storage.get.return_value = [{}, {'storage': 'other', 'content': 'iso'}, {'storage': 'local', 'content': 'backup'}]
    assert tools._get_storage_content('iso', storage='local') == []
    api.nodes.return_value.storage.get.side_effect = RuntimeError('offline')
    with pytest.raises(RuntimeError):
        tools.list_templates()
    api.nodes.get.side_effect = RuntimeError('offline')
    with pytest.raises(RuntimeError):
        tools.list_isos()


@pytest.mark.parametrize('module', [iso, snapshots, backup, storage])
def test_storage_payload_helpers_unwrap_expected_shapes(module):
    assert module._as_list({'data': [1]}) == [1]
    assert module._as_list({'data': None}) == []
    if hasattr(module, '_get'):
        assert module._get(None, 'x', 1) == 1
    if hasattr(module, '_b2h'):
        assert module._b2h('bad') in {'0 B', '0.00 B'}
        assert 'KiB' in module._b2h(1024)


def test_storage_status_selection_and_failure_contract(backend):
    api, _ = backend
    tools = StorageTools(api)
    api.nodes.get.return_value = [{'node': 'pve', 'status': 'offline'}]
    assert tools._node_names() == ['pve']
    assert tools._candidate_nodes_for_storage({'nodes': ['missing']}, ['pve']) == ['missing']
    assert tools._candidate_nodes_for_storage({'nodes': ' pve , other '}, ['pve']) == ['pve']
    assert tools._storage_status({}, ['pve']) is None
    api.storage.get.side_effect = RuntimeError('offline')
    tools._call_with_retry = lambda operation, call: call()
    with pytest.raises(RuntimeError):
        tools.get_storage()


def test_backup_inventory_and_action_errors(backend):
    api, _ = backend
    tools = BackupTools(api)
    api.nodes.get.return_value = [{'node': 'pve'}, {}]
    api.nodes.return_value.storage.get.return_value = [{}]
    assert 'No backups' in tools.list_backups()[0].text
    api.nodes.get.side_effect = RuntimeError('offline')
    with pytest.raises(RuntimeError):
        tools.list_backups()
    api.nodes.return_value.vzdump.post.side_effect = RuntimeError('offline')
    with pytest.raises(RuntimeError):
        tools.create_backup('pve', '100', 'local')
    api.nodes.return_value.qemu.post.side_effect = RuntimeError('offline')
    with pytest.raises(RuntimeError):
        tools.restore_backup('pve', 'local:backup/vzdump-qemu-100.tar.zst', '100', 'local')
    assert json.loads(SnapshotTools(api)._json_fmt({'success': True})[0].text)['success'] is True
