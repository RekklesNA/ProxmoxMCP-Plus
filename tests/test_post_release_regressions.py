"""Second-review regressions through real MCP and prepared HTTP requests."""

import json
from unittest.mock import Mock, patch

import pytest
import requests
from proxmoxer import ProxmoxAPI

from proxmox_mcp.config.models import Config, CommandPolicyConfig
from proxmox_mcp.models.tooling import result_status
from proxmox_mcp.security.command_policy import CommandPolicyGate
from proxmox_mcp.server import ProxmoxMCPServer
from proxmox_mcp.services.jobs import JobStore
from proxmox_mcp.tools.backup import BackupTools
from proxmox_mcp.tools.snapshots import SnapshotTools
from proxmox_mcp.security.resources import validate_guest_id, submit_snapshot_rollback
from proxmox_mcp.security.command_policy import _tokens_match


@pytest.mark.asyncio
async def test_vm_description_mcp_rejects_container_path_injection(tmp_path):
    api = ProxmoxAPI('pve.invalid', user='root@pam', token_name='audit', token_value='fake')
    captured = []
    def transport(method, url, **options):
        prepared = requests.Request(method, url, data=options.get('data')).prepare()
        captured.append((prepared.method, prepared.url, prepared.body))
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"data":null}'
        return response
    api._store['session'].request = transport
    config = Config.model_validate({'proxmox': {'host': 'pve.invalid'},
        'auth': {'user': 'root@pam', 'token_name': 'audit', 'token_value': 'fake'},
        'jobs': {'sqlite_path': str(tmp_path / 'jobs.sqlite')},
        'mcp': {'tool_allowlist': ['set_vm_description']}})
    with patch('proxmox_mcp.server.load_config', return_value=config), patch('proxmox_mcp.core.proxmox.ProxmoxAPI', return_value=api):
        server = ProxmoxMCPServer()
    try:
        with pytest.raises(Exception, match='positive ASCII integer'):
            await server.mcp.call_tool('set_vm_description', {'node': 'pve', 'vmid': '../lxc/200', 'description': 'post-review-probe'})
        assert captured == []
        await server.mcp.call_tool('set_vm_description', {'node': 'pve', 'vmid': '100', 'description': 'post-review-probe'})
        assert captured == [('PUT', 'https://pve.invalid:8006/api2/json/nodes/pve/qemu/100/config', 'description=post-review-probe')]
        assert server.tool_registry.registered_tools == {'set_vm_description'}
    finally:
        server.close()


@pytest.mark.parametrize('restart', [False, True])
def test_snapshot_retry_rechecks_new_child_guard(tmp_path, restart):
    api = Mock()
    guest = api.nodes.return_value.qemu.return_value
    guest.snapshot.get.return_value = [{'name': 'base'}]
    guest.snapshot.return_value.rollback.post.return_value = 'UPID:pve:rollback'
    api.nodes.return_value.tasks.return_value.status.get.return_value = {'status': 'stopped', 'exitstatus': 'ERROR'}
    api.nodes.return_value.tasks.return_value.log.get.return_value = []
    path = str(tmp_path / 'jobs.sqlite')
    store = JobStore(api, path)
    try:
        initial = SnapshotTools(api, job_store=store).rollback_snapshot('pve', '100', 'base')
        job_id = json.loads(initial[-1].text)['job_id']
        store.poll_job(job_id)
        guest.snapshot.get.return_value = [{'name': 'base'}, {'name': 'newer', 'parent': 'base'}]
        with pytest.raises(ValueError, match='newer child'):
            SnapshotTools(api, job_store=store).rollback_snapshot('pve', '100', 'base')
        if restart:
            store.close()
            store = JobStore(api, path)
        with pytest.raises(ValueError, match='newer child'):
            store.retry_job(job_id)
        assert store.get_job(job_id)['status'] == 'failed'
        assert guest.snapshot.return_value.rollback.post.call_count == 1
        guest.snapshot.get.return_value = [{'name': 'base'}]
        assert store.retry_job(job_id)['status'] == 'running'
        assert guest.snapshot.return_value.rollback.post.call_count == 2
    finally:
        store.close()


def test_non_ascii_approval_token_is_denied_without_exception():
    policy = CommandPolicyGate(CommandPolicyConfig(mode='audit_only', require_approval_token=True, approval_token='ascii-secret'))
    assert policy.evaluate('uname', approval_token='nonascii-\u00e9').allowed is False


def test_backup_partial_inventory_reports_partial_status():
    api = Mock()
    api.nodes.get.return_value = [{'node': 'good'}, {'node': 'bad'}]
    good, bad = Mock(), Mock()
    api.nodes.side_effect = lambda node: good if node == 'good' else bad
    good.storage.get.return_value = [{'storage': 'local', 'content': 'backup'}]
    good.storage.return_value.content.get.return_value = [{'volid': 'local:backup/a.vma', 'content': 'backup'}]
    bad.storage.get.side_effect = RuntimeError('node unreachable')
    result = BackupTools(api).list_backups()
    assert len(result) == 2
    assert result_status(result) == 'partial'
    assert 'partial' in result[0].text


def test_documented_full_command_matching_actually_uses_substring_search():
    policy = CommandPolicyGate(CommandPolicyConfig(mode='allowlist', allow_patterns=['uname']))
    assert policy.evaluate('echo different-command; uname').allowed is True


@pytest.mark.parametrize('value', ['../lxc/200', '100?x=', '100#fragment', '100/..', '0', '-1', '', None, True, 1.5, '\u0661\u0660\u0660'])
def test_guest_identifiers_reject_paths_and_non_ascii_numbers(value):
    with pytest.raises(ValueError):
        validate_guest_id(value)
    assert validate_guest_id(100) == '100'


@pytest.mark.parametrize('provided, expected, allowed', [('caf\u00e9', 'caf\u00e9', True),
    ('other', 'caf\u00e9', False), ('\ud800', 'secret', False), ('secret', '\ud800', False), (1, 'secret', False)])
def test_approval_comparison_handles_unicode_and_invalid_text(provided, expected, allowed):
    assert _tokens_match(provided, expected) is allowed


@pytest.mark.parametrize('inventory', [None, {'data': None}, 'unknown', [1]])
def test_snapshot_rollback_refuses_incomplete_inventory(inventory):
    api = Mock()
    guest = api.nodes.return_value.qemu.return_value
    guest.snapshot.get.return_value = inventory
    with pytest.raises(RuntimeError, match='inventory'):
        submit_snapshot_rollback(api, 'pve', '100', 'base', 'qemu')
    guest.snapshot.return_value.rollback.post.assert_not_called()


def test_snapshot_rollback_validates_guest_type_and_unwraps_inventory():
    api = Mock()
    with pytest.raises(ValueError, match='guest type'):
        submit_snapshot_rollback(api, 'pve', '100', 'base', 'other')
    guest = api.nodes.return_value.lxc.return_value
    guest.snapshot.get.return_value = {'data': [{'name': 'current', 'parent': 'base'}]}
    guest.snapshot.return_value.rollback.post.return_value = 'UPID:pve:rollback'
    assert submit_snapshot_rollback(api, 'pve', '100', 'base', 'lxc') == 'UPID:pve:rollback'
