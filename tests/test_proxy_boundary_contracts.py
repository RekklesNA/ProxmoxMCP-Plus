"""Proxy authorization, readiness and startup rollback contracts."""

import base64
import json
import runpy
from collections import deque
from unittest.mock import Mock, AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from proxmox_mcp import openapi_proxy as proxy
from proxmox_mcp.config.models import CommandPolicyConfig
from proxmox_mcp.security.command_policy import CommandPolicyGate


def app(**options):
    return proxy.create_app(['unused'], api_key=None, strict_auth=False, cors_allow_origins=['https://app.invalid'], **options)


def test_proxy_authentication_and_cors_defaults():
    assert proxy._parse_cors_allow_origins(None) == ['*']
    assert proxy._verify_authorization_header('Bearer', 'fake').status_code == 401
    basic = base64.b64encode(b'user:wrong').decode()
    assert proxy._verify_authorization_header('Basic ' + basic, 'fake').status_code == 403
    assert proxy._verify_authorization_header('Unsupported fake', 'fake').status_code == 401


@pytest.mark.parametrize('options', [
    {'job_store': Mock(), 'job_stores': {'default': Mock()}},
    {'job_stores': {'a': Mock(), 'b': Mock()}, 'command_policy': Mock()},
    {'job_store': Mock(), 'command_policy': Mock(), 'command_policies': {'default': Mock()}},
    {'target_readonly': {'unknown': True}},
])
def test_proxy_rejects_conflicting_target_context(options):
    with pytest.raises(ValueError):
        app(**options)


def test_proxy_readiness_and_missing_job_service_are_explicit():
    value = app()
    client = TestClient(value)
    try:
        assert client.get('/readyz').status_code == 503
        value.state.is_connected = True
        assert client.get('/readyz').status_code == 200
        assert client.get('/livez').status_code == 200
        assert client.get('/jobs').status_code == 503
        assert client.post('/jobs/unknown/poll').status_code == 503
    finally:
        client.close()


def test_proxy_client_scope_and_current_tool_filter_are_both_enforced():
    store = Mock()
    store.get_job.return_value = {'tool_name': 'delete_vm'}
    value = proxy.create_app(['unused'], api_key='fake', strict_auth=True, cors_allow_origins=[], job_store=store,
        client_permissions={'_api_key': {'tools': ['retry_job'], 'targets': ['default']}})
    client = TestClient(value, headers={'Authorization': 'Bearer fake'})
    try:
        assert client.post('/jobs/job/retry', headers={'X-Approval-Token': 'approval'}).status_code == 403
        store.retry_job.assert_not_called()
    finally:
        client.close()


def test_proxy_retry_audit_policy_and_resource_cleanup():
    store = Mock()
    store.get_job.return_value = {'tool_name': 'delete_vm'}
    store.retry_job.return_value = {'status': 'running'}
    policy = CommandPolicyGate(CommandPolicyConfig(high_risk_mode='audit_only'))
    client = TestClient(app(job_store=store, command_policy=policy))
    try:
        assert client.post('/jobs/job/retry').status_code == 202
    finally:
        client.close()
    store.close.side_effect = RuntimeError('failure')
    manager = Mock()
    manager.close.side_effect = RuntimeError('failure')
    proxy._close_job_resources({'default': store}, [manager])
    manager.close.assert_called_once()


@pytest.mark.asyncio
async def test_rate_limiter_expires_buckets_and_sweeps_without_client_identity():
    request = Request({'type': 'http', 'headers': [], 'client': None})
    call = AsyncMock(return_value='response')
    limiter = proxy.RateLimitMiddleware(Mock(), requests_per_minute=0)
    assert await limiter.dispatch(request, call) == 'response'
    limiter.requests_per_minute = 10
    limiter._requests_seen = 255
    limiter._buckets = {'unknown': deque([0]), 'stale': deque([0])}
    assert await limiter.dispatch(request, call) == 'response'
    assert 'stale' not in limiter._buckets


@pytest.mark.parametrize('named', [False, True])
def test_proxy_partial_initialization_closes_managers(monkeypatch, tmp_path, named):
    auth = {'user': 'root@pam', 'token_name': 'audit', 'token_value': 'fake'}
    data = {'targets': {'lab': {'host': 'pve.invalid', 'auth': auth}}} if named else {'proxmox': {'host': 'pve.invalid'}, 'auth': auth}
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setenv('PROXMOX_MCP_CONFIG', str(path))
    monkeypatch.setenv('PROXMOX_API_KEY', 'fake')
    monkeypatch.setattr('sys.argv', ['proxy', '--', 'unused'])
    manager = Mock()
    with patch('proxmox_mcp.core.proxmox.ProxmoxManager', return_value=manager), \
         patch('proxmox_mcp.services.JobStore', side_effect=RuntimeError('database failure')), patch('proxmox_mcp.openapi_proxy.uvicorn.run'):
        if named:
            with pytest.raises(RuntimeError):
                proxy.main()
        else:
            proxy.main()
    assert manager.close.called


def test_proxy_cli_requires_a_command_and_module_entrypoint_runs(monkeypatch):
    monkeypatch.setattr('sys.argv', ['proxy'])
    with pytest.raises(SystemExit) as error:
        proxy.main()
    assert error.value.code == 2
    monkeypatch.setattr('sys.argv', ['proxy', '--', 'unused'])
    monkeypatch.delenv('PROXMOX_MCP_CONFIG', raising=False)
    monkeypatch.setenv('PROXMOX_API_KEY', 'fake')
    with patch('uvicorn.run') as run:
        runpy.run_path(proxy.__file__, run_name='__main__')
    run.assert_called_once()
