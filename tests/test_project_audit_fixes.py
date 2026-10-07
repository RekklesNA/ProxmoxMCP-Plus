"""Regression tests for the independently reproduced project audit findings."""
import asyncio
import json
import time
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from proxmox_mcp.config.models import Config, SSHConfig
from proxmox_mcp.openapi_proxy import create_app
from proxmox_mcp.server import ProxmoxMCPServer
from proxmox_mcp.services.jobs import JobStore, JobConflictError
from proxmox_mcp.tools.iso import ISOTools
from proxmox_mcp.tools.backup import BackupTools
from proxmox_mcp.tools.vm import VMTools
from proxmox_mcp.tools.containers import ContainerTools
from proxmox_mcp.tools.console.container_manager import ContainerConsoleManager
from proxmox_mcp.formatting.formatters import ProxmoxFormatters
from proxmox_mcp.tools.console.manager import VMConsoleManager
from proxmox_mcp.tools.storage import StorageTools
from proxmox_mcp.mcp_oauth_provider import MCPApiKeyOAuthProvider
from proxmox_mcp.security.command_policy import CommandPolicyGate
from proxmox_mcp.config.models import CommandPolicyConfig
from proxmoxer import ProxmoxAPI
import requests
import logging


def config(tmp_path, **overrides):
    value = dict(proxmox={'host': 'audit.invalid'},
                 auth={'user': 'audit@pve', 'token_name': 'test', 'token_value': 'fake'},
                 jobs={'sqlite_path': str(tmp_path / 'jobs.sqlite3')})
    value.update(overrides)
    return Config.model_validate(value)


def test_iso_substring_selects_exact_volume():
    api = Mock()
    endpoint = api.nodes.return_value.storage.return_value.content
    endpoint.get.return_value = [
        {'volid': 'local:iso/old-debian.iso', 'content': 'iso'},
        {'volid': 'local:iso/debian.iso', 'content': 'iso'},
    ]
    endpoint.return_value.delete.return_value = None
    ISOTools(api).delete_iso('pve1', 'local', 'debian.iso')
    endpoint.assert_called_once_with('local:iso/debian.iso')


@pytest.mark.parametrize('tool', ['iso', 'backup'])
def test_delete_tools_reject_guest_disk_volume(tool):
    api = Mock()
    endpoint = api.nodes.return_value.storage.return_value.content
    endpoint.get.return_value = []
    endpoint.return_value.delete.return_value = None
    volume = 'local:images/100/vm-100-disk-0.qcow2'
    with pytest.raises(ValueError):
        if tool == 'iso':
            ISOTools(api).delete_iso('pve1', 'local', volume)
        else:
            BackupTools(api).delete_backup('pve1', 'local', volume)
    endpoint.return_value.delete.assert_not_called()


def test_force_vm_delete_waits_for_stop():
    api = Mock()
    vm = api.nodes.return_value.qemu.return_value
    vm.status.current.get.return_value = {'status': 'running', 'name': 'audit'}
    vm.status.stop.post.return_value = 'UPID:pve1:stop'
    api.nodes.return_value.tasks.return_value.status.get.return_value = {'status': 'stopped', 'exitstatus': 'OK'}
    vm.delete.return_value = 'UPID:pve1:delete'
    VMTools(api).delete_vm('pve1', '100', force=True)
    vm.status.current.get.assert_called_once()
    vm.status.stop.post.assert_called_once()
    vm.delete.assert_called_once()
    api.nodes.return_value.tasks.return_value.status.get.assert_called_once()


def test_force_container_delete_waits_for_stop():
    api = Mock()
    ct = api.nodes.return_value.lxc.return_value
    ct.status.current.get.return_value = {'status': 'running'}
    ct.status.stop.post.return_value = 'UPID:pve1:stop'
    api.nodes.return_value.tasks.return_value.status.get.return_value = {'status': 'stopped', 'exitstatus': 'OK'}
    ct.delete.return_value = 'UPID:pve1:delete'
    tools = ContainerTools(api)
    with patch.object(tools, '_resolve_targets', return_value=[('pve1', 100, 'audit')]):
        result = json.loads(tools.delete_container('100', force=True, format_style='json')[0].text)
    assert result[0]['ok'] is True
    ct.status.current.get.assert_called_once()
    api.nodes.return_value.tasks.return_value.status.get.assert_called_once()


@pytest.mark.asyncio
async def test_custom_high_risk_operation_is_enforced(tmp_path):
    policy = {'high_risk_mode': 'enforce', 'high_risk_operations': ['start_vm'],
              'high_risk_require_approval_token': True, 'high_risk_approval_token': 'fake-approval'}
    api = Mock()
    vm = api.nodes.return_value.qemu.return_value
    vm.status.current.get.return_value = {'status': 'stopped'}
    vm.status.start.post.return_value = 'UPID:pve1:start'
    with patch('proxmox_mcp.server.load_config', return_value=config(tmp_path, command_policy=policy)), \
         patch('proxmox_mcp.core.proxmox.ProxmoxAPI', return_value=api):
        server = ProxmoxMCPServer()
    try:
        assert not server.command_policy.evaluate_operation('start_vm').allowed
        from mcp.server.fastmcp.exceptions import ToolError
        with pytest.raises(ToolError, match='approval token'):
            await server.mcp.call_tool('start_vm', {'node': 'pve1', 'vmid': '100'})
        vm.status.start.post.assert_not_called()
        await server.mcp.call_tool('start_vm', {'node': 'pve1', 'vmid': '100', 'approval_token': 'fake-approval'})
        vm.status.start.post.assert_called_once()
    finally:
        server.close()


@pytest.mark.asyncio
async def test_real_fastmcp_dispatch_keeps_event_loop_responsive(tmp_path):
    api = Mock()
    def delayed_status():
        time.sleep(0.25)
        return {'status': 'online', 'cpu': 0, 'cpuinfo': {'cpus': 4},
                'memory': {'used': 0, 'total': 100}, 'uptime': 1}
    api.nodes.return_value.status.get.side_effect = delayed_status
    with patch('proxmox_mcp.server.load_config', return_value=config(tmp_path)), \
         patch('proxmox_mcp.core.proxmox.ProxmoxAPI', return_value=api):
        server = ProxmoxMCPServer()
    try:
        start = time.perf_counter()
        async def heartbeat():
            await asyncio.sleep(0.02)
            return time.perf_counter() - start
        tick = asyncio.create_task(heartbeat())
        await asyncio.sleep(0)
        await server.mcp.call_tool('get_node_status', {'node': 'pve1'})
        lag = await tick
        print(f'event-loop heartbeat: expected 20ms, observed {lag * 1000:.1f}ms')
        assert lag < 0.20
    finally:
        server.close()


def test_unauthenticated_paths_use_bounded_metric_labels():
    app = create_app(['unused'], api_key='fake-key', strict_auth=True, cors_allow_origins=[])
    client = TestClient(app)
    try:
        for i in range(100):
            assert client.get(f'/random-{i}').status_code == 401
        assert len(app.state.http_metrics._series) == 1
    finally:
        client.close()


def test_retry_claim_requires_reconciliation_after_crash(tmp_path):
    path = str(tmp_path / 'retry.sqlite3')
    api = Mock()
    api.nodes.return_value.tasks.return_value.status.get.return_value = {'status': 'stopped', 'exitstatus': 'error'}
    api.nodes.return_value.tasks.return_value.log.get.return_value = []
    store = JobStore(api, sqlite_path=path)
    def crash():
        raise KeyboardInterrupt('simulated process interruption during remote replay')
    job = store.register_task(tool_name='start_vm', summary='audit', node='pve1', upid='old',
                              retry_spec={'kind': 'vm.start', 'params': {'node': 'pve1', 'vmid': '100'}},
                              retry_factory=crash)
    store.poll_job(job['job_id'])
    with pytest.raises(KeyboardInterrupt):
        store.retry_job(job['job_id'])
    store.close()
    store = JobStore(api, sqlite_path=path)
    try:
        assert store.get_job(job['job_id'])['status'] == 'needs_reconciliation'
        assert store.poll_job(job['job_id'])['status'] == 'needs_reconciliation'
        with pytest.raises(JobConflictError):
            store.retry_job(job['job_id'])
        with pytest.raises(JobConflictError):
            store.cancel_job(job['job_id'])
    finally:
        store.close()


def test_system_ssh_honors_configured_host_key_policy():
    manager = ContainerConsoleManager(Mock(), SSHConfig(prefer_ssh_client=True,
                                                       strict_host_key_checking=True,
                                                       known_hosts_file='/audit/pinned-hosts'))
    with patch('proxmox_mcp.tools.console.container_manager.run_bounded') as run:
        run.return_value = Mock(returncode=0, stdout='', stderr='')
        manager._execute_via_system_ssh('pve1', 'true')
    argv = run.call_args.args[0]
    assert 'StrictHostKeyChecking=yes' in argv
    assert any('pinned-hosts' in arg for arg in argv)


def test_petabyte_format_preserves_magnitude():
    assert ProxmoxFormatters.format_bytes(1024 ** 5) == '1.00 PB'


def response(payload):
    result = requests.Response()
    result.status_code = 200
    result._content = json.dumps({'data': payload}).encode()
    return result


def real_api():
    return ProxmoxAPI('audit.invalid', user='audit@pve', token_name='fake', token_value='fake')


@pytest.mark.parametrize('tool', ['iso', 'backup'])
def test_volume_path_cannot_escape_into_user_management_endpoint(tool):
    sent = []
    def send(session, request, **kwargs):
        sent.append((request.method, request.url))
        return response([] if request.method == 'GET' else None)
    with patch.object(requests.Session, 'send', new=send):
        volume = '../../../../../access/users/audit-user@pve?audit:probe'
        with pytest.raises(ValueError):
            if tool == 'iso':
                ISOTools(real_api()).delete_iso('pve1', 'local', volume)
            else:
                BackupTools(real_api()).delete_backup('pve1', 'local', volume)
    assert not sent


def test_default_proxmoxer_logger_suppresses_request_password(caplog):
    def send(session, request, **kwargs):
        path = request.path_url.split('?')[0]
        if path.endswith('/cluster/resources'):
            return response([])
        if path.endswith('/nodes'):
            return response([{'node': 'pve1'}])
        if path.endswith('/storage'):
            return response([{'storage': 'local-lvm', 'content': 'rootdir', 'type': 'lvmthin'}])
        if path.endswith('/nodes/pve1/lxc') and request.method == 'POST':
            return response('UPID:pve1:create')
        if path.endswith('/nodes/pve1/lxc'):
            return response([])
        raise AssertionError(path)
    with caplog.at_level(logging.INFO), patch.object(requests.Session, 'send', new=send):
        ContainerTools(real_api()).create_container('pve1', '100', 'local:vztmpl/audit.tar.gz',
                                                     password='fake-audit-root-password')
    # Disproved candidate: dependency logger is explicitly WARNING by default.
    assert 'fake-audit-root-password' not in caplog.text


@pytest.mark.asyncio
async def test_vm_killed_by_signal_reported_failure():
    api = Mock()
    api.nodes.return_value.qemu.return_value.status.current.get.return_value = {'status': 'running'}
    agent = api.nodes.return_value.qemu.return_value.agent
    endpoints = {
        'info': Mock(), 'exec': Mock(), 'exec-status': Mock()
    }
    endpoints['info'].get.return_value = {'supported_commands': [{'name': 'guest-exec', 'enabled': True}]}
    endpoints['exec'].post.return_value = {'pid': 100}
    endpoints['exec-status'].get.return_value = {'exited': 1, 'signal': 9}
    agent.side_effect = lambda action: endpoints[action]
    result = await VMConsoleManager(api).execute_command('pve1', '100', 'true')
    assert result['success'] is False
    assert result['exit_code'] == -9
    assert result['signal'] == 9


def test_rrd_fallback_uses_supported_parameters():
    api = Mock()
    endpoint = api.nodes.return_value.lxc.return_value.rrddata
    def validate(**kwargs):
        assert kwargs == {'timeframe': 'hour'}
        return [{'cpu': 0.25, 'mem': 100, 'maxmem': 200}]
    endpoint.get.side_effect = validate
    assert ContainerTools(api)._rrd_last('pve1', 100) == (25, 100, 200)
    endpoint.get.assert_called_once()


def test_storage_inactive_is_reported_offline():
    api = Mock()
    api.storage.get.return_value = [{'storage': 'nfs', 'type': 'nfs', 'content': 'images', 'disable': 0}]
    api.nodes.get.return_value = [{'node': 'pve1', 'status': 'online'}]
    api.nodes.return_value.storage.return_value.status.get.return_value = {
        'enabled': 1, 'active': 0, 'total': 0, 'used': 0, 'avail': 0
    }
    tools = StorageTools(api)
    with patch.object(tools, '_format_response', side_effect=lambda data, kind: data):
        result = tools.get_storage()
    assert result[0]['status'] == 'offline'


def test_storage_status_lookup_failure_is_reported_offline_when_disabled():
    api = Mock()
    api.storage.get.return_value = [{'storage': 'nfs', 'type': 'nfs', 'content': 'images', 'disable': 1}]
    api.nodes.get.return_value = [{'node': 'pve1', 'status': 'online'}]
    api.nodes.return_value.storage.return_value.status.get.side_effect = RuntimeError('unreachable')
    tools = StorageTools(api)
    with patch.object(tools, '_format_response', side_effect=lambda data, kind: data):
        result = tools.get_storage()
    assert result[0]['status'] == 'offline'


def test_container_resize_upid_is_registered():
    api = Mock()
    api.nodes.return_value.lxc.return_value.resize.put.return_value = 'UPID:pve1:resize'
    store = Mock()
    store.register_task.return_value = {'job_id': 'resize-job'}
    tools = ContainerTools(api, job_store=store)
    with patch.object(tools, '_resolve_targets', return_value=[('pve1', 100, 'audit')]):
        result = json.loads(tools.update_container_resources('100', disk_gb=5, format_style='json')[0].text)
    assert result[0]['ok'] is True
    assert result[0]['task_id'] == 'UPID:pve1:resize'
    assert result[0]['status'] == 'submitted'
    store.register_task.assert_called_once()


def test_container_inventory_errors_are_reported():
    api = Mock()
    api.cluster.resources.get.side_effect = RuntimeError('cluster inventory unavailable')
    api.nodes.get.return_value = [{'node': 'pve1'}]
    api.nodes.return_value.lxc.get.side_effect = RuntimeError('node inventory unavailable')
    with pytest.raises(RuntimeError, match='inventory is unavailable'):
        ContainerTools(api).get_containers(format_style='json')


def test_bulk_action_errors_are_sanitized():
    api = Mock()
    api.nodes.return_value.lxc.return_value.status.start.post.side_effect = RuntimeError('password=fake-audit-password')
    tools = ContainerTools(api)
    with patch.object(tools, '_resolve_targets', return_value=[('pve1', 100, 'audit')]):
        result = tools.start_container('100', format_style='json')[0].text
    assert 'fake-audit-password' not in result


@pytest.mark.asyncio
async def test_denied_command_counted_error(tmp_path):
    with patch('proxmox_mcp.server.load_config', return_value=config(tmp_path)), \
         patch('proxmox_mcp.core.proxmox.ProxmoxAPI', return_value=Mock()):
        server = ProxmoxMCPServer()
    try:
        result = await server.mcp.call_tool('execute_vm_command', {'node': 'pve1', 'vmid': '100', 'command': 'uname'})
        assert 'CMD_POLICY_NOT_ALLOWLISTED' in str(result)
        snapshot = server.metrics.snapshot()['execute_vm_command']
        assert snapshot['denied']['default']['calls'] == 1
        assert 'success' not in snapshot
    finally:
        server.close()


def test_unicode_consent_transaction_is_rejected():
    provider = MCPApiKeyOAuthProvider(api_key='fake', issuer_url='https://audit.invalid',
                                      database_url='postgresql://unused')
    assert provider._verify_transaction('pmcpt2.\u4e2d\u6587.fake') is None


@pytest.mark.asyncio
@pytest.mark.parametrize('platform_name, command, expected', [
    ('Windows-11', 'uname -a', ['/bin/sh', '-c', 'uname -a']),
    ('Linux-6', 'echo first && echo second', ['/bin/sh', '-c', 'echo first && echo second']),
])
async def test_vm_command_wire_arguments_are_independent_of_server_os(platform_name, command, expected):
    from urllib.parse import parse_qs
    sent_commands = []
    def send(session, request, **kwargs):
        path = request.path_url
        if path.endswith('/status/current'):
            return response({'status': 'running'})
        if path.endswith('/agent/info'):
            return response({'supported_commands': [{'name': 'guest-exec', 'enabled': True}]})
        if path.endswith('/agent/exec'):
            sent_commands.append(parse_qs(request.body)['command'])
            return response({'pid': 100})
        if '/agent/exec-status' in path:
            return response({'exited': 1, 'exitcode': 0})
        raise AssertionError(path)
    with patch.object(requests.Session, 'send', new=send), \
         patch('proxmoxer.backends.https.platform.platform', return_value=platform_name):
        await VMConsoleManager(real_api()).execute_command('pve1', '100', command)
    assert sent_commands == [expected]
    print(f'{platform_name}: transmitted argv = {expected}')


@pytest.mark.asyncio
async def test_denied_original_tool_cannot_be_retried(tmp_path):
    api = Mock()
    api.nodes.return_value.tasks.return_value.status.get.return_value = {'status': 'stopped', 'exitstatus': 'error'}
    api.nodes.return_value.tasks.return_value.log.get.return_value = []
    api.nodes.return_value.qemu.return_value.delete.return_value = 'UPID:pve1:new-delete'
    with patch('proxmox_mcp.server.load_config', return_value=config(tmp_path, mcp={'tool_denylist': ['delete_vm']})), \
         patch('proxmox_mcp.core.proxmox.ProxmoxAPI', return_value=api):
        server = ProxmoxMCPServer()
    try:
        assert 'delete_vm' not in server.tool_registry.registered_tools
        job = server.job_store.register_task(tool_name='delete_vm', summary='historical failure', node='pve1', upid='old',
            retry_spec={'kind': 'vm.delete', 'params': {'node': 'pve1', 'vmid': '100'}})
        server.job_store.poll_job(job['job_id'])
        from mcp.server.fastmcp.exceptions import ToolError
        with pytest.raises(ToolError, match='disabled'):
            await server.mcp.call_tool('retry_job', {'job_id': job['job_id']})
        api.nodes.return_value.qemu.return_value.delete.assert_not_called()
    finally:
        server.close()


def test_documented_allowlist_rejects_arbitrary_second_shell_command():
    gate = CommandPolicyGate(CommandPolicyConfig(mode='allowlist',
        allow_patterns=[r'^uname(?:\s+-a)?$', r'^df\s+-h$']))
    # Literal strings only; these commands are never executed.
    assert not gate.evaluate('uname -a && touch /root/audit-marker').allowed
    assert not gate.evaluate('df -h ; shutdown -h now').allowed
    assert gate.evaluate('uname -a').allowed
    assert gate.evaluate('df -h').allowed
