import importlib.util
from pathlib import Path

import pytest


def _reload_run_real_e2e():
    module_path = Path(__file__).resolve().parents[1] / "test_scripts" / "run_real_e2e.py"
    spec = importlib.util.spec_from_file_location("run_real_e2e_for_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolve_live_config_path_prefers_explicit_e2e_env(tmp_path, monkeypatch):
    config_path = tmp_path / "custom-live.json"
    config_path.write_text("{}")
    monkeypatch.setenv("PROXMOX_MCP_E2E_CONFIG", str(config_path))
    monkeypatch.delenv("PROXMOX_MCP_CONFIG", raising=False)

    run_real_e2e = _reload_run_real_e2e()

    assert run_real_e2e.resolve_live_config_path() == config_path


def test_resolve_live_config_path_rejects_default_runtime_config(monkeypatch):
    monkeypatch.delenv("PROXMOX_MCP_E2E_CONFIG", raising=False)
    monkeypatch.delenv("PROXMOX_MCP_CONFIG", raising=False)

    run_real_e2e = _reload_run_real_e2e()

    live_path = run_real_e2e.DEFAULT_LIVE_CONFIG_PATH
    backup_text = None
    if live_path.exists():
        backup_text = live_path.read_text(encoding="utf-8")
        live_path.unlink()
    try:
        with pytest.raises(FileNotFoundError, match="config.live.json"):
            run_real_e2e.resolve_live_config_path()
    finally:
        if backup_text is not None:
            live_path.write_text(backup_text, encoding="utf-8")


def test_assert_config_is_live_ready_blocks_local_default(monkeypatch):
    run_real_e2e = _reload_run_real_e2e()

    class Proxmox:
        host = "127.0.0.1"

    class Config:
        proxmox = Proxmox()

    with pytest.raises(RuntimeError, match="Refusing to run live e2e"):
        run_real_e2e.assert_config_is_live_ready(run_real_e2e.DEFAULT_CONFIG_PATH, Config())
