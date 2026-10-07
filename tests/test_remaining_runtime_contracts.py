"""Fallback and malformed response contracts for public runtime boundaries."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from proxmox_mcp.code_mode import _schema, _source_allowed
from proxmox_mcp.config.models import Config, MCPConfig
from proxmox_mcp.config.loader import load_config, _apply_mcp_env_overrides
from proxmox_mcp.formatting.templates import ProxmoxTemplates
from proxmox_mcp.openapi_proxy import create_app
from proxmox_mcp.services.jobs import JobStore, JobConflictError
from proxmox_mcp.services.tool_registry import ToolRegistry, ToolExposurePolicy
from proxmox_mcp.tools.base import ProxmoxTool
from proxmox_mcp.tools.node import NodeTools
from proxmox_mcp.tools.logs import LogTools
from proxmox_mcp.tools.iso import ISOTools
from proxmox_mcp.tools.backup import BackupTools
from proxmox_mcp.tools.snapshots import SnapshotTools
from proxmox_mcp.tools.storage import StorageTools
from proxmox_mcp.tools.jobs import JobsTools


def test_schema_fallbacks_and_invalid_source():
    assert _schema(Mock(fn_metadata=None)) == {'type': 'object', 'properties': {}}
    model = Mock()
    model.model_json_schema.side_effect = ValueError('unsupported')
    assert _schema(SimpleNamespace(fn_metadata=SimpleNamespace(arg_model=model)))['properties'] == {}
    assert _source_allowed('if (') is False


def test_configuration_filter_and_missing_credentials():
    with pytest.raises(ValueError, match='empty'):
        MCPConfig(tool_allowlist=[' '])
    with pytest.raises(ValueError, match='requires either'):
        Config()
    with pytest.raises(ValueError, match='mutually exclusive'):
        ToolExposurePolicy(allowlist=[], denylist=[])
    mcp = Mock()
    registry = ToolRegistry()
    registry.register_all(SimpleNamespace(mcp=mcp))
    assert registry._mcp is mcp


def test_environment_policy_overrides_and_object_validation(monkeypatch):
    monkeypatch.setenv('MCP_CODE_MODE_POOL_REUSE', 'true')
    value = {}
    _apply_mcp_env_overrides(value)
    assert value['mcp']['code_mode_pool_reuse'] is True
    with pytest.raises(ValueError, match='JSON object'):
        _apply_mcp_env_overrides({'mcp': []})
    monkeypatch.setenv('PROXMOX_HOST', 'pve.invalid')
    monkeypatch.setenv('PROXMOX_USER', 'root@pam')
    monkeypatch.setenv('PROXMOX_TOKEN_NAME', 'audit')
    monkeypatch.setenv('PROXMOX_TOKEN_VALUE', 'fake')
    monkeypatch.setenv('COMMAND_POLICY_DENY_PATTERNS', 'danger')
    monkeypatch.setenv('COMMAND_POLICY_HIGH_RISK_OPERATIONS', 'delete_vm')
    config = load_config()
    assert config.command_policy.deny_patterns == ['danger']
    assert config.command_policy.high_risk_operations == ['delete_vm']


def test_node_basic_fallback_keeps_disk_and_offline_status():
    api = Mock()
    api.nodes.get.return_value = [{'node': 'pve', 'status': 'online', 'disk': {'used': 1024, 'total': 2048}}]
    api.nodes.return_value.status.get.side_effect = RuntimeError('unreachable')
    result = NodeTools(api).get_nodes()[0].text
    assert 'pve' in result and 'ONLINE' in result
    assert 'Disk:' in ProxmoxTemplates.node_list([{'node': 'pve', 'disk': {'used': 1024, 'total': 2048}}])
    assert 'Resources: 1' in ProxmoxTemplates.cluster_status({'resources': [{}]})


def test_node_list_failure_and_status_fallback_errors(monkeypatch):
    monkeypatch.setattr('proxmox_mcp.tools.base.time.sleep', lambda _: None)
    api = Mock()
    api.nodes.get.side_effect = RuntimeError('unreachable')
    with pytest.raises(RuntimeError):
        NodeTools(api).get_nodes()
    api.nodes.return_value.status.get.side_effect = RuntimeError('unreachable')
    with pytest.raises(RuntimeError):
        NodeTools(api).get_node_status('pve')
    api.nodes.get.side_effect = None
    for entries in [[{'node': 'other'}], [{'node': 'pve', 'status': 'online'}]]:
        api.nodes.get.return_value = entries
        with pytest.raises(RuntimeError):
            NodeTools(api).get_node_status('pve')


def test_log_formatters_accept_text_and_unknown_timestamps():
    tools = LogTools(Mock())
    assert '42' in tools._format_task_log([42], 'UPID:pve:task')
    assert '[?]' in tools._format_cluster_log([{}, 'raw'])
    assert '42' in tools._format_log_entries([42], 'syslog', 'pve')


def test_storage_cache_and_content_failures():
    api = Mock()
    api.storage.get.return_value = []
    api.nodes.get.return_value = [{'node': 'pve'}]
    tools = StorageTools(api)
    assert tools.get_storage()[0].text == tools.get_storage()[0].text
    api.storage.get.assert_called_once()
    api.nodes.return_value.storage.get.return_value = [{'storage': 'local', 'content': 'iso'}]
    api.nodes.return_value.storage.return_value.content.get.side_effect = RuntimeError('unreachable')
    with pytest.raises(RuntimeError, match='inventory'):
        ISOTools(api).list_isos()
    assert json.loads(ISOTools(api)._json_fmt({'value': 1})[0].text) == {'value': 1}
    assert json.loads(BackupTools(api)._json_fmt({'value': 1})[0].text) == {'value': 1}


def test_backup_bad_timestamp_and_snapshot_delete_failure():
    api = Mock()
    api.nodes.get.return_value = [{'node': 'pve'}]
    api.nodes.return_value.storage.get.return_value = [{'storage': 'local', 'content': 'backup'}]
    api.nodes.return_value.storage.return_value.content.get.return_value = [{'ctime': 'invalid', 'volid': 'local:backup/a'}]
    assert 'invalid' in BackupTools(api).list_backups()[0].text
    api.nodes.return_value.qemu.return_value.snapshot.get.return_value = [{'name': 'base'}]
    api.nodes.return_value.qemu.return_value.snapshot.return_value.delete.side_effect = RuntimeError('unreachable')
    with pytest.raises(RuntimeError):
        SnapshotTools(api).delete_snapshot('pve', '100', 'base')


def test_prerequisite_task_rejects_malformed_status():
    api = Mock()
    api.nodes.return_value.tasks.return_value.status.get.return_value = []
    with pytest.raises(RuntimeError, match='invalid status'):
        ProxmoxTool(api)._wait_for_task('pve', 'UPID:pve:task')


@pytest.mark.parametrize('error', [TimeoutError('unknown submission'), ConnectionError('unknown submission')])
def test_submission_timeout_requires_reconciliation_and_summary_preserves_history(tmp_path, error):
    api = Mock()
    api.nodes.return_value.tasks.return_value.status.get.return_value = {'status': 'stopped', 'exitstatus': 'ERROR'}
    api.nodes.return_value.tasks.return_value.log.get.return_value = []
    with JobStore(api, str(tmp_path / 'jobs.sqlite')) as store:
        job = store.register_task(tool_name='create_vm', summary='Create', node='pve', upid='UPID:pve:old', retry_factory=Mock(side_effect=error))
        statements = []
        store._conn.set_trace_callback(statements.append)
        result = store.poll_job(job['job_id'], include_audit=False)
        assert result['status'] == 'failed'
        assert [e['event'] for e in result['audit_log']] == ['polled']
        assert not any('SELECT timestamp, event' in s for s in statements)
        with pytest.raises(type(error)):
            store.retry_job(job['job_id'])
        assert store.get_job(job['job_id'])['status'] == 'needs_reconciliation'
        with pytest.raises(JobConflictError):
            store.retry_job(job['job_id'])
        payload = json.loads(JobsTools(store).reconcile_job(job['job_id'], confirmed_not_submitted=True)[0].text)
        assert payload['status'] == 'failed'
        assert [e['event'] for e in store.get_audit(job['job_id'])] == ['created', 'polled', 'retry_started', 'retry_interrupted', 'retry_reconciled']


def test_proxy_audit_not_found_has_safe_error():
    store = Mock()
    from proxmox_mcp.services.jobs import JobNotFoundError
    store.get_audit.side_effect = JobNotFoundError('private detail')
    app = create_app(['unused'], api_key=None, strict_auth=False, cors_allow_origins=[], job_store=store)
    client = TestClient(app)
    try:
        response = client.get('/jobs/missing/audit')
        assert response.status_code == 404
        assert 'private detail' not in response.text
    finally:
        client.close()
