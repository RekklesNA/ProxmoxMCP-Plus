"""Regression for confused-deputy bypass (target param ignored / stale ContextVar).

Two targets:
  - permissive: writable, audit_only, disabled high-risk
  - restricted: readonly + deny_all + high_risk enforce requiring token

Assert that priming with permissive does not allow restricted to bypass
readonly/high-risk, and that explicit target works on fresh context.
"""

import json
import pytest
from unittest.mock import patch, Mock
from mcp.server.fastmcp.exceptions import ToolError

from proxmox_mcp.server import ProxmoxMCPServer


def _two_target_config(path, *, restricted_readonly: bool = True):
    """Write config with permissive + restricted targets."""
    path.write_text(
        json.dumps(
            {
                "targets": {
                    "permissive": {
                        "host": "permissive.example",
                        "port": 8006,
                        "readonly": False,
                        "auth": {
                            "user": "u@pve",
                            "token_name": "t",
                            "token_value": "v",
                        },
                        "command_policy": {
                            "mode": "audit_only",
                            "high_risk_mode": "disabled",
                        },
                    },
                    "restricted": {
                        "host": "restricted.example",
                        "port": 8006,
                        "readonly": restricted_readonly,
                        "auth": {
                            "user": "u@pve",
                            "token_name": "t2",
                            "token_value": "v2",
                        },
                        "command_policy": {
                            "mode": "deny_all",
                            "high_risk_mode": "enforce",
                            "high_risk_require_approval_token": True,
                            "high_risk_approval_token": "secret-token",
                        },
                    },
                },
                "jobs": {"sqlite_path": str(path.with_suffix(".sqlite3"))},
            }
        )
    )


def _mock_api():
    """Patch ProxmoxAPI to a mock that pretends VM ops succeed."""
    patcher = patch("proxmox_mcp.core.proxmox.ProxmoxAPI")
    mock_cls = patcher.start()
    api = Mock()
    # get_nodes path
    api.nodes.get.return_value = [{"node": "pve1", "status": "online"}]
    api.nodes.return_value.status.get.return_value = {
        "status": "online",
        "uptime": 0,
        "cpuinfo": {"cpus": 4},
        "memory": {"used": 0, "total": 0},
    }
    # vm create path
    api.nodes.return_value.qemu.create.return_value = "UPID:create"
    api.nodes.return_value.qemu.return_value.status.start.post.return_value = "UPID:start"
    api.nodes.return_value.qemu.return_value.delete.return_value = "UPID:delete"
    api.nodes.return_value.qemu.return_value.status.current.get.return_value = {
        "status": "stopped"
    }
    # allow any chain
    mock_cls.return_value = api
    return patcher, api


@pytest.mark.asyncio
async def test_restricted_still_blocked_after_permissive_prime(tmp_path):
    config_path = tmp_path / "confused.json"
    _two_target_config(config_path, restricted_readonly=True)
    patcher, api = _mock_api()
    server = ProxmoxMCPServer(str(config_path))
    try:
        # Prime with permissive target (simulates stale ContextVar if bug existed)
        resp = await server.mcp.call_tool("get_nodes", {"target": "permissive"})
        assert resp  # success

        # Restricted readonly must still block mutation even after prime
        with pytest.raises(ToolError, match="read-only"):
            await server.mcp.call_tool(
                "create_vm",
                {
                    "target": "restricted",
                    "node": "pve1",
                    "vmid": "200",
                    "name": "test",
                    "cpus": 1,
                    "memory": 512,
                    "disk_size": 8,
                },
            )

        # High-risk without token must still be blocked (readonly also blocks,
        # but we also check high-risk path separately with non-readonly restricted)
        # For readonly restricted, delete_vm is also blocked by readonly:
        with pytest.raises(ToolError, match="read-only|approval token|High-risk"):
            await server.mcp.call_tool(
                "delete_vm",
                {"target": "restricted", "node": "pve1", "vmid": "100"},
            )

        # Even with token, readonly still blocks (high-risk token cannot bypass readonly)
        with pytest.raises(ToolError, match="read-only"):
            await server.mcp.call_tool(
                "delete_vm",
                {
                    "target": "restricted",
                    "node": "pve1",
                    "vmid": "100",
                    "approval_token": "secret-token",
                },
            )

        # The permissive read-only prime succeeded above; restricted calls did
        # not reach the restricted API because the wrapper rejected them first.
    finally:
        server.close()
        patcher.stop()


@pytest.mark.asyncio
async def test_high_risk_enforce_blocks_without_token_after_permissive_prime(tmp_path):
    # Separate test where restricted is NOT readonly, to prove high-risk gate uses same target
    config_path = tmp_path / "confused2.json"
    _two_target_config(config_path, restricted_readonly=False)
    patcher, api = _mock_api()
    server = ProxmoxMCPServer(str(config_path))
    try:
        # Prime with permissive
        await server.mcp.call_tool("get_nodes", {"target": "permissive"})

        # High-risk without token on restricted must fail
        with pytest.raises(ToolError, match="approval token|High-risk"):
            await server.mcp.call_tool(
                "delete_vm",
                {"target": "restricted", "node": "pve1", "vmid": "100"},
            )

        # With correct token, it should proceed (mock returns UPID)
        resp = await server.mcp.call_tool(
            "delete_vm",
            {
                "target": "restricted",
                "node": "pve1",
                "vmid": "100",
                "approval_token": "secret-token",
            },
        )
        assert resp

        # Wrong token still blocked even after successful permissive call
        with pytest.raises(ToolError, match="approval token|High-risk"):
            await server.mcp.call_tool(
                "delete_vm",
                {
                    "target": "restricted",
                    "node": "pve1",
                    "vmid": "100",
                    "approval_token": "wrong",
                },
            )
    finally:
        server.close()
        patcher.stop()


@pytest.mark.asyncio
async def test_explicit_target_works_on_fresh_context(tmp_path):
    """Fresh server: first call with explicit target must respect that target."""
    config_path = tmp_path / "fresh.json"
    _two_target_config(config_path, restricted_readonly=True)
    patcher, api = _mock_api()
    server = ProxmoxMCPServer(str(config_path))
    try:
        # No priming – first call is restricted mutation, must be blocked
        with pytest.raises(ToolError, match="read-only"):
            await server.mcp.call_tool(
                "start_vm",
                {"target": "restricted", "node": "pve1", "vmid": "100"},
            )

        # Fresh context, permissive mutation should succeed
        resp = await server.mcp.call_tool(
            "start_vm",
            {"target": "permissive", "node": "pve1", "vmid": "100"},
        )
        assert resp

        # Fresh context, high-risk on non-readonly restricted without token must fail
        server.close()
        patcher.stop()
        # Re-create with non-readonly for this sub-check
        config_path2 = tmp_path / "fresh2.json"
        _two_target_config(config_path2, restricted_readonly=False)
        patcher2, api2 = _mock_api()
        server2 = ProxmoxMCPServer(str(config_path2))
        try:
            with pytest.raises(ToolError, match="approval token|High-risk"):
                await server2.mcp.call_tool(
                    "delete_vm",
                    {"target": "restricted", "node": "pve1", "vmid": "100"},
                )
        finally:
            server2.close()
            patcher2.stop()
    finally:
        try:
            server.close()
        except Exception:
            pass
        try:
            patcher.stop()
        except Exception:
            pass
