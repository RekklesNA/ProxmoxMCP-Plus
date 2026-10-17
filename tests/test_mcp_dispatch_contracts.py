"""Public MCP schemas and target authorization dispatch contracts."""

from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock, patch

import pytest

from proxmox_mcp.config.models import Config, ClientPermissions
from proxmox_mcp.server import ProxmoxMCPServer
from proxmox_mcp.services.builtin_tool_plugins import RegistryPluginBase


@pytest.fixture
def server(tmp_path):
    config = Config.model_validate({'proxmox': {'host': 'pve.invalid'},
        'auth': {'user': 'root@pam', 'token_name': 'audit', 'token_value': 'fake'},
        'ssh': {'user': 'root', 'key_file': 'fake-key'}, 'jobs': {'sqlite_path': str(tmp_path / 'jobs.sqlite')}})
    with patch('proxmox_mcp.server.load_config', return_value=config), patch('proxmox_mcp.core.proxmox.ProxmoxAPI', return_value=Mock()):
        value = ProxmoxMCPServer()
    for name, tool in vars(value.target_toolsets['default']).items():
        replacement = Mock()
        for method in dir(tool):
            if not method.startswith('_') and callable(getattr(tool, method)):
                setattr(replacement, method, Mock(return_value={'success': True, 'source': name + '.' + method}))
        value.target_toolsets['default'].__dict__[name] = replacement
    value.target_toolsets['default'].vm_tools.execute_vm_command = AsyncMock(return_value={'success': True})
    value.proxmox.nodes.get.return_value = [{'node': 'pve'}]
    try:
        yield value
    finally:
        value.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('tool, arguments, service, method', [
    ('reconcile_job', {'job_id': 'job', 'confirmed_not_submitted': True}, 'jobs_tools', 'reconcile_job'),
    ('get_job', {'job_id': 'job', 'refresh': True}, 'jobs_tools', 'get_job'),
    ('cancel_job', {'job_id': 'job'}, 'jobs_tools', 'cancel_job'),
    ('stop_vm', {'node': 'pve', 'vmid': '100'}, 'vm_tools', 'stop_vm'),
    ('shutdown_vm', {'node': 'pve', 'vmid': '100'}, 'vm_tools', 'shutdown_vm'),
    ('reset_vm', {'node': 'pve', 'vmid': '100'}, 'vm_tools', 'reset_vm'),
    ('get_containers', {}, 'container_tools', 'get_containers'),
    ('get_containers', {'payload': {'node': 'pve', 'include_stats': True, 'include_raw': True}}, 'container_tools', 'get_containers'),
    ('start_container', {'selector': '100'}, 'container_tools', 'start_container'),
    ('stop_container', {'selector': '100'}, 'container_tools', 'stop_container'),
    ('restart_container', {'selector': '100'}, 'container_tools', 'restart_container'),
    ('delete_container', {'selector': '100'}, 'container_tools', 'delete_container'),
    ('list_snapshots', {'node': 'pve', 'vmid': '100'}, 'snapshot_tools', 'list_snapshots'),
    ('create_snapshot', {'node': 'pve', 'vmid': '100', 'snapname': 'base'}, 'snapshot_tools', 'create_snapshot'),
    ('delete_snapshot', {'node': 'pve', 'vmid': '100', 'snapname': 'base'}, 'snapshot_tools', 'delete_snapshot'),
    ('list_templates', {}, 'iso_tools', 'list_templates'),
    ('download_iso', {'node': 'pve', 'storage': 'local', 'url': 'https://example.invalid/a.iso', 'filename': 'a.iso'}, 'iso_tools', 'download_iso'),
    ('delete_iso', {'node': 'pve', 'storage': 'local', 'filename': 'a.iso'}, 'iso_tools', 'delete_iso'),
    ('create_backup', {'node': 'pve', 'vmid': '100', 'storage': 'local'}, 'backup_tools', 'create_backup'),
    ('restore_backup', {'node': 'pve', 'vmid': '100', 'archive': 'local:backup/a.tar'}, 'backup_tools', 'restore_backup'),
    ('delete_backup', {'node': 'pve', 'storage': 'local', 'volid': 'local:backup/a.tar'}, 'backup_tools', 'delete_backup'),
    ('get_node_syslog', {'node': 'pve'}, 'log_tools', 'get_node_syslog'),
    ('get_task_log', {'node': 'pve', 'upid': 'UPID:pve:task'}, 'log_tools', 'get_task_log'),
    ('get_cluster_log', {}, 'log_tools', 'get_cluster_log'),
    ('get_node_firewall_log', {'node': 'pve'}, 'log_tools', 'get_node_firewall_log'),
    ('get_guest_firewall_log', {'node': 'pve', 'vmid': '100'}, 'log_tools', 'get_guest_firewall_log'),
])
async def test_public_schema_dispatches_to_the_selected_target(server, tool, arguments, service, method):
    server.job_store.get_job = Mock(return_value={'tool_name': 'create_snapshot'})
    result = await server.mcp.call_tool(tool, arguments)
    assert result
    assert getattr(getattr(server.target_toolsets['default'], service), method).call_count == 1


@pytest.mark.asyncio
async def test_client_scope_limits_discovery_and_original_retry_operation(server):
    server.config.mcp.client_permissions = {'_local': ClientPermissions(tools=['get_vms', 'list_targets', 'retry_job'], targets=['default'])}
    assert await server.mcp.call_tool('get_vms', {})
    with pytest.raises(Exception, match='authorized'):
        await server.mcp.call_tool('delete_vm', {'node': 'pve', 'vmid': '100'})
    server.config.mcp.client_permissions['_local'].targets = []
    assert await server.mcp.call_tool('list_targets', {}) == []
    with pytest.raises(Exception, match='authorized'):
        await server.mcp.call_tool('get_vms', {})
    server.config.mcp.client_permissions['_local'].targets = ['default']
    server.job_store.get_job = Mock(return_value={'tool_name': 'delete_vm'})
    with pytest.raises(Exception, match='authorized'):
        await server.mcp.call_tool('retry_job', {'job_id': 'job'})
    server.target_toolsets['default'].jobs_tools.retry_job.assert_not_called()


@pytest.mark.asyncio
async def test_discovery_failures_and_positional_retry_still_apply_policy(server):
    with patch.object(server.target_registry, 'describe', side_effect=RuntimeError('invalid discovery')):
        with pytest.raises(Exception):
            await server.mcp.call_tool('list_targets', {})
    assert server.metrics.snapshot()['list_targets']['error']['all']['calls'] == 1
    server.job_store.get_job = Mock(return_value={'tool_name': 'delete_vm'})
    wrapper = RegistryPluginBase()._wrap_sync(server, 'retry_job', lambda tools: tools.jobs_tools.retry_job)
    wrapper('job')
    assert server.job_store.get_job.call_args.args == ('job',)
    server.target_registry.resolve = Mock(return_value=SimpleNamespace(name='default', readonly=True))
    asynchronous = RegistryPluginBase()._wrap_async(server, 'execute_vm_command', lambda tools: tools.vm_tools.execute_vm_command)
    with pytest.raises(ValueError, match='read-only'):
        await asynchronous(node='pve', vmid='100', command='uname')
