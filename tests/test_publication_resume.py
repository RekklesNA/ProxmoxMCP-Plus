"""Publication retries must verify existing artifacts before skipping uploads."""

import hashlib
import importlib.util
import io
import json
import tarfile
import urllib.error
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("publication", Path(__file__).resolve().parents[1] / "scripts/check_pypi_publication.py")
publication = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publication)


def archive_bytes(filename, content=b"checked source", timestamp=2020):
    output = io.BytesIO()
    if filename.endswith(".whl"):
        with zipfile.ZipFile(output, "w") as archive:
            entry = zipfile.ZipInfo("proxmox_mcp/server.py", (timestamp, 1, 1, 0, 0, 0))
            archive.writestr(entry, content)
    else:
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            entry = tarfile.TarInfo("package/src/proxmox_mcp/server.py")
            entry.size, entry.mtime, entry.mode = len(content), timestamp, 0o644
            archive.addfile(entry, io.BytesIO(content))
    return output.getvalue()


@pytest.fixture
def artifacts(tmp_path):
    names = ["proxmox_mcp_plus-0.6.0-py3-none-any.whl", "proxmox_mcp_plus-0.6.0.tar.gz"]
    for name in names:
        (tmp_path / name).write_bytes(archive_bytes(name))
    return tmp_path, names


def published(monkeypatch, names, *, content=b"checked source", version="0.6.0", **overrides):
    downloads = {f"https://files.pythonhosted.org/{name}": archive_bytes(name, content, timestamp=2022) for name in names}
    payload = {"info": {"version": version}, "urls": [
        dict(filename=name, url=url, digests={"sha256": hashlib.sha256(data).hexdigest()}, **overrides)
        for (url, data), name in zip(downloads.items(), names)
    ]}
    monkeypatch.setattr(publication, "fetch", lambda url: downloads[url] if "files.pythonhosted.org" in url else json.dumps(payload).encode())
    return payload


def test_unpublished_version_keeps_both_uploads(artifacts, monkeypatch):
    dist, names = artifacts

    def missing(url):
        raise urllib.error.HTTPError(url, 404, "not found", {}, None)

    monkeypatch.setattr(publication, "fetch", missing)
    assert publication.check(dist, "0.6.0")
    assert {path.name for path in dist.iterdir()} == set(names)


@pytest.mark.parametrize("count", [0, 1, 2])
def test_partial_and_complete_publication_accept_identical_contents(artifacts, monkeypatch, count):
    dist, names = artifacts
    published(monkeypatch, names[:count])
    assert publication.check(dist, "0.6.0") == (count != 2)
    assert {path.name for path in dist.iterdir()} == set(names[count:])


def test_changed_archive_fails_before_removing_any_file(artifacts, monkeypatch):
    dist, names = artifacts
    published(monkeypatch, names, content=b"different source")
    with pytest.raises(ValueError, match="contents differ"):
        publication.check(dist, "0.6.0")
    assert {path.name for path in dist.iterdir()} == set(names)


def test_later_mismatch_preserves_an_earlier_matching_artifact(artifacts, monkeypatch):
    dist, names = artifacts
    payload = published(monkeypatch, names)
    original_fetch = publication.fetch
    changed = archive_bytes(names[1], b"changed source")
    payload["urls"][1]["digests"]["sha256"] = hashlib.sha256(changed).hexdigest()
    monkeypatch.setattr(publication, "fetch", lambda url: changed if url.endswith(".tar.gz") else original_fetch(url))
    with pytest.raises(ValueError, match="contents differ"):
        publication.check(dist, "0.6.0")
    assert {path.name for path in dist.iterdir()} == set(names)


@pytest.mark.parametrize("condition", ["version", "checksum", "yanked", "origin"])
def test_invalid_publication_metadata_fails_closed(artifacts, monkeypatch, condition):
    dist, names = artifacts
    payload = published(monkeypatch, names)
    if condition == "version":
        payload["info"]["version"] = "0.5.27"
    elif condition == "checksum":
        payload["urls"][0]["digests"]["sha256"] = "0" * 64
    elif condition == "yanked":
        payload["urls"][0]["yanked"] = True
    else:
        payload["urls"][0]["url"] = "https://example.invalid/package.whl"
    with pytest.raises(ValueError):
        publication.check(dist, "0.6.0")
    assert {path.name for path in dist.iterdir()} == set(names)


def test_non_404_errors_are_not_treated_as_unpublished(artifacts, monkeypatch):
    def unavailable(url):
        raise urllib.error.HTTPError(url, 503, "unavailable", {}, None)

    monkeypatch.setattr(publication, "fetch", unavailable)
    with pytest.raises(urllib.error.HTTPError):
        publication.check(artifacts[0], "0.6.0")


def test_publication_requires_both_distribution_types(tmp_path):
    with pytest.raises(ValueError, match="one wheel"):
        publication.check(tmp_path, "0.6.0")


@pytest.mark.parametrize("filename", ["package.whl", "package.tar.gz"])
def test_unpacked_artifacts_are_bounded(filename, monkeypatch):
    monkeypatch.setattr(publication, "MAX_BYTES", 4)
    with pytest.raises(ValueError, match="size limit"):
        publication.contents(archive_bytes(filename), filename)


def test_download_response_is_bounded(monkeypatch):
    monkeypatch.setattr(publication, "MAX_BYTES", 4)
    monkeypatch.setattr(publication.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(b"12345"))
    with pytest.raises(ValueError, match="size limit"):
        publication.fetch("https://pypi.org/")
