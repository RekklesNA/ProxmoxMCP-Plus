"""Contracts for LXC template downloading via the Proxmox REST API."""

from unittest.mock import MagicMock

import pytest

from proxmox_mcp.services.tool_catalog import BUILTIN_TOOL_NAMES
from proxmox_mcp.tools.iso import ISOTools


def test_download_template_submits_vztmpl_and_registers_job():
    api = MagicMock()
    endpoint = api.nodes.return_value.storage.return_value
    endpoint.return_value.post.return_value = "UPID:six:download"
    tools = ISOTools(api)
    tools._register_background_job = MagicMock(return_value={"job_id": "job-123"})
    tools._submission_content = MagicMock(return_value=[])

    result = tools.download_template(
        node="six",
        storage="local",
        url="https://example.org/debian-13.tar.zst",
        filename="debian-13.tar.zst",
        checksum="a" * 64,
    )

    endpoint.assert_called_with("download-url")
    assert endpoint.return_value.post.call_args.kwargs == {
        "url": "https://example.org/debian-13.tar.zst",
        "filename": "debian-13.tar.zst",
        "content": "vztmpl",
        "checksum": "a" * 64,
        "checksum-algorithm": "sha256",
    }
    job_kwargs = tools._register_background_job.call_args.kwargs
    assert job_kwargs["tool_name"] == "download_template"
    assert job_kwargs["retry_spec"]["kind"] == "iso.download"
    assert job_kwargs["retry_spec"]["params"]["request"]["content"] == "vztmpl"
    assert "job-123" in result[0].text
    assert "download_template" in BUILTIN_TOOL_NAMES


@pytest.mark.parametrize("filename", [
    "../escape.tar.zst",
    "path/to/file.tar.xz",
    "bad\\name.tar.gz",
    "bad.iso",
    "",
])
def test_download_template_rejects_bad_filename(filename):
    api = MagicMock()
    tools = ISOTools(api)
    with pytest.raises(ValueError):
        tools.download_template("six", "local", "https://example.org/a.tar.zst", filename)
    api.nodes.assert_not_called()


@pytest.mark.parametrize("url", [
    "http://example.org/a.tar.zst",
    "file:///etc/passwd",
    "https://user:pass@example.org/a.tar.zst",
    "https:///a.tar.zst",
])
def test_download_template_rejects_bad_url(url):
    api = MagicMock()
    tools = ISOTools(api)
    with pytest.raises(ValueError):
        tools.download_template("six", "local", url, "a.tar.zst")
    api.nodes.assert_not_called()


def test_download_template_rejects_bad_digest():
    api = MagicMock()
    tools = ISOTools(api)
    with pytest.raises(ValueError):
        tools.download_template("six", "local", "https://example.org/a.tar.zst", "a.tar.zst", checksum="nope")
    api.nodes.assert_not_called()
