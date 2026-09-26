"""Regression contracts from the September audit; no live guests are modified."""
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from proxmoxer.core import ProxmoxResource

from proxmox_mcp.config.models import CommandPolicyConfig
from proxmox_mcp.security.command_policy import CommandPolicyGate
from proxmox_mcp.services.jobs import JobStore
from proxmox_mcp.tools.backup import BackupTools


@pytest.mark.parametrize('mode', ['allowlist', 'audit_only'])
@pytest.mark.parametrize('command', ['rm -rf /audit-placeholder', 'sudo rm\t-rf /audit-placeholder', ':(){:|:&};:'])
def test_default_deny_rules_override_command_permission(mode, command):
    gate = CommandPolicyGate(CommandPolicyConfig(mode=mode, allow_patterns=['.*']))
    decision = gate.evaluate(command)
    assert not decision.allowed
    assert decision.code == 'CMD_POLICY_DENY_PATTERN'
    assert gate.evaluate('uname -a').allowed


class ContractSession:
    """Reject wrong HTTP methods, paths and LXC restore parameters."""
    def __init__(self):
        self.calls = []

    def request(self, method, url, *, data=None, params=None):
        self.calls.append((method, url, data, params))
        if method == 'DELETE':
            assert url.endswith('/nodes/pve/tasks/UPID:audit')
            payload = None
        else:
            assert method == 'POST'
            assert url.endswith('/nodes/pve/lxc')
            assert data['restore'] == 1
            assert data['ostemplate'].startswith(('local:backup/', 'pbs:backup/ct/'))
            assert 'archive' not in data
            assert set(data) <= {'restore', 'ostemplate', 'vmid', 'storage', 'unique'}
            payload = 'UPID:audit'
        return SimpleNamespace(status_code=200, content=b'{}', data=payload)


def contract_api():
    session = ContractSession()
    api = ProxmoxResource(base_url='https://unused/api2/json', session=session,
                          serializer=SimpleNamespace(loads=lambda response: response.data))
    return api, session


@pytest.mark.parametrize('archive', ['local:backup/vzdump-lxc-100.tar.zst', 'pbs:backup/ct/100/2026-09-26T00:00:00Z'])
def test_lxc_restore_and_cancel_http_contract(tmp_path, archive):
    api, session = contract_api()
    with JobStore(api, str(tmp_path / 'jobs.sqlite3')) as store:
        BackupTools(api, job_store=store).restore_backup('pve', archive, '101', storage='local-lvm')
        job = store.list_jobs()[0]
        assert session.calls[0][2] == {'vmid': 101, 'ostemplate': archive, 'restore': 1, 'storage': 'local-lvm', 'unique': 1}
        store.cancel_job(job['job_id'])
        assert session.calls[-1][0] == 'DELETE'
        store._conn.execute("UPDATE jobs SET status = 'failed'")
        store._conn.commit()
    # Reload the persisted recipe, not the live retry/cancel callback.
    with JobStore(api, str(tmp_path / 'jobs.sqlite3')) as store:
        store.retry_job(job['job_id'])
        store.cancel_job(job['job_id'])
        assert session.calls[-1][0] == 'DELETE'


def test_legacy_lxc_restore_recipe_is_repaired(tmp_path):
    api, session = contract_api()
    with JobStore(api, str(tmp_path / 'jobs.sqlite3')) as store:
        job = store.register_task(tool_name='restore_backup', summary='legacy', node='pve', upid='UPID:audit',
            retry_spec={'kind': 'backup.restore', 'params': {'node': 'pve', 'is_lxc': True,
                        'request': {'archive': 'local:backup/vzdump-lxc-100.tar.zst', 'vmid': 101}}})
        store._conn.execute("UPDATE jobs SET status = 'failed'")
        store._conn.commit()
        store.retry_job(job['job_id'])
        assert session.calls[-1][2]['restore'] == 1


@pytest.mark.parametrize('partial', [False, True])
def test_backup_listing_distinguishes_failure_from_empty(partial):
    api = Mock()
    api.nodes.get.return_value = [{'node': 'pve'}]
    api.nodes.return_value.storage.get.return_value = [{'storage': name, 'content': 'backup'} for name in ['bad', 'good']]
    bad, good = Mock(), Mock()
    bad.content.get.side_effect = PermissionError('403 secret-detail')
    good.content.get.return_value = [{'volid': 'good:backup/example', 'vmid': 100}] if partial else []
    api.nodes.return_value.storage.side_effect = lambda name: bad if name == 'bad' else good
    if partial:
        text = BackupTools(api).list_backups()[0].text
        assert 'partial results' in text
        assert 'good:backup/example' in text
        assert 'secret-detail' not in text
    else:
        with pytest.raises(RuntimeError, match='Backup listing incomplete'):
            BackupTools(api).list_backups()


def test_poll_during_retry_preserves_claim_across_stores(tmp_path):
    api = Mock()
    db = str(tmp_path / 'jobs.sqlite3')
    with JobStore(api, db) as writer, JobStore(api, db) as reader:
        def retry():
            assert reader.poll_job(job['job_id'])['status'] == 'retrying'
            return 'UPID:new'
        job = writer.register_task(tool_name='create_backup', summary='race', node='pve', upid='UPID:old', retry_factory=retry)
        writer._conn.execute("UPDATE jobs SET status = 'failed'")
        writer._conn.commit()
        result = writer.retry_job(job['job_id'])
        assert result['upid'] == 'UPID:new'
        assert reader.get_job(job['job_id'])['status'] == 'running'
        api.nodes.assert_not_called()


def test_inflight_poll_cannot_overwrite_retry_claim(tmp_path):
    api = Mock()
    started, release = threading.Event(), threading.Event()
    errors = []
    db = str(tmp_path / 'jobs.sqlite3')
    with JobStore(api, db) as writer, JobStore(api, db) as reader:
        def retry():
            started.set()
            assert release.wait(5)
            return 'UPID:new'
        job = writer.register_task(tool_name='create_backup', summary='race', node='pve', upid='UPID:old', retry_factory=retry)
        writer._conn.execute("UPDATE jobs SET status = 'failed'")
        writer._conn.commit()
        def run_retry():
            try:
                writer.retry_job(job['job_id'])
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=run_retry)
        def status():
            thread.start()
            assert started.wait(5)
            return {'status': 'stopped', 'exitstatus': 'ERROR'}
        api.nodes.return_value.tasks.return_value.status.get.side_effect = status
        api.nodes.return_value.tasks.return_value.log.get.return_value = []
        try:
            assert reader.poll_job(job['job_id'])['status'] == 'retrying'
        finally:
            release.set()
            thread.join(5)
        assert not errors and not thread.is_alive()
        assert reader.get_job(job['job_id'])['upid'] == 'UPID:new'


def test_audit_migration_append_and_optional_retention(tmp_path):
    db = str(tmp_path / 'jobs.sqlite3')
    with JobStore(Mock(), db) as store:
        job = store.register_task(tool_name='test', summary='old', node=None, upid=None)
        # Recreate an old-format database history without needing a fixture binary.
        store._conn.execute('DELETE FROM job_audit_events')
        legacy = [{'timestamp': '2020-01-01T00:00:00+00:00', 'event': 'created', 'details': {'token': 'private'}}]
        store._conn.execute('UPDATE jobs SET audit_log_json = ?', (json.dumps(legacy),))
        store._conn.commit()
    with JobStore(Mock(), db) as store:
        assert len(store.get_job(job['job_id'])['audit_log']) == 1
        store.poll_job(job['job_id'])
        assert store._conn.execute('SELECT audit_log_json FROM jobs').fetchone()[0] == '[]'
        assert store._conn.execute('SELECT COUNT(*) FROM job_audit_events').fetchone()[0] == 2
        assert 'private' not in store._conn.execute('SELECT details_json FROM job_audit_events ORDER BY id').fetchone()[0]
    with JobStore(Mock(), db, audit_retention_days=1) as store:
        store.poll_job(job['job_id'])
        history = store.get_job(job['job_id'])['audit_log']
        assert len(history) == 2
        assert all(event['event'] == 'poll_skipped' for event in history)
    with JobStore(Mock(), db) as store:
        assert len(store.get_job(job['job_id'])['audit_log']) == 2
