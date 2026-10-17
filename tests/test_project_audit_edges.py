"""Contract, failure and lifecycle tests for the audit repair."""

import sys
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from proxmox_mcp.core.process import run_bounded
from proxmox_mcp.models.tooling import ToolResult, result_succeeded
from proxmox_mcp.openapi_proxy import create_app
from proxmox_mcp.security.resources import resolve_volume, validate_volume, validate_segment
from proxmox_mcp.services.jobs import JobStore, JobConflictError, JobNotFoundError
from proxmox_mcp.services.tool_registry import ToolExposurePolicy
from proxmox_mcp.tools.base import ProxmoxTool
from proxmox_mcp.tools.console.container_manager import ContainerConsoleManager
from proxmox_mcp.config.models import SSHConfig


@pytest.mark.parametrize('value', ['../pve', '..', '?query', '#fragment', '', 'pve\n'])
def test_resource_segments_reject_url_controls(value):
    with pytest.raises(ValueError):
        validate_segment(value)


@pytest.mark.parametrize('value', ['local:iso/../disk', 'local:iso//file', 'local:iso/a%2fb', 'local:iso/a?x', 'local:iso/a#x', 'local:iso/a\\b'])
def test_volume_validation_rejects_path_ambiguity(value):
    with pytest.raises(ValueError):
        validate_volume('local', value)


def test_pbs_nested_volume_remains_supported():
    volume = 'pbs:backup/vm/100/2026-10-07T01:02:03Z'
    assert validate_volume('pbs', volume) == volume


def test_volume_resolution_rejects_failed_inventory_and_ambiguous_names():
    api = Mock()
    inventory = api.nodes.return_value.storage.return_value.content
    inventory.get.return_value = None
    with pytest.raises(RuntimeError, match='inventory'):
        resolve_volume(api, 'pve', 'local', 'disk.iso', {'iso'}, filename=True)
    inventory.get.return_value = [{'volid': 'local:iso/disk.iso', 'content': 'iso'}] * 2
    with pytest.raises(ValueError, match='ambiguous'):
        resolve_volume(api, 'pve', 'local', 'disk.iso', {'iso'}, filename=True)
    with pytest.raises(ValueError, match='volume ID'):
        resolve_volume(api, 'pve', 'local', '../disk.iso', {'iso'}, filename=True)


def test_subprocess_output_is_bounded_on_both_streams():
    result = run_bounded([sys.executable, '-c', 'import sys; sys.stdout.write("a"*200000); sys.stderr.write("b"*200000)'], timeout=5, max_output_bytes=4096)
    assert result.returncode == 0
    assert result.stdout == 'a' * 4096
    assert result.stderr == 'b' * 4096
    assert result.output_truncated


def test_subprocess_timeout_reaps_child_and_preserves_partial_output():
    result = run_bounded([sys.executable, '-c', 'import time; print("started",flush=True); time.sleep(10)'], timeout=2.0)
    assert result.returncode == 124
    assert result.stdout == 'started\n' or result.stdout == 'started\r\n'
    assert not result.output_truncated


@pytest.mark.parametrize('kwargs', [{'timeout': 0}, {'timeout': 1, 'max_output_bytes': 0}])
def test_subprocess_rejects_invalid_limits(kwargs):
    with pytest.raises(ValueError):
        run_bounded(['unused'], **kwargs)


def test_channel_drain_caps_output_and_keeps_draining():
    manager = ContainerConsoleManager(Mock(), SSHConfig())
    manager.OUTPUT_LIMIT_BYTES = 4
    channel = Mock()
    out = [b'abcdefgh']
    err = [b'ijklmnop']
    channel.recv_ready.side_effect = lambda: bool(out)
    channel.recv_stderr_ready.side_effect = lambda: bool(err)
    channel.recv.side_effect = lambda size: out.pop(0)
    channel.recv_stderr.side_effect = lambda size: err.pop(0)
    channel.exit_status_ready.return_value = True
    channel.recv_exit_status.return_value = 0
    result = manager._read_channel(channel)
    assert result['output'] == 'abcd'
    assert result['error'] == 'ijkl'
    assert result['output_truncated']
    channel.close.assert_called_once()


@pytest.fixture
def job_store(tmp_path):
    api = Mock()
    api.nodes.return_value.tasks.return_value.status.get.return_value = {'status': 'stopped', 'exitstatus': 'error'}
    api.nodes.return_value.tasks.return_value.log.get.return_value = []
    store = JobStore(api, str(tmp_path / 'jobs.sqlite3'), target_name='target')
    yield store
    store.close()


def uncertain_job(store):
    def interrupted():
        raise KeyboardInterrupt()
    job = store.register_task(tool_name='start_vm', summary='start', node='pve', upid='UPID:pve:old', retry_factory=interrupted)
    store.poll_job(job['job_id'])
    with pytest.raises(KeyboardInterrupt):
        store.retry_job(job['job_id'])
    return job['job_id']


def test_reconciliation_attaches_verified_task_without_resubmission(job_store):
    identifier = uncertain_job(job_store)
    result = job_store.reconcile_job(identifier, upid='UPID:pve:new')
    assert result['status'] == 'running'
    assert result['upid'] == 'UPID:pve:new'
    assert result['previous_upids'] == ['UPID:pve:old']
    assert result['audit_log'][-1]['event'] == 'retry_reconciled'


def test_reconciliation_can_confirm_no_submission(job_store):
    identifier = uncertain_job(job_store)
    assert job_store.reconcile_job(identifier, confirmed_not_submitted=True)['status'] == 'failed'
    with pytest.raises(JobConflictError):
        job_store.reconcile_job(identifier, confirmed_not_submitted=True)


@pytest.mark.parametrize('kwargs', [{}, {'upid': 'UPID:pve:new', 'confirmed_not_submitted': True}, {'upid': 'UPID:other:new'}])
def test_reconciliation_rejects_missing_ambiguous_or_wrong_node_evidence(job_store, kwargs):
    identifier = uncertain_job(job_store)
    with pytest.raises(ValueError):
        job_store.reconcile_job(identifier, **kwargs)
    assert job_store.get_job(identifier)['status'] == 'needs_reconciliation'


def test_expired_retry_claim_requires_reconciliation(job_store):
    job = job_store.register_task(tool_name='start_vm', summary='start', node='pve', upid='old')
    with job_store._write_transaction():
        record = job_store._load_record_from_db(job['job_id'])
        record.status = 'retrying'
        record.metadata['retry_lease_expires'] = '2000-01-01T00:00:00+00:00'
        job_store._save_record(record)
    result = job_store.get_job(job['job_id'])
    assert result['status'] == 'needs_reconciliation'
    assert result['audit_log'][-1]['event'] == 'retry_lease_expired'


def test_job_lists_do_not_query_audit_for_each_row(job_store):
    for number in range(20):
        job_store.register_task(tool_name='start_vm', summary='start', node='pve', upid=str(number))
    queries = []
    job_store._conn.set_trace_callback(queries.append)
    result = job_store.list_jobs()
    assert len(result) == 20
    assert all(not item['audit_log'] for item in result)
    assert sum(statement.startswith('SELECT') for statement in queries) == 1
    queries.clear()
    result = job_store.list_jobs(include_audit=True)
    assert all(item['audit_log'][0]['event'] == 'created' for item in result)
    assert sum(statement.startswith('SELECT') for statement in queries) == 2


def test_audit_pages_have_stable_cursors_and_target_isolation(job_store):
    job = job_store.register_task(tool_name='start_vm', summary='start', node='pve', upid='old')
    job_store.poll_job(job['job_id'])
    page = job_store.get_audit(job['job_id'], limit=1)
    assert len(page) == 1 and page[0]['event'] == 'created'
    next_page = job_store.get_audit(job['job_id'], after_id=page[0]['id'])
    assert next_page[0]['event'] == 'polled'
    with pytest.raises(JobNotFoundError):
        job_store.get_audit('missing')
    with JobStore(job_store.proxmox, job_store.sqlite_path, target_name='other') as other:
        with pytest.raises(JobNotFoundError):
            other.get_audit(job['job_id'])


def test_job_cache_has_a_fixed_upper_bound(job_store):
    for number in range(510):
        job_store.register_task(tool_name='start_vm', summary='start', node='pve', upid=str(number))
    assert len(job_store._jobs) <= 500
    assert len(job_store.list_jobs(limit=500)) == 500


def test_proxy_retry_respects_tool_filter_without_a_command_policy(job_store):
    job = job_store.register_task(tool_name='delete_vm', summary='delete', node='pve', upid='old', retry_factory=Mock())
    job_store.poll_job(job['job_id'])
    app = create_app(['unused'], api_key='fake', strict_auth=True, cors_allow_origins=[], job_store=job_store,
                     tool_exposure_policy=ToolExposurePolicy(known_tools={'delete_vm'}, denylist=['delete_vm']))
    client = TestClient(app)
    try:
        response = client.post(f"/jobs/{job['job_id']}/retry", headers={'Authorization': 'Bearer fake'})
    finally:
        client.close()
    assert response.status_code == 403


def test_proxy_exposes_audit_and_reconciliation_routes(job_store):
    identifier = uncertain_job(job_store)
    app = create_app(['unused'], api_key='fake', strict_auth=True, cors_allow_origins=[], job_store=job_store)
    client = TestClient(app)
    try:
        headers = {'Authorization': 'Bearer fake'}
        assert client.get(f'/jobs/{identifier}/audit', headers=headers).status_code == 200
        assert client.get('/jobs/missing/audit', headers=headers).status_code == 404
        assert client.post(f'/jobs/{identifier}/reconcile', headers=headers, json={'confirmed_not_submitted': True}).json()['status'] == 'failed'
        assert client.post(f'/jobs/{identifier}/reconcile', headers=headers, json={'confirmed_not_submitted': True}).status_code == 409
    finally:
        client.close()


@pytest.mark.parametrize('result, expected', [(ToolResult(success=False, code='DENIED', message='blocked'), False),
    ([{'ok': False}], False), ([{'ok': True}], True), ({'success': False}, False)])
def test_metrics_use_structured_outcomes(result, expected):
    assert result_succeeded(result) is expected


def test_prerequisite_task_failure_does_not_submit_dependent_operation():
    api = Mock()
    tools = ProxmoxTool(api)
    api.nodes.return_value.tasks.return_value.status.get.return_value = {'status': 'stopped', 'exitstatus': 'error'}
    with pytest.raises(RuntimeError, match='Prerequisite task failed'):
        tools._wait_for_task('pve', 'old')
    api.nodes.return_value.tasks.return_value.status.get.return_value = {'status': 'running'}
    with pytest.raises(TimeoutError):
        tools._wait_for_task('pve', 'old', timeout_seconds=0)
    with patch('proxmox_mcp.tools.base.time.sleep'):
        api.nodes.return_value.tasks.return_value.status.get.side_effect = [{'status': 'running'}, {'status': 'stopped', 'exitstatus': 'OK'}]
        tools._wait_for_task('pve', 'old')
