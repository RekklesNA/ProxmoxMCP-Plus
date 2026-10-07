"""Executable contracts for authorization, caching and operational boundaries."""

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from proxmox_mcp.config.loader import _apply_mcp_env_overrides, _parse_tool_filter_env, load_config
from proxmox_mcp.config.models import Config, MCPConfig, LoggingConfig, CommandPolicyConfig
from proxmox_mcp.core.logging import setup_logging
from proxmox_mcp.core.targets import TargetRegistry
from proxmox_mcp.formatting.templates import ProxmoxTemplates
from proxmox_mcp.models.tooling import ToolResult, result_status
from proxmox_mcp.observability.metrics import ToolMetrics, HttpRequestMetrics, LabeledMetricSeries
from proxmox_mcp.security.access import authorize_client, client_principal, permitted_targets
from proxmox_mcp.security.command_policy import CommandPolicyGate
from proxmox_mcp.security.sanitization import sanitize_value
from proxmox_mcp.services.tool_registry import _async_dispatch, ToolRegistry, ToolExposurePolicy
from proxmox_mcp.tools.base import ProxmoxTool
from proxmox_mcp.tools.guest_config import parse_device


LEGACY = {"proxmox": {"host": "pve.invalid"}, "auth": {"user": "root@pam", "token_name": "audit", "token_value": "fake"}}


@pytest.mark.parametrize("result, expected", [
    (ToolResult(success=False, code="CMD_POLICY_NOT_ALLOWLISTED", message="Denied"), "denied"),
    ({"success": False, "code": "INCOMPLETE_INVENTORY"}, "partial"),
    ({"ok": False}, "error"), ({"status": "submitted"}, "submitted"),
    ([{"ok": True}, {"ok": False}], "partial"), ([{"ok": False}], "error"),
    ([{"status": "submitted"}], "submitted"), (None, "success"),
])
def test_outcome_categories(result, expected):
    assert result_status(result) == expected


def test_metrics_report_status_and_escape_labels():
    tools = ToolMetrics()
    tools.observe('a"b', 12, False, target='t\\x', outcome='denied')
    tools.observe('a"b', 8, False, target='t\\x', outcome='denied')
    assert tools.snapshot()['a"b']['denied']['t\\x']['latency_ms_avg'] == 10
    assert 'status="denied"' in tools.render_prometheus()
    assert 'a\\"b' in tools.render_prometheus()
    http = HttpRequestMetrics()
    http.observe('', 'UNTRUSTED', 401, 3)
    assert http.snapshot()['requests'][0]['method'] == 'OTHER'
    assert 'method="OTHER"' in http.render_prometheus()
    assert LabeledMetricSeries().latency_ms_avg == 0


def test_client_permissions_fail_closed_and_keep_legacy_defaults():
    authorize_client({}, 'unknown', 'delete_vm', 'default')
    policies = {'reader': {'tools': ['get_vms'], 'targets': ['lab']},
                'admin': SimpleNamespace(tools=['*'], targets=['*'])}
    authorize_client(policies, 'reader', 'get_vms', 'lab')
    authorize_client(policies, 'admin', 'delete_vm', 'production')
    for principal, tool, target in [('unknown', 'get_vms', 'lab'), ('reader', 'delete_vm', 'lab'), ('reader', 'get_vms', 'production')]:
        with pytest.raises(PermissionError):
            authorize_client(policies, principal, tool, target)
    assert permitted_targets(policies, 'reader') == {'lab'}
    assert permitted_targets(policies, 'unknown') == set()
    assert permitted_targets(policies, 'admin') is None
    assert permitted_targets({}, 'unknown') is None
    with patch('proxmox_mcp.security.access.get_access_token', return_value=None):
        assert client_principal('STDIO') == '_local'
        assert client_principal('STREAMABLE') == '_shared_key'
    with patch('proxmox_mcp.security.access.get_access_token', return_value=SimpleNamespace(client_id='reader')):
        assert client_principal('STREAMABLE') == 'reader'


@pytest.mark.asyncio
async def test_dispatch_checks_arguments_and_handles_extensions():
    calls = []
    def extension(node: str, **kwargs):
        calls.append(node)
        return kwargs
    authorize = Mock()
    dispatch = _async_dispatch(extension, authorize, 'extension_alias')
    assert await dispatch(node='pve', approval_token='fake', value=1) == {'value': 1}
    authorize.assert_called_once_with('extension_alias', {'node': 'pve', 'kwargs': {'value': 1}})
    with pytest.raises(ValueError):
        await dispatch(node='../pve')
    assert calls == ['pve']
    async def asynchronous(node: str):
        return node
    assert await _async_dispatch(asynchronous)(node='pve') == 'pve'


def test_registry_requires_binding_and_reports_capability_gaps():
    registry = ToolRegistry(exposure_policy=ToolExposurePolicy(known_tools=['feature'], allowlist=['feature']))
    assert registry.requested_but_unavailable == {'feature'}
    with pytest.raises(RuntimeError):
        registry.tool(name='feature')(lambda: 1)
    registry._authorize('feature', {})


@pytest.mark.asyncio
async def test_dispatch_limit_is_bounded_and_records_queue_time():
    registry = ToolRegistry()
    server = SimpleNamespace(config=SimpleNamespace(mcp=MCPConfig(worker_limit=1)),
        target_registry=SimpleNamespace(resolve=lambda target: SimpleNamespace(name='default')), metrics=ToolMetrics())
    registry._server = server
    active = 0
    maximum = 0
    async def operation():
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(.01)
        active -= 1
        return 'done'
    dispatch = _async_dispatch(operation, acquire=registry._acquire)
    assert await asyncio.gather(*[dispatch() for _ in range(4)]) == ['done'] * 4
    assert maximum == 1
    assert server.metrics.snapshot()['dispatch_queue']['success']['default']['calls'] == 4
    async with ToolRegistry()._acquire('operation', {}):
        pass


def test_cache_coalesces_concurrent_reads_and_expires_without_wall_clock():
    tool = ProxmoxTool(Mock())
    read = Mock(return_value={'value': 7})
    with ThreadPoolExecutor(max_workers=8) as workers:
        values = list(workers.map(lambda _: tool._cached_read('key', read), range(32)))
    assert values == [{'value': 7}] * 32
    assert read.call_count == 1
    with patch('proxmox_mcp.tools.base.time.monotonic', return_value=10**20):
        assert tool._cache_get('key') is None
    for index in range(510):
        tool._cache_set(str(index), index)
    assert len(tool._cache) == 500


@pytest.mark.parametrize('text', ['broken', 'bridge=x,bridge=y', '=empty'])
def test_device_merge_rejects_ambiguous_configuration(text):
    with pytest.raises(ValueError):
        parse_device(text)


def test_sanitizer_recurses_sequence_types():
    assert sanitize_value(['password=fake-secret', ('token=fake-token',)]) == ['password=[REDACTED]', ('token=[REDACTED]',)]


def test_base_formatting_and_errors():
    tool = ProxmoxTool(Mock())
    assert 'UNKNOWN' in tool._format_response({}, 'node_status')[0].text
    assert 'No containers' in tool._format_response([], 'containers')[0].text
    with pytest.raises(ValueError, match='Invalid input'):
        tool._handle_error('test', RuntimeError('invalid parameter'))
    assert ProxmoxTool(Mock(), job_store=Mock())._register_background_job(tool_name='test', summary='test', node='pve', upid=None) is None


def test_templates_preserve_unknown_capacity_and_container_contract():
    assert 'Unknown' in ProxmoxTemplates.storage_list([{'storage': 'local', 'type': 'dir', 'used': None, 'total': None}])
    assert '100' in ProxmoxTemplates.container_list([{'vmid': 100, 'name': 'ct', 'status': 'running', 'node': 'pve', 'memory': {'used': 10, 'total': 20}}])
    assert 'Proxmox Nodes' in ProxmoxTemplates.node_list([])


def test_logging_reopens_owned_handlers_and_falls_back_on_file_errors(tmp_path):
    root = logging.getLogger()
    original = root.handlers[:]
    level = root.level
    try:
        path = tmp_path / 'new' / 'logs' / 'app.log'
        setup_logging(LoggingConfig(file=str(path)))
        assert path.is_file()
        setup_logging(LoggingConfig(file='relative.log'))
        with patch('proxmox_mcp.core.logging.logging.FileHandler', side_effect=OSError('read-only')):
            setup_logging(LoggingConfig(file=str(path)))
        assert any(getattr(handler, '_proxmox_mcp_handler', False) for handler in root.handlers)
    finally:
        for handler in list(root.handlers):
            if handler not in original:
                root.removeHandler(handler)
                handler.close()
        root.handlers[:] = original
        root.setLevel(level)


def test_file_configuration_and_deployment_overrides(tmp_path, monkeypatch):
    monkeypatch.delenv('PROXMOX_HOST', raising=False)
    monkeypatch.setenv('MCP_ALLOW_UNAUTHENTICATED_HTTP', 'true')
    monkeypatch.setenv('MCP_CODE_MODE', 'true')
    monkeypatch.setenv('PROXMOX_JOBS_SQLITE_PATH', str(tmp_path / 'persistent.sqlite'))
    data = json.loads(json.dumps(LEGACY))
    _apply_mcp_env_overrides(data)
    assert data['jobs']['sqlite_path'].endswith('persistent.sqlite')
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(LEGACY), encoding='utf-8')
    assert load_config(str(path)).mcp.code_mode is True
    for invalid in ['{broken', '[]', '{}', '{"proxmox":{"host":"pve"}}', '{"targets": {}}', '{"targets":{"a":{}}}', '{"targets":{"a":{"host":"pve"}}}']:
        path.write_text(invalid, encoding='utf-8')
        with pytest.raises(ValueError):
            load_config(str(path))
    monkeypatch.delenv('UNSET_FILTER', raising=False)
    assert _parse_tool_filter_env('UNSET_FILTER') is None


def test_target_configuration_validation_and_safe_discovery():
    for data in [dict(LEGACY, targets={'lab': dict(host='pve', auth=LEGACY['auth'])}),
                 {'targets': {}, 'ssh': {}}, {'targets': {'lab': dict(host='pve', auth=LEGACY['auth'])}, 'api_tunnel': {'enabled': False}}]:
        with pytest.raises(ValidationError):
            Config.model_validate(data)
    assert MCPConfig(transport=None).transport == 'STDIO'
    assert MCPConfig.normalize_transport(2) == 2
    assert MCPConfig.normalize_tool_filter(None) is None
    registry = TargetRegistry(Config.model_validate(LEGACY))
    assert registry.describe(allowed_names=set()) == []
    assert registry.describe(allowed_names={'default'})[0]['host'] == 'pve.invalid'
    for config in [SimpleNamespace(targets={}, proxmox=None, auth=None), SimpleNamespace(targets=None, proxmox=None, auth=None),
                   SimpleNamespace(targets={}, proxmox=object(), auth=None)]:
        with pytest.raises(ValueError):
            TargetRegistry(config)
    with pytest.raises(ValueError):
        TargetRegistry._from_named(' ', Mock())


def test_empty_and_unconfigured_operation_policy():
    policy = CommandPolicyGate(CommandPolicyConfig(high_risk_mode='disabled'))
    assert policy.evaluate(' ').code == 'CMD_POLICY_EMPTY'
    assert policy.evaluate_operation('').code == 'OP_POLICY_EMPTY'
    assert policy.evaluate_operation('delete_vm').code == 'OP_POLICY_DISABLED'
    enforced = CommandPolicyGate(CommandPolicyConfig(high_risk_mode='enforce', high_risk_require_approval_token=True))
    assert enforced.evaluate_operation('delete_vm').code == 'OP_POLICY_APPROVAL_NOT_CONFIGURED'
