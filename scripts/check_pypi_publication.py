"""Verify existing PyPI artifacts before resuming a partially completed upload."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import tarfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

MAX_BYTES = 64 * 1024 * 1024


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Publication response exceeds the size limit")
    return data


def contents(data: bytes, filename: str) -> dict[str, tuple[object, ...]]:
    """Compare installable members, ignoring archive creation timestamps."""
    result: dict[str, tuple[object, ...]] = {}
    size = 0
    if filename.endswith(".whl"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for entry in archive.infolist():
                if entry.filename in result:
                    raise ValueError("Duplicate wheel member")
                size += entry.file_size
                if size > MAX_BYTES:
                    raise ValueError("Unpacked wheel exceeds the size limit")
                result[entry.filename] = (bool(entry.external_attr >> 16 & 0o111),
                                          hashlib.sha256(archive.read(entry)).hexdigest())
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            for member in archive:
                if member.name in result:
                    raise ValueError("Duplicate source archive member")
                size += member.size
                if size > MAX_BYTES:
                    raise ValueError("Unpacked source archive exceeds the size limit")
                stream = archive.extractfile(member) if member.isfile() else None
                digest = hashlib.sha256(stream.read()).hexdigest() if stream else None
                result[member.name] = (member.type, member.mode, member.linkname, digest)
    return result


def check(dist: Path, version: str) -> bool:
    """Remove only verified existing files, leaving unpublished artifacts to upload."""
    wheels, sdists = list(dist.glob("*.whl")), list(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("Expected one wheel and one source archive")
    artifacts = wheels + sdists
    try:
        payload = json.loads(fetch(f"https://pypi.org/pypi/proxmox-mcp-plus/{urllib.parse.quote(version, safe='')}/json"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return True
        raise
    if payload["info"]["version"] != version:
        raise ValueError("PyPI returned an unexpected version")
    published = {item["filename"]: item for item in payload["urls"]}
    verified = []
    for path in artifacts:
        item = published.get(path.name)
        if item is None:
            continue
        url = urllib.parse.urlsplit(item["url"])
        if item.get("yanked") or url.scheme != "https" or url.hostname != "files.pythonhosted.org":
            raise ValueError("Existing artifact is yanked or has an unexpected download origin")
        remote = fetch(item["url"])
        if hashlib.sha256(remote).hexdigest() != item["digests"]["sha256"]:
            raise ValueError("Published artifact checksum mismatch")
        if contents(remote, path.name) != contents(path.read_bytes(), path.name):
            raise ValueError(f"Existing artifact contents differ: {path.name}")
        verified.append(path)
    # Validate every existing artifact before changing the upload directory.
    for path in verified:
        path.unlink()
        print(f"Verified existing artifact: {path.name}")
    return len(verified) != len(artifacts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    needed = check(args.dist, args.version)
    output = f"publish_needed={str(needed).lower()}\n"
    if os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
            stream.write(output)
    print(output.strip())
