"""Exercise actual Compose interpolation, profile isolation and host bindings."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def compose(tmp_path):
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker CLI is needed for Compose configuration regression checks")
    version = subprocess.run([docker, "compose", "version"], capture_output=True, timeout=30)
    if version.returncode:
        pytest.skip("Docker Compose plugin is unavailable")
    empty = tmp_path / "empty.env"
    empty.write_text("", encoding="utf-8")
    clean = {key: value for key, value in os.environ.items()
             if not key.upper().startswith(("PROXMOX_", "MCP_", "COMPOSE_", "OPENAPI_"))}

    def render(profiles=(), **variables):
        command = [docker, "compose", "--env-file", str(empty), "-f", str(ROOT / "docker-compose.yml")]
        for profile in profiles:
            command.extend(["--profile", profile])
        result = subprocess.run(command + ["config", "--format", "json"],
                                env={**clean, **variables}, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout).get("services", {})

    return render


def test_no_mode_or_secret_is_required_to_inspect_an_idle_project(compose):
    assert compose() == {}


@pytest.mark.parametrize("profile,service,key", [
    ("mcp-http", "proxmox-mcp-http", "MCP_API_KEY"),
    ("openapi", "proxmox-mcp-api", "PROXMOX_API_KEY"),
])
@pytest.mark.parametrize("configured", [False, True])
def test_selected_mode_does_not_require_the_other_modes_secret(compose, profile, service, key, configured):
    services = compose([profile], **({key: "compose-fixture-key"} if configured else {}))
    assert set(services) == {service}
    assert services[service]["environment"][key] == ("compose-fixture-key" if configured else "")
    # Empty secrets may be rendered: application startup is responsible for rejection.
    assert services[service]["environment"]["PROXMOX_MCP_MODE"] == profile


@pytest.mark.parametrize("address", [None, "192.0.2.10", "0.0.0.0"])
def test_bindings_are_loopback_by_default_and_widen_only_explicitly(compose, address):
    overrides = {} if address is None else {"OPENAPI_BIND_ADDRESS": address, "MCP_HTTP_BIND_ADDRESS": address}
    services = compose(["openapi", "mcp-http"], **overrides)
    assert set(services) == {"proxmox-mcp-api", "proxmox-mcp-http"}
    for service, port in [("proxmox-mcp-api", 8811), ("proxmox-mcp-http", 8000)]:
        bindings = services[service]["ports"]
        assert len(bindings) == 1
        assert bindings[0]["host_ip"] == (address or "127.0.0.1")
        assert bindings[0]["target"] == port and str(bindings[0]["published"]) == str(port)
        assert services[service]["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in services[service]["security_opt"]
        assert not services[service].get("privileged", False)


def test_binding_override_for_one_mode_does_not_widen_the_other(compose):
    services = compose(["openapi", "mcp-http"], MCP_HTTP_BIND_ADDRESS="192.0.2.10")
    assert services["proxmox-mcp-api"]["ports"][0]["host_ip"] == "127.0.0.1"
    assert services["proxmox-mcp-http"]["ports"][0]["host_ip"] == "192.0.2.10"
