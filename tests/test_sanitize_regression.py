"""Regression tests for _sanitize and _log_safe fixes."""
from __future__ import annotations
from unittest.mock import Mock

from proxmox_mcp.services.jobs import JobConflictError, JobStore, _sanitize
from proxmox_mcp.tools.base import _log_safe as base_log_safe
from proxmox_mcp.core.proxmox import _log_safe as proxmox_log_safe
from proxmox_mcp.core.ssh_tunnel import _log_safe as ssh_log_safe


def test_sanitize_does_not_corrupt_innocent_url(tmp_path):
    url = "https://cdn.example/ubuntu.iso?ver=22.04&arch=amd64"
    assert _sanitize(url) == url
    # nested in retry_spec
    spec = {"kind": "iso.download", "params": {"node": "pve", "storage": "local", "request": {"url": url, "filename": "ubuntu.iso"}}}
    assert _sanitize(spec) == spec


def test_sanitize_redacts_secret_query_param():
    url = "https://cdn.example/ubuntu.iso?ver=22.04&token=sig123"
    sanitized = _sanitize(url)
    assert "sig123" not in sanitized
    assert "token=[REDACTED]" in sanitized
    assert "ver=22.04" in sanitized  # non-secret preserved

    trailing = _sanitize("https://cdn.example/file?token=sig123&arch=amd64&ver=1")
    assert trailing == "https://cdn.example/file?token=[REDACTED]&arch=amd64&ver=1"


def test_sanitize_redacts_userinfo():
    url = "https://root:hunter2@10.0.0.1:8006/api2/json"
    assert _sanitize(url) == "https://[REDACTED]@10.0.0.1:8006/api2/json"
    assert "hunter2" not in _sanitize(url)


def test_sanitize_redacts_secret_dict_keys():
    payload = {"password": "hunter2", "nested": {"api_key": "abc", "safe": "ok"}, "url": "https://example.com/?secret=xyz"}
    sanitized = _sanitize(payload)
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["nested"]["api_key"] == "[REDACTED]"
    assert sanitized["nested"]["safe"] == "ok"
    assert "xyz" not in sanitized["url"]


def test_log_safe_redacts_embedded_userinfo_url():
    msg = "Failed to connect: https://root:hunter2@10.0.0.1:8006/api2/json (ConnectionError)"
    out = base_log_safe(msg)
    assert "hunter2" not in out
    assert "[REDACTED]@" in out
    assert "10.0.0.1" in out


def test_log_safe_redacts_secret_kv_in_exception_text():
    # realistic requests ConnectionError with URL containing token
    msg = "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='cdn.example', port=443): Max retries exceeded with url: https://cdn.example/ubuntu.iso?token=sig123 (Caused by NewConnectionError)"
    out = base_log_safe(msg)
    assert "sig123" not in out
    assert "token=[REDACTED]" in out


def test_log_safe_redacts_authorization_header():
    msg = "proxmoxer.core.ResourceException: 401 Unauthorized: authorization: Bearer abc.def.ghi"
    out = base_log_safe(msg)
    assert "authorization=[REDACTED]" in out.lower() or "[REDACTED]" in out
    assert "abc.def.ghi" not in out


def test_sanitizers_redact_json_and_hyphenated_api_keys():
    from proxmox_mcp.services.jobs import _sanitize_string

    for sanitizer in (base_log_safe, _sanitize_string):
        output = sanitizer('{"token": "supersecret123", "password": "hunter2"}')
        assert "supersecret123" not in output
        assert "hunter2" not in output
        output = sanitizer("X-Api-Key: LEAKED_KEY_VALUE")
        assert "LEAKED_KEY_VALUE" not in output


def test_log_safe_redacts_password_equals_pattern():
    msg = "Authentication failed for user root password=hunter2"
    assert "hunter2" not in base_log_safe(msg)
    assert "password=[REDACTED]" in base_log_safe(msg)


def test_log_safe_truncates():
    long = "x" * 500
    assert len(base_log_safe(long)) == 200
    assert len(proxmox_log_safe(long)) == 200
    assert len(ssh_log_safe(long)) == 200


def test_retry_spec_url_corruption_not_persisted(tmp_path):
    proxmox = Mock()
    store = JobStore(proxmox, sqlite_path=str(tmp_path / "jobs.sqlite3"))
    url = "https://cdn.example/ubuntu.iso?ver=22.04&token=sig123"
    retry_spec = {"kind": "iso.download", "params": {"node": "pve", "storage": "local", "request": {"url": url, "filename": "ubuntu.iso"}}}
    job = store.register_task(tool_name="download_iso", summary="dl", node="pve", upid="UPID:1", retry_spec=retry_spec)
    # outbound is sanitized
    assert "sig123" not in str(job["retry_spec"])
    # persisted is redacted flag set, stored as None
    assert job["retry_spec"]["params"]["request"]["url"].endswith("token=[REDACTED]")
    assert job["retry_spec_redacted"] is True
    # retry must raise
    try:
        store._conn.execute("UPDATE jobs SET status='failed' WHERE job_id=?", (job["job_id"],))
        store._conn.commit()
        store.retry_job(job["job_id"])
        assert False, "should have raised"
    except JobConflictError as e:
        assert "redacted" in str(e).lower()


def test_retry_spec_innocent_url_persists(tmp_path):
    proxmox = Mock()
    # handler for iso.download
    store = JobStore(proxmox, sqlite_path=str(tmp_path / "jobs2.sqlite3"))
    url = "https://cdn.example/ubuntu.iso?ver=22.04&arch=amd64"
    retry_spec = {"kind": "iso.download", "params": {"node": "pve", "storage": "local", "request": {"url": url, "filename": "ubuntu.iso"}}}
    job = store.register_task(tool_name="download_iso", summary="dl", node="pve", upid="UPID:1", retry_spec=retry_spec)
    assert job["retry_spec"] is not None
    assert job["retry_spec_redacted"] is False
    # persisted value intact
    import sqlite3
    import json
    raw = sqlite3.connect(str(tmp_path / "jobs2.sqlite3")).execute("SELECT retry_spec_json FROM jobs").fetchone()[0]
    loaded = json.loads(raw)
    assert loaded["params"]["request"]["url"] == url


def test_sanitize_preserves_non_secret_retry_spec(tmp_path):
    proxmox = Mock()
    proxmox.nodes.return_value.qemu.return_value.status.start.post.return_value = "UPID:retry"
    store = JobStore(proxmox, sqlite_path=str(tmp_path / "jobs3.sqlite3"))
    retry_spec = {"kind": "vm.start", "params": {"node": "pve", "vmid": "100"}}
    job = store.register_task(tool_name="start_vm", summary="start", node="pve", upid="UPID:1", retry_spec=retry_spec)
    assert job["retry_spec"] == retry_spec
