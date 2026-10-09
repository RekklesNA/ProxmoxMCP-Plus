"""Explicitly enabled, GET-only Proxmox connection-pool integration checks."""

from concurrent.futures import ThreadPoolExecutor
import os

import pytest

from proxmox_mcp.config.loader import load_config
from proxmox_mcp.core.proxmox import ProxmoxManager
from proxmox_mcp.core.targets import TargetRegistry


@pytest.mark.integration
def test_live_independent_sessions_preserve_readonly_api_results():
    config_path = os.getenv("PROXMOX_READONLY_TEST_CONFIG")
    if not config_path:
        pytest.skip("Set PROXMOX_READONLY_TEST_CONFIG for GET-only live verification")
    registry = TargetRegistry(load_config(config_path))
    for target_name in registry.names:
        target = registry.resolve(target_name)
        connection = target.config.model_copy(update={"timeout": 5, "session_pool_size": 1})
        baseline = ProxmoxManager(connection, target.auth, target.api_tunnel, target.ssh)
        try:
            expected_version = baseline.get_api().version.get()
            assert isinstance(expected_version, dict) and expected_version.get("version")
            expected_nodes = {entry["node"] for entry in baseline.get_api().nodes.get()}
        finally:
            baseline.close()
        connection.session_pool_size = 4
        pooled = ProxmoxManager(connection, target.auth, target.api_tunnel, target.ssh)
        try:
            def read(_):
                api = pooled.get_api()
                assert api.version.get() == expected_version
                assert {entry["node"] for entry in api.nodes.get()} == expected_nodes
            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(read, range(8)))
        finally:
            pooled.close()
