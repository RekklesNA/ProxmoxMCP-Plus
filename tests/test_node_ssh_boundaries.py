"""Exercise node SSH safety through the actual MCP dispatcher."""
import json
from unittest.mock import patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from proxmox_mcp.server import ProxmoxMCPServer


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['readonly', 'high_risk_approval', 'bad_approval', 'client_denied', 'target_opt_out', 'allowed'])
async def test_real_mcp_host_command_boundary(tmp_path, case):
    policy = {'mode': 'allowlist', 'allow_patterns': ['^id$'], 'high_risk_mode': 'audit_only'}
    if case == 'high_risk_approval':
        policy.update(high_risk_mode='enforce', high_risk_require_approval_token=True, high_risk_approval_token='expected')
    if case == 'bad_approval':
        policy.update(require_approval_token=True, approval_token='expected')
    target = {'host': 'host.example', 'auth': {'user': 'user', 'token_name': 'token', 'token_value': 'value'}, 'readonly': case == 'readonly', 'ssh': {'user': 'test-user', 'allow_node_commands': True}, 'command_policy': policy}
    config = {'targets': {'a': target}, 'mcp': {'transport': 'STDIO'}, 'jobs': {'sqlite_path': str(tmp_path / 'jobs.sqlite3')}}
    if case == 'client_denied':
        config['mcp']['client_permissions'] = {'_local': {'tools': ['get_nodes'], 'targets': ['a']}}
    if case == 'target_opt_out':
        config['targets']['b'] = dict(target, ssh={'user': 'test-user', 'allow_node_commands': False})
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config), encoding='utf-8')
    with patch('proxmox_mcp.core.proxmox.ProxmoxAPI') as api:
        api.return_value.nodes.get.return_value = [{'node': 'pve1'}]
        server = ProxmoxMCPServer(str(path))
    try:
        selected = 'b' if case == 'target_opt_out' else 'a'
        manager = server.target_toolsets[selected].container_tools.console_manager
        with patch.object(manager, '_run_ssh', return_value={'success': True, 'exit_code': 0}) as ssh:
            arguments = {'node': 'pve1', 'command': 'id', 'target': selected}
            if case == 'bad_approval':
                arguments['approval_token'] = '\u4e0d\u5339\u914d'
            if case == 'allowed':
                result = await server.mcp.call_tool('execute_node_command', arguments)
                assert 'true' in str(result)
                ssh.assert_called_once()
            elif case == 'bad_approval':
                result = await server.mcp.call_tool('execute_node_command', arguments)
                assert 'CMD_POLICY_APPROVAL_REQUIRED' in str(result)
                ssh.assert_not_called()
            else:
                with pytest.raises(ToolError):
                    await server.mcp.call_tool('execute_node_command', arguments)
                ssh.assert_not_called()
    finally:
        server.close()
