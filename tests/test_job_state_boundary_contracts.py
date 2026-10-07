"""Durable job state conflicts and retry rollback contracts."""

import json
from unittest.mock import Mock

import pytest

from proxmox_mcp.services.jobs import JobStore, JobConflictError, JobNotFoundError, _is_secret_key
from proxmox_mcp.tools.jobs import JobsTools


@pytest.fixture
def store(tmp_path):
    api = Mock()
    api.nodes.return_value.tasks.return_value.status.get.return_value = {'status': 'stopped', 'exitstatus': 'ERROR'}
    api.nodes.return_value.tasks.return_value.log.get.return_value = []
    with JobStore(api, str(tmp_path / 'jobs.sqlite')) as value:
        yield value


def failed_job(store, **options):
    job = store.register_task(tool_name='start_vm', summary='Start guest', node='pve', upid='UPID:pve:old', **options)
    store.poll_job(job['job_id'])
    return job['job_id']


def test_uncertain_submission_does_not_replace_concurrent_terminal_state(store):
    def concurrent_completion():
        store._conn.execute("UPDATE jobs SET status='completed' WHERE job_id=?", (job_id,))
        store._conn.commit()
        raise TimeoutError('ambiguous result')
    job_id = failed_job(store, retry_factory=concurrent_completion)
    with pytest.raises(TimeoutError):
        store.retry_job(job_id)
    result = store.get_job(job_id)
    assert result['status'] == 'completed'
    assert result['audit_log'][-1]['event'] == 'retry_interrupted'


@pytest.mark.parametrize('recipe', [None, {'kind': 'vm.start', 'params': None}, {'kind': 'missing', 'params': {}}])
def test_retry_rejects_missing_malformed_or_unavailable_recipes(store, recipe):
    job_id = failed_job(store, retry_spec=recipe)
    with pytest.raises(JobConflictError):
        store.retry_job(job_id)
    assert store.get_job(job_id)['status'] == 'failed'


def test_retry_failure_rolls_back_claim_and_preserves_sanitized_audit(store):
    job_id = failed_job(store, retry_factory=Mock(side_effect=RuntimeError('password=private')))
    with pytest.raises(RuntimeError):
        store.retry_job(job_id)
    record = store.get_job(job_id)
    assert record['status'] == 'failed'
    assert record['attempts'] == 1
    assert 'private' not in json.dumps(record)
    assert record['audit_log'][-1]['event'] == 'retry_failed'


def test_cancel_without_upid_and_cancel_pending_are_distinct(store):
    job = store.register_task(tool_name='start_vm', summary='No task', node=None, upid=None)
    with pytest.raises(JobConflictError):
        store.cancel_job(job['job_id'])
    job = store.register_task(tool_name='start_vm', summary='Running task', node='pve', upid='UPID:pve:running')
    store.cancel_job(job['job_id'])
    store.proxmox.nodes.return_value.tasks.return_value.status.get.return_value = {'status': 'running'}
    assert store.poll_job(job['job_id'])['status'] == 'cancel_requested'


def test_cancel_race_preserves_terminal_state(store):
    job_id = None
    def cancel(upid):
        with store._write_transaction():
            store._conn.execute("UPDATE jobs SET status='completed' WHERE job_id=?", (job_id,))
    job = store.register_task(tool_name='start_vm', summary='Cancel race', node='pve', upid='UPID:pve:old', cancel_factory=cancel)
    job_id = job['job_id']
    result = store.cancel_job(job_id)
    assert result['status'] == 'completed'
    assert result['audit_log'][-1]['event'] == 'cancel_discarded'


@pytest.mark.parametrize('failure', [False, True])
def test_retry_result_does_not_overwrite_concurrent_worker_state(store, failure):
    job_id = None
    def retry():
        with store._write_transaction():
            store._conn.execute("UPDATE jobs SET status='completed',upid='UPID:pve:other' WHERE job_id=?", (job_id,))
        if failure:
            raise RuntimeError('backend rejected retry')
        return 'UPID:pve:new'
    job_id = failed_job(store, retry_factory=retry)
    with pytest.raises((RuntimeError, JobConflictError)):
        store.retry_job(job_id)
    result = store.get_job(job_id)
    assert result['status'] == 'completed'
    assert result['upid'] == 'UPID:pve:other'
    assert result['audit_log'][-1]['event'] == ('retry_failure_discarded' if failure else 'retry_result_discarded')


def test_stale_claim_and_unknown_job_are_rejected(store):
    job_id = failed_job(store, retry_factory=lambda: 'UPID:pve:new')
    record = store._load_record_from_db(job_id)
    with store._write_transaction():
        store._conn.execute("UPDATE jobs SET status='completed' WHERE job_id=?", (job_id,))
        with pytest.raises(JobConflictError):
            store._claim_retry(record)
    assert store._get_record(job_id).job_id == job_id
    with pytest.raises(JobNotFoundError):
        store._get_record('unknown')
    with pytest.raises(JobNotFoundError):
        store.get_job('unknown')


@pytest.mark.parametrize('payload, status', [(None, 'unknown'), ({'status': 'error'}, 'failed'), ({'status': 'unexpected'}, 'running')])
def test_unknown_and_error_task_status_are_not_success(store, payload, status):
    assert store._normalize_status(payload)[0] == status
    assert store._extract_progress(None) is None
    assert store._extract_progress(['progress 101%', {'msg': 'progress 50%'}, 'done 75%']) == 75


def test_retention_is_opt_in_and_initialization_failure_closes_connection(store):
    assert _is_secret_key('password') is True
    store.prune_audit_events()
    with pytest.raises(ValueError):
        JobStore(Mock(), ':memory:', audit_retention_days=0)
    from unittest.mock import patch
    connection = Mock()
    with patch('proxmox_mcp.services.jobs.sqlite3.connect', return_value=connection), \
         patch.object(JobStore, '_configure_connection', side_effect=RuntimeError('failed setup')):
        with pytest.raises(RuntimeError, match='failed setup'):
            JobStore(Mock(), ':memory:')
    connection.close.assert_called_once()


def test_job_tools_refresh_poll_cancel_and_reconcile(store):
    job_id = failed_job(store, retry_factory=lambda: 'UPID:pve:new')
    tools = JobsTools(store)
    assert json.loads(tools.get_job(job_id)[0].text)['status'] == 'failed'
    assert json.loads(tools.get_job(job_id, refresh=True)[0].text)['status'] == 'failed'
    tools.retry_job(job_id)
    assert json.loads(tools.cancel_job(job_id)[0].text)['status'] == 'cancel_requested'
    assert json.loads(tools.poll_job(job_id)[0].text)['status'] == 'failed'
