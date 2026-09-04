import ast
import fnmatch
import json
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _setup_kwargs() -> dict[str, object]:
    tree = ast.parse((ROOT / "setup.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "setup":
            values: dict[str, object] = {}
            for kw in node.keywords:
                if not kw.arg:
                    continue
                try:
                    values[kw.arg] = ast.literal_eval(kw.value)
                except ValueError:
                    continue
            return values
    raise AssertionError("setup.py does not call setup()")


def test_release_versions_are_aligned():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    setup_kwargs = _setup_kwargs()
    package_init: dict[str, object] = {}
    exec(
        compile((ROOT / "src/proxmox_mcp/__init__.py").read_text(encoding="utf-8"), "__init__.py", "exec"),
        package_init,
    )
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))

    version = pyproject["project"]["version"]
    assert setup_kwargs["version"] == version
    assert package_init["__version__"] == version
    assert manifest["version"] == version
    assert server["version"] == version
    assert {package["version"] for package in server["packages"]} == {version}


def test_setup_metadata_tracks_pyproject_runtime_contract():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    setup_kwargs = _setup_kwargs()

    assert setup_kwargs["name"] == pyproject["project"]["name"]
    assert setup_kwargs["python_requires"] == pyproject["project"]["requires-python"]
    assert set(setup_kwargs["install_requires"]) == set(pyproject["project"]["dependencies"])
    assert set(setup_kwargs["entry_points"]["console_scripts"]) == {
        f"{name}={target}" for name, target in pyproject["project"]["scripts"].items()
    }


def test_ghcr_release_builds_pinned_multi_arch_images():
    workflow = (ROOT / ".github/workflows/publish-ghcr.yml").read_text(encoding="utf-8")
    docker_actions = re.findall(
        r"^\s*uses:\s+(docker/[^@\s]+)@([^\s#]+)",
        workflow,
        re.MULTILINE,
    )

    assert re.search(r"uses: docker/setup-qemu-action@[0-9a-f]{40}\s+# v4\.2\.0", workflow)
    assert re.search(r"uses: docker/setup-buildx-action@[0-9a-f]{40}\s+# v4\.2\.0", workflow)
    assert {name for name, _ in docker_actions} == {
        "docker/setup-qemu-action",
        "docker/setup-buildx-action",
        "docker/login-action",
        "docker/metadata-action",
        "docker/build-push-action",
    }
    assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for _, ref in docker_actions)
    assert re.search(r"image: docker\.io/tonistiigi/binfmt@sha256:[0-9a-f]{64}", workflow)
    assert "platforms: arm64" in workflow
    assert "platforms: linux/amd64,linux/arm64" in workflow
    assert "runs-on: ubuntu-24.04-arm" in workflow
    assert "docker pull --platform linux/arm64" in workflow
    assert "http://127.0.0.1:18811/livez" in workflow
    assert 'test "$(docker exec "$container_name" uname -m)" = "aarch64"' in workflow
    assert "test ! -e /usr/local/bin/pip" in workflow


def test_docker_context_excludes_local_secrets_and_tool_state():
    patterns = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert {".agents", ".codex", ".codex-run", ".playwright-cli"} <= patterns
    assert {".env", ".env.*", "*.key", "*.pem", "proxmox-config/*.json"} <= patterns
    assert {
        "!proxmox-config/config.example.json",
        "!proxmox-config/config.live.example.json",
    } <= patterns

    git_patterns = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for database in (
        "proxmox-jobs.sqlite3",
        "proxmox-jobs.sqlite3-wal",
        "proxmox-jobs.sqlite3-shm",
        "proxmox-jobs.sqlite3.target-lab",
        "proxmox-jobs.sqlite3.target-lab-wal",
        "proxmox-jobs.sqlite3.target-lab-shm",
    ):
        assert any(fnmatch.fnmatchcase(database, pattern) for pattern in patterns)
        assert any(fnmatch.fnmatchcase(database, pattern) for pattern in git_patterns)


def test_runtime_image_removes_python_packaging_toolchain():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert re.search(r"^FROM python:3\.11-slim@sha256:[0-9a-f]{64}$", dockerfile, re.MULTILINE)
    assert "python -m pip install --no-cache-dir ." in dockerfile
    assert "python -m pip uninstall --yes pip setuptools wheel" in dockerfile
