"""Startup rollback, connection ownership and transport shutdown contracts."""

import io
import runpy
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock, patch

import pytest

import proxmox_mcp
from proxmox_mcp import docker_entrypoint
from proxmox_mcp.config.models import AuthConfig, ProxmoxConfig, MCPConfig, Config
from proxmox_mcp.core.proxmox import ProxmoxManager
from proxmox_mcp.core.ssh_tunnel import SSHTunnelManager
from proxmox_mcp.server import ProxmoxMCPServer
import proxmox_mcp.server as server_module


AUTH = AuthConfig(user='root@pam', token_name='audit', token_value='fake')


def bare_server():
    server = ProxmoxMCPServer.__new__(ProxmoxMCPServer)
    server.logger = Mock()
    server.target_job_stores = {}
    server.proxmox_managers = {}
    server.code_mode = None
    server.config = SimpleNamespace(mcp=MCPConfig())
    server.mcp = Mock()
    server.oauth_provider = None
    return server


def test_package_lazy_import_and_docker_exec_entrypoint():
    assert proxmox_mcp.__getattr__('ProxmoxMCPServer') is ProxmoxMCPServer
    with pytest.raises(AttributeError):
        proxmox_mcp.__getattr__('unknown')
    with patch('proxmox_mcp.docker_entrypoint.os.execvp') as execute:
        docker_entrypoint.main()
        assert execute.call_args.args[0] == execute.call_args.args[1][0]
        runpy.run_path(docker_entrypoint.__file__, run_name='__main__')
        assert execute.call_count == 2


def test_api_initialization_failure_and_synchronized_request_ownership():
    with patch('proxmox_mcp.core.proxmox.ProxmoxAPI', side_effect=RuntimeError('invalid setup')):
        with pytest.raises(RuntimeError):
            ProxmoxManager(ProxmoxConfig(host='pve.invalid'), AUTH)
    tunnel = Mock()
    tunnel.ensure_tunnel.side_effect = RuntimeError('unavailable')
    with patch('proxmox_mcp.core.proxmox.SSHTunnelManager', return_value=tunnel):
        with pytest.raises(RuntimeError):
            ProxmoxManager(ProxmoxConfig(host='pve.invalid'), AUTH, api_tunnel_config=SimpleNamespace(enabled=False))
    tunnel.close.assert_called_once()
    session = Mock()
    session.request.return_value = 'response'
    api = SimpleNamespace(_store={'session': session})
    with patch('proxmox_mcp.core.proxmox.ProxmoxAPI', return_value=api):
        manager = ProxmoxManager(ProxmoxConfig(host='pve.invalid'), AUTH)
    manager.tunnel_manager = Mock()
    assert session.request('GET', '/version') == 'response'
    manager.tunnel_manager.ensure_tunnel.assert_called_once()
    manager.close()
    session.close.assert_called_once()


def tunnel_config():
    return SimpleNamespace(enabled=True, assume_external=False, local_host='127.0.0.1', local_port=65530,
        remote_host='pve', remote_port=8006, ssh_host='ssh.invalid', connect_timeout=1)


def test_tunnel_probe_reconnect_backoff_and_owned_listener():
    tunnel = SSHTunnelManager(tunnel_config())
    with patch('proxmox_mcp.core.ssh_tunnel.socket.create_connection', side_effect=OSError()):
        assert tunnel._is_local_endpoint_reachable() is False
    connection = Mock()
    connection.__enter__ = Mock(return_value=connection)
    connection.__exit__ = Mock(return_value=False)
    with patch('proxmox_mcp.core.ssh_tunnel.socket.create_connection', return_value=connection):
        assert tunnel._is_local_endpoint_reachable() is True
    process = Mock()
    process.poll.return_value = None
    tunnel._process = process
    tunnel._is_local_endpoint_reachable = Mock(return_value=True)
    tunnel.ensure_tunnel()
    process.terminate.assert_not_called()
    tunnel._is_local_endpoint_reachable.return_value = False
    tunnel._start_process = Mock(side_effect=OSError('unavailable'))
    with pytest.raises(OSError):
        tunnel.ensure_tunnel()
    process.terminate.assert_called_once()
    with pytest.raises(RuntimeError, match='backing off'):
        tunnel.ensure_tunnel()
    tunnel.close()


@pytest.mark.parametrize('stream', [None, io.StringIO('x' * 10000)])
def test_tunnel_stderr_drain_is_bounded_and_reaped(stream):
    tunnel = SSHTunnelManager(tunnel_config())
    process = Mock(stderr=stream)
    process.poll.return_value = 1
    with patch('proxmox_mcp.core.ssh_tunnel.subprocess.Popen', return_value=process):
        tunnel._start_process()
    tunnel._stderr_thread.join(timeout=2)
    assert len(tunnel._stderr_tail) <= 4096
    with pytest.raises(RuntimeError):
        tunnel._wait_for_local_listener()
    tunnel.close()
    assert tunnel._stderr_thread is None


def test_server_close_attempts_every_owned_resource_even_after_errors():
    server = bare_server()
    server.job_store = Mock()
    server.job_store.close.side_effect = RuntimeError('failure')
    other = Mock()
    other.close.side_effect = RuntimeError('failure')
    manager = Mock()
    manager.close.side_effect = RuntimeError('failure')
    server.target_job_stores = {'default': server.job_store, 'other': other}
    server.proxmox_managers = {'default': manager}
    server.close()
    other.close.assert_called_once()
    manager.close.assert_called_once()
    with pytest.raises(AttributeError):
        getattr(server, 'unknown')


@pytest.mark.asyncio
async def test_native_oauth_http_uses_provider_lifespan_and_sse_is_rejected():
    server = bare_server()
    provider = Mock(issuer_url='https://pve.invalid')
    server.oauth_provider = provider
    with pytest.raises(ValueError):
        await server._run_streamable_http_async(sse=True)
    with patch('uvicorn.Config'), patch('uvicorn.Server', return_value=SimpleNamespace(serve=AsyncMock())):
        await server._run_streamable_http_async()
    provider.bind_http_lifespan.assert_called_once()
    server._run_streamable_http_async = AsyncMock()
    await server._run_sse_http_async()
    server._run_streamable_http_async.assert_awaited_once_with(sse=True)


@pytest.mark.parametrize('failure, code', [(KeyboardInterrupt(), 0), (RuntimeError('failed initialization'), 1)])
def test_cli_reports_initialization_failure_and_interrupt(failure, code):
    with patch('proxmox_mcp.server.ProxmoxMCPServer', side_effect=failure):
        with pytest.raises(SystemExit) as error:
            server_module.main()
    assert error.value.code == code


def test_server_run_failure_closes_resources_and_invalid_legacy_transport_falls_back():
    server = bare_server()
    server.config.mcp = SimpleNamespace(transport='unknown')
    with patch('proxmox_mcp.server.signal.signal'), patch('anyio.run', side_effect=RuntimeError('failed transport')):
        with pytest.raises(SystemExit) as error:
            server.start()
    assert error.value.code == 1


def test_partial_server_initialization_closes_already_created_managers():
    config = Config.model_validate({'targets': {name: {'host': 'pve.invalid', 'auth': AUTH.model_dump()} for name in ['first', 'second']}})
    first = Mock()
    with patch('proxmox_mcp.server.load_config', return_value=config), patch('proxmox_mcp.server.setup_logging', return_value=Mock()), \
         patch('proxmox_mcp.server.ProxmoxManager', side_effect=[first, RuntimeError('second failed')]):
        with pytest.raises(RuntimeError):
            ProxmoxMCPServer()
    first.close.assert_called_once()


def test_oauth_routes_registration_and_sse_startup_rejection(tmp_path, monkeypatch):
    data = {'proxmox': {'host': 'pve.invalid'}, 'auth': AUTH.model_dump(),
        'jobs': {'sqlite_path': str(tmp_path / 'jobs.sqlite')},
        'mcp': {'transport': 'STREAMABLE', 'allowed_hosts': ['pve.invalid']}}
    config = Config.model_validate(data)
    provider = Mock()
    with patch('proxmox_mcp.server.load_config', return_value=config), patch('proxmox_mcp.server.ProxmoxManager'), \
         patch('proxmox_mcp.server.FastMCP'), patch('proxmox_mcp.server.build_oauth_from_env', return_value=(provider, None)):
        value = ProxmoxMCPServer()
        try:
            provider.register_routes.assert_called_once_with(value.mcp)
            assert value._build_transport_security().enable_dns_rebinding_protection is True
        finally:
            value.close()
    config.mcp.transport = 'SSE'
    monkeypatch.setenv('MCP_OAUTH_ENABLED', 'true')
    with patch('proxmox_mcp.server.load_config', return_value=config), patch('proxmox_mcp.server.ProxmoxManager'):
        with pytest.raises(ValueError, match='STREAMABLE'):
            ProxmoxMCPServer()
