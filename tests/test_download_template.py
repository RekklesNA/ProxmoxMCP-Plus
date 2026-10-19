"""LXC downloads: destination evidence, single submission and public MCP policy."""
import json
from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from proxmoxer.core import ResourceException

from proxmox_mcp.models.tooling import result_succeeded, result_status
from proxmox_mcp.server import ProxmoxMCPServer
from proxmox_mcp.services.jobs import JobStore
from proxmox_mcp.services.tool_catalog import BUILTIN_TOOL_NAMES
from proxmox_mcp.tools.iso import ISOTools

ARGS = dict(node="six", storage="local", url="https://example.org/debian.tar.zst", filename="debian.tar.zst")
APPROVAL = "template-fixture-approval"
UPID = "UPID:six:00000001:00000001:12345678:download:template:fixture@pve:"


def backend():
    api = MagicMock()
    pool = {"storage": "local", "content": "iso,vztmpl,backup", "active": 1, "enabled": 1}
    api.nodes.return_value.storage.get.return_value = [pool]
    endpoint = api.nodes.return_value.storage.return_value
    endpoint.content.get.return_value = []
    endpoint.return_value.post.return_value = UPID
    return api, endpoint, pool


@pytest.fixture
def fixture():
    api, endpoint, pool = backend()
    tools = ISOTools(api)
    tools._register_background_job = MagicMock(return_value={"job_id": "job-123"})
    return tools, api, endpoint, pool


def payload(result):
    content = result[0] if isinstance(result, tuple) else result
    return json.loads(content[0].text)


@pytest.mark.parametrize("extension", ["gz", "xz", "zst"])
@pytest.mark.parametrize("algorithm,length", [("sha256", 64), ("sha512", 128), ("md5", 32)])
def test_download_template_submits_exact_payload_and_guarded_job(fixture, extension, algorithm, length):
    tools, api, endpoint, _ = fixture
    args = {**ARGS, "filename": "debian.tar." + extension, "checksum_algorithm": algorithm, "checksum": "A" * length}
    result = tools.download_template(**args, approval_token=APPROVAL)
    receipt = payload(result)
    assert receipt["status"] == "submitted" and receipt["job_id"] == "job-123"
    assert result_succeeded(result) and result_status(result) == "submitted"
    endpoint.assert_called_once_with("download-url")
    endpoint.return_value.post.assert_called_once_with(
        url=ARGS["url"], filename=args["filename"], content="vztmpl",
        **{"verify-certificates": 1, "checksum-algorithm": algorithm, "checksum": "A" * length},
    )
    endpoint.content.get.assert_called_once_with(content="vztmpl")
    registration = tools._register_background_job.call_args.kwargs
    assert registration["tool_name"] == "download_template"
    assert {"retry_spec", "retry_factory"}.isdisjoint(registration)
    assert "url" not in registration["metadata"]
    registration["cancel_factory"](UPID)
    api.nodes.return_value.tasks.assert_called_once_with(UPID)
    api.nodes.return_value.tasks.return_value.delete.assert_called_once_with()
    api.nodes.return_value.tasks.return_value.status.stop.post.assert_not_called()
    assert "download_template" in BUILTIN_TOOL_NAMES


@pytest.mark.parametrize("field,value", [
    ("filename", "../a.tar.zst"), ("filename", "a/b.tar.xz"), ("filename", "a\\b.tar.gz"),
    ("filename", "a.iso"), ("filename", ""), ("filename", "a b.tar.zst"),
    ("filename", "x%2fy.tar.zst"), ("filename", "a\x7f.tar.zst"),
    ("filename", "a" * 256 + ".tar.zst"), ("filename", None),
    ("url", "http://example.org/a"), ("url", "file:///etc/passwd"),
    ("url", "https://user:pass@example.org/a"), ("url", "https://@example.org/a"),
    ("url", "https:///a"), ("url", "https://example.org/a#fragment"),
    ("url", "https://example.org/a#"), ("url", "https://example.org:0/a"),
    ("url", "https://example.org:65536/a"), ("url", "https://example.org:bad/a"),
    ("url", "https://[bad/a"), ("url", "https://example.org/a\n"),
    ("url", "https://example.org/a\\b"), ("url", None),
    ("node", "../six"), ("node", "six/other"), ("storage", "local/other"),
    ("checksum_algorithm", "sha1"), ("checksum_algorithm", []),
    ("checksum", ""), ("checksum", "g" * 64), ("checksum", "a" * 32), ("checksum", 7),
])
def test_invalid_arguments_cannot_touch_the_api(fixture, field, value):
    tools, api, _, _ = fixture
    with pytest.raises(ValueError):
        tools.download_template(**{**ARGS, field: value})
    api.nodes.assert_not_called()


@pytest.mark.parametrize("inventory", [None, {}, [None], [], [{"storage": "other"}],
    [{"storage": "local"}, {"storage": "local"}]])
def test_missing_or_ambiguous_storage_fails_before_post(fixture, inventory):
    tools, api, endpoint, _ = fixture
    api.nodes.return_value.storage.get.return_value = inventory
    with pytest.raises(ValueError):
        tools.download_template(**ARGS)
    endpoint.return_value.post.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("active", 0), ("active", None), ("active", 1.0), ("enabled", "1"),
    ("enabled", False), ("content", "iso,backup"), ("content", None), ("content", ["vztmpl"]),
])
def test_invalid_storage_capabilities_fail_closed(fixture, field, value):
    tools, _, endpoint, pool = fixture
    pool[field] = value
    with pytest.raises(ValueError):
        tools.download_template(**ARGS)
    endpoint.return_value.post.assert_not_called()


@pytest.mark.parametrize("inventory", [None, {}, [None], [{}], [{"volid": None}],
    [{"volid": "local:vztmpl/debian.tar.zst", "content": "vztmpl"}]])
def test_unknown_inventory_or_existing_template_is_not_overwritten(fixture, inventory):
    tools, _, endpoint, _ = fixture
    endpoint.content.get.return_value = inventory
    with pytest.raises(ValueError):
        tools.download_template(**ARGS)
    endpoint.return_value.post.assert_not_called()


@pytest.mark.parametrize("stage", ["storage", "content"])
def test_inventory_transport_errors_are_definite_pre_submission_failures(fixture, stage):
    tools, api, endpoint, _ = fixture
    getter = api.nodes.return_value.storage.get if stage == "storage" else endpoint.content.get
    getter.side_effect = ConnectionError("offline")
    with pytest.raises(RuntimeError, match="prepare template download"):
        tools.download_template(**ARGS)
    endpoint.return_value.post.assert_not_called()
    tools._register_background_job.assert_not_called()


@pytest.mark.parametrize("outcome", [None, {}, "", "OK", "UPID:other:download",
    ConnectionError("response lost"), ResourceException(500, "Server Error", "lost")])
def test_unknown_post_outcome_is_unsuccessful_and_never_retried(fixture, outcome):
    tools, _, endpoint, _ = fixture
    if isinstance(outcome, Exception):
        endpoint.return_value.post.side_effect = outcome
    else:
        endpoint.return_value.post.return_value = outcome
    result = tools.download_template(**ARGS)
    receipt = payload(result)
    assert receipt["code"] == "SUBMISSION_UNCERTAIN" and receipt["retryable"] is False
    assert receipt["status"] == "unknown"
    assert result_succeeded(result) is False and result_status(result) == "error"
    endpoint.return_value.post.assert_called_once()
    tools._register_background_job.assert_not_called()


@pytest.mark.parametrize("status", [400, 403, 409])
def test_explicit_pve_rejection_is_not_reported_as_unknown(fixture, status):
    tools, _, endpoint, _ = fixture
    endpoint.return_value.post.side_effect = ResourceException(status, "Error", "invalid request")
    with pytest.raises(ValueError):
        tools.download_template(**ARGS)
    endpoint.return_value.post.assert_called_once()
    tools._register_background_job.assert_not_called()


@pytest.mark.parametrize("tracking", [None, "broken"])
def test_submission_retains_upid_without_local_job_tracking(fixture, tracking):
    tools, _, endpoint, _ = fixture
    tools._register_background_job.return_value = None
    if tracking == "broken":
        tools._register_background_job.side_effect = OSError("database full")
    receipt = payload(tools.download_template(**ARGS))
    assert receipt["success"] is True and receipt["task_id"] == UPID and receipt["job_id"] is None
    assert bool(receipt["tracking_warning"]) is (tracking == "broken")
    assert "checksum" not in endpoint.return_value.post.call_args.kwargs


def test_task_persistence_cancel_and_no_blind_retry_after_restart(tmp_path):
    api, endpoint, pool = backend()
    pool["active"] = True
    pool["enabled"] = True
    endpoint.content.get.return_value = [{"volid": "local:vztmpl/other.tar.zst"}]
    database = str(tmp_path / "jobs.sqlite")
    with JobStore(api, database) as store:
        receipt = payload(ISOTools(api, job_store=store).download_template(**ARGS))
        job_id = receipt["job_id"]
    with JobStore(api, database) as store:
        assert store.get_job(job_id)["tool_name"] == "download_template"
        assert store.cancel_job(job_id)["status"] == "cancel_requested"
        api.nodes.return_value.tasks.return_value.delete.assert_called_once_with()
        api.nodes.return_value.tasks.return_value.status.get.return_value = {"status": "stopped", "exitstatus": "ERROR"}
        api.nodes.return_value.tasks.return_value.log.get.return_value = []
        assert store.poll_job(job_id, force=True)["status"] == "failed"
        with pytest.raises(ValueError, match="retry"):
            store.retry_job(job_id)
    endpoint.return_value.post.assert_called_once()


def make_server(tmp_path, *, readonly=False, grant=True):
    fixtures = {name: backend() for name in ("chosen", "other")}
    config = {"targets": {name: {
        "host": name, "readonly": readonly,
        "auth": {"user": "test@pve", "token_name": "test", "token_value": "fixture"},
        "command_policy": {"high_risk_mode": "enforce", "high_risk_require_approval_token": True,
            "high_risk_approval_token": APPROVAL if name == "chosen" else APPROVAL + "-other"},
    } for name in fixtures}, "jobs": {"sqlite_path": str(tmp_path / "jobs.sqlite")}}
    if not grant:
        config["mcp"] = {"client_permissions": {"_local": {"targets": ["chosen"], "tools": ["list_templates"]}}}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with patch("proxmox_mcp.core.proxmox.ProxmoxAPI", side_effect=lambda **kw: fixtures[kw["host"]][0]):
        server = ProxmoxMCPServer(str(path))
    for api, _, _ in fixtures.values():
        api.reset_mock()
    return server, fixtures


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing_approval", "wrong_approval", "readonly", "client_grant", "wrong_target_token", "missing_target", "unknown_target"])
async def test_public_mcp_policy_denies_before_proxmox(tmp_path, case):
    server, fixtures = make_server(tmp_path, readonly=case == "readonly", grant=case != "client_grant")
    args = {**ARGS, "target": "chosen", "approval_token": APPROVAL}
    if case == "missing_approval":
        args.pop("approval_token")
    elif case == "wrong_approval":
        args["approval_token"] = "wrong"
    elif case == "wrong_target_token":
        args["target"] = "other"
    elif case == "missing_target":
        args.pop("target")
    elif case == "unknown_target":
        args["target"] = "unknown"
    try:
        with pytest.raises(ToolError):
            await server.mcp.call_tool("download_template", args)
        for api, _, _ in fixtures.values():
            api.nodes.assert_not_called()
            api.nodes.get.assert_not_called()
    finally:
        server.close()


@pytest.mark.asyncio
async def test_approved_public_dispatch_tracks_only_selected_target(tmp_path):
    server, fixtures = make_server(tmp_path)
    try:
        schema = {tool.name: tool for tool in await server.mcp.list_tools()}["download_template"].inputSchema
        assert {"node", "storage", "url", "filename", "checksum", "approval_token", "target"} <= schema["properties"].keys()
        assert "download_template" in server.config.command_policy.high_risk_operations
        result = await server.mcp.call_tool("download_template", {**ARGS, "target": "chosen", "approval_token": APPROVAL})
        receipt = payload(result)
        assert receipt["status"] == "submitted" and receipt["job_id"]
        endpoint = fixtures["chosen"][1]
        endpoint.return_value.post.assert_called_once_with(**{
            "url": ARGS["url"], "filename": ARGS["filename"], "content": "vztmpl", "verify-certificates": 1,
        })
        fixtures["other"][0].nodes.assert_not_called()
        job = server.target_job_stores["chosen"].get_job(receipt["job_id"])
        assert job["tool_name"] == "download_template"
        assert "url" not in job["metadata"]
    finally:
        server.close()
