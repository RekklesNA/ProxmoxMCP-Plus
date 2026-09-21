"""Fail publication when metadata or built archives disagree with the release tag."""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import tarfile
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path


def check(root: Path, tag: str = "", dist: Path | None = None) -> str:
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    versions = {"pyproject.toml": version}
    tree = ast.parse((root / "setup.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "setup":
            versions["setup.py"] = next(ast.literal_eval(kw.value) for kw in node.keywords if kw.arg == "version")
    versions["package"] = re.search(r'__version__\s*=\s*["\x27]([^"\x27]+)', (root / "src/proxmox_mcp/__init__.py").read_text())[1]
    versions["manifest"] = json.loads((root / "manifest.json").read_text())["version"]
    server = json.loads((root / "server.json").read_text())
    versions["registry"] = server["version"]
    versions.update({f"registry package {i}": p["version"] for i, p in enumerate(server["packages"])})
    if tag:
        versions["release tag"] = tag.removeprefix("v")
    if dist is not None:
        wheels, sdists = list(dist.glob("*.whl")), list(dist.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise ValueError("Expected exactly one wheel and one source archive")
        with zipfile.ZipFile(wheels[0]) as wheel:
            name = next(n for n in wheel.namelist() if n.endswith('.dist-info/METADATA'))
            versions["wheel"] = Parser().parsestr(wheel.read(name).decode())["Version"]
        with tarfile.open(sdists[0]) as archive:
            name = next(n for n in archive.getnames() if n.endswith('/PKG-INFO'))
            stream = archive.extractfile(name)
            if stream is None:
                raise ValueError("Missing source archive metadata")
            versions["sdist"] = Parser().parsestr(stream.read().decode())["Version"]
    if any(v != version for v in versions.values()):
        raise ValueError(f"Release version mismatch: {versions}")
    print(f"Release metadata verified: {version}")
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default=os.environ.get("RELEASE_TAG") or (os.environ.get("GITHUB_REF_NAME", "") if os.environ.get("GITHUB_REF_TYPE") == "tag" else ""))
    parser.add_argument("--dist", type=Path)
    args = parser.parse_args()
    check(Path(__file__).resolve().parents[1], args.tag, args.dist)
