"""Run live end-to-end checks against a real Proxmox environment."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
DEFAULT_CONFIG_PATH = ROOT / "proxmox-config" / "config.json"
DEFAULT_LIVE_CONFIG_PATH = ROOT / "proxmox-config" / "config.live.json"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


TASK_RE = re.compile(r"Task ID:\s*(\S+)")
TEST_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICodexLiveE2ETestKey codex-live-e2e"


def log(message: str) -> None:
    print(f"[live-e2e] {message}", flush=True)


def call_with_transient_retry(getter: Any, context: str, attempts: int = 8, delay: float = 2.0) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return getter()
        except (requests.exceptions.RequestException, OSError) as exc:
            last_error = exc
            if attempt == attempts:
                break
            log(f"Transient API failure during {context}; retrying ({attempt}/{attempts}) -> {exc}")
            time.sleep(delay)
    raise RuntimeError(f"Failed during {context} after {attempts} attempts: {last_error}") from last_error


def resolve_live_config_path() -> Path:
    explicit_e2e = os.getenv("PROXMOX_MCP_E2E_CONFIG")
    if explicit_e2e:
        return Path(explicit_e2e)

    if DEFAULT_LIVE_CONFIG_PATH.exists():
        return DEFAULT_LIVE_CONFIG_PATH

    explicit_runtime = os.getenv("PROXMOX_MCP_CONFIG")
    if explicit_runtime:
        explicit_path = Path(explicit_runtime)
        if explicit_path != DEFAULT_CONFIG_PATH:
            return explicit_path

    raise FileNotFoundError(
        "Live e2e requires a dedicated reachable config. "
        "Create proxmox-config/config.live.json from proxmox-config/config.live.example.json, "
        "or set PROXMOX_MCP_E2E_CONFIG to an explicit live config path."
    )


def tcp_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def build_connectivity_hint(config: Any) -> str:
    proxmox_host = str(config.proxmox.host)
    proxmox_port = int(config.proxmox.port)
    lines = [
        f"Configured Proxmox API target {proxmox_host}:{proxmox_port} is not reachable from this machine.",
    ]

    api_tunnel = getattr(config, "api_tunnel", None)
    ssh_config_path = Path.home() / ".ssh" / "config"
    ssh_config_text = ""
    if ssh_config_path.exists():
        ssh_config_text = ssh_config_path.read_text(encoding="utf-8", errors="ignore")
    if api_tunnel is not None and getattr(api_tunnel, "enabled", False):
        lines.append(
            f"Automatic API tunnel is enabled via ssh host '{api_tunnel.ssh_host}', but that SSH path is not reachable either."
        )
        lines.append(
            "Restore the jump-host/VPN path first; once SSH to that alias works, the server will create the local API forward automatically."
        )
    elif proxmox_host in {"localhost", "127.0.0.1", "::1"}:
        lines.append(
            "This config assumes a local tunnel or local PVE install, but no local listener is present."
        )
        ssh_cfg = config.ssh
        if ssh_cfg is not None:
            lines.append(
                f"Configured SSH path also looks local-only: port {ssh_cfg.port}, host_overrides={ssh_cfg.host_overrides or {}}."
            )
        if "proxyjump" in ssh_config_text.lower():
            lines.append(
                "Your ~/.ssh/config still contains jump-host entries. This usually means the real PVE lives behind a jump host, not on localhost."
            )
        lines.append(
            "Fix one of these before rerunning e2e: set proxmox.host to the actual reachable PVE address, or re-establish the local tunnel that used to forward 8006/2222."
        )
    else:
        lines.append(
            "Either the host is wrong, the required VPN/Tailscale/SSH jump path is down, or a firewall blocks access."
        )

    return "\n".join(lines)


def validate_live_connectivity(config: Any) -> None:
    proxmox_host = str(config.proxmox.host)
    proxmox_port = int(config.proxmox.port)
    api_tunnel = getattr(config, "api_tunnel", None)
    if api_tunnel is not None and getattr(api_tunnel, "enabled", False):
        ssh_host = str(api_tunnel.ssh_host)
        if not tcp_reachable(ssh_host, 22):
            raise RuntimeError(build_connectivity_hint(config))
        return

    if not tcp_reachable(proxmox_host, proxmox_port):
        raise RuntimeError(build_connectivity_hint(config))

    if config.ssh is not None:
        ssh_port = int(config.ssh.port)
        override_hosts = config.ssh.host_overrides or {}
        if proxmox_host in {"localhost", "127.0.0.1", "::1"} and override_hosts:
            unresolved = [
                f"{node_alias}->{ssh_host}:{ssh_port}"
                for node_alias, ssh_host in sorted(override_hosts.items())
                if not tcp_reachable(str(ssh_host), ssh_port)
            ]
            if unresolved:
                log(
                    "SSH override targets are currently unreachable: "
                    + ", ".join(unresolved)
                )


def parse_json_text(contents: list[Any]) -> Any:
    return json.loads(contents[0].text)


def extract_task_id(contents: list[Any]) -> str:
    text = contents[0].text
    match = TASK_RE.search(text)
    if not match:
        raise RuntimeError(f"Unable to find task ID in tool response:\n{text}")
    return match.group(1)


def extract_task_id_from_item(item: dict[str, Any]) -> str:
    raw = item.get("task_id") or item.get("message") or item.get("upid")
    if isinstance(raw, str) and raw.startswith("UPID:"):
        return raw
    raise RuntimeError(f"Unable to find task ID in JSON item: {item}")


def wait_for_task(api: Any, node: str, upid: str, timeout: int = 900) -> dict[str, Any]:
    deadline = time.time() + timeout
    last_status: dict[str, Any] | None = None
    while time.time() < deadline:
        status = call_with_transient_retry(
            lambda: api.nodes(node).tasks(upid).status.get(),
            f"task status poll for {upid}",
        )
        last_status = status if isinstance(status, dict) else {"raw": status}
        exit_status = str(last_status.get("exitstatus", "") or "")
        state = str(last_status.get("status", "") or "").lower()
        if exit_status:
            if exit_status == "OK":
                return last_status
            raise RuntimeError(f"Task {upid} failed: {last_status}")
        if state in {"stopped", "ok"}:
            return last_status
        time.sleep(2)
    raise TimeoutError(f"Timed out waiting for task {upid}: {last_status}")


def wait_for_guest_status(getter: Any, expected: str, timeout: int = 180) -> dict[str, Any]:
    deadline = time.time() + timeout
    last_status: dict[str, Any] | None = None
    while time.time() < deadline:
        status = call_with_transient_retry(
            getter,
            f"guest status wait for '{expected}'",
        )
        last_status = status if isinstance(status, dict) else {"raw": status}
        if last_status.get("status") == expected:
            return last_status
        time.sleep(2)
    raise TimeoutError(f"Timed out waiting for guest status '{expected}': {last_status}")


def next_vmid(api: Any) -> int:
    value = api.cluster.nextid.get()
    return int(value["data"] if isinstance(value, dict) and "data" in value else value)


def reserve_vmids(api: Any, count: int) -> list[int]:
    used: set[int] = set()
    for node in api.nodes.get():
        node_name = str(node["node"])
        for vm in api.nodes(node_name).qemu.get():
            if "vmid" in vm:
                used.add(int(vm["vmid"]))
        for ct in api.nodes(node_name).lxc.get():
            if "vmid" in ct:
                used.add(int(ct["vmid"]))

    start = next_vmid(api)
    reserved: list[int] = []
    candidate = start
    while len(reserved) < count:
        if candidate not in used:
            reserved.append(candidate)
            used.add(candidate)
        candidate += 1
    return reserved


def storage_supports(storage: dict[str, Any], content: str) -> bool:
    raw = str(storage.get("content", "") or "")
    return content in {part.strip() for part in raw.split(",") if part.strip()}


def choose_online_node(api: Any) -> str:
    nodes = api.nodes.get()
    for node in nodes:
        if node.get("status") == "online":
            return str(node["node"])
    raise RuntimeError("No online Proxmox node found")


def choose_storage(api: Any, node: str, content: str) -> str:
    for storage in api.nodes(node).storage.get():
        if storage_supports(storage, content):
            return str(storage["storage"])
    raise RuntimeError(f"No storage on node {node} supports '{content}'")


def choose_container_storage(api: Any, node: str) -> str:
    for storage in api.nodes(node).storage.get():
        if storage_supports(storage, "rootdir") or storage_supports(storage, "images"):
            return str(storage["storage"])
    raise RuntimeError(f"No container-capable storage found on node {node}")


def choose_template(api: Any, node: str) -> str:
    for storage in api.nodes(node).storage.get():
        if not storage_supports(storage, "vztmpl"):
            continue
        storage_name = str(storage["storage"])
        content = api.nodes(node).storage(storage_name).content.get(content="vztmpl")
        if content:
            return str(content[0]["volid"])
    raise RuntimeError(f"No LXC template found on node {node}")


def choose_template_storage(api: Any, node: str) -> str:
    return choose_storage(api, node, "vztmpl")


def choose_appliance_template(api: Any, node: str) -> dict[str, Any]:
    preferred_names = (
        "alpine-",
        "debian-12-standard_",
        "ubuntu-22.04-standard_",
    )
    aplinfo = api.nodes(node).aplinfo.get()
    templates = [item for item in aplinfo if isinstance(item, dict) and item.get("type") == "lxc"]
    if not templates:
        raise RuntimeError(f"No downloadable LXC templates available for node {node}")

    for prefix in preferred_names:
        for item in templates:
            template_name = str(item.get("template", "") or "")
            if template_name.startswith(prefix):
                return item
    return templates[0]


def ensure_template(api: Any, node: str) -> str:
    try:
        return choose_template(api, node)
    except RuntimeError:
        storage = choose_template_storage(api, node)
        template_info = choose_appliance_template(api, node)
        filename = str(template_info["template"])
        url = str(template_info["location"])
        params: dict[str, Any] = {
            "url": url,
            "filename": filename,
            "content": "vztmpl",
        }
        checksum = template_info.get("sha512sum")
        if checksum:
            params["checksum"] = str(checksum)
            params["checksum-algorithm"] = "sha512"
        log(f"Downloading LXC template {filename} to {storage} from {url}")
        upid = api.nodes(node).storage(storage)("download-url").post(**params)
        wait_for_task(api, node, str(upid), timeout=1800)
        return choose_template(api, node)


def newest_backup(api: Any, node: str, storage: str, vmid: int) -> str:
    backups = api.nodes(node).storage(storage).content.get(content="backup", vmid=vmid)
    if not backups:
        raise RuntimeError(f"No backup found for VM/CT {vmid} in storage {storage}")
    backups = sorted(backups, key=lambda item: item.get("ctime", 0), reverse=True)
    return str(backups[0]["volid"])


def wait_for_http(url: str, timeout: int = 120) -> requests.Response:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            response = requests.get(url, timeout=5)
            if response.ok:
                return response
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(2)
    raise TimeoutError(f"Timed out waiting for {url}: {last_error}")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def run_local_openapi(config_path: Path) -> None:
    port = free_port()
    env = os.environ.copy()
    env["PROXMOX_MCP_CONFIG"] = str(config_path)
    env["PYTHONPATH"] = str(SRC)
    command = [
        sys.executable,
        "-m",
        "proxmox_mcp.openapi_proxy",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--",
        sys.executable,
        "main.py",
    ]
    proc = subprocess.Popen(  # noqa: S603
        command,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        health = wait_for_http(f"http://127.0.0.1:{port}/health")
        log(f"Local OpenAPI health: {health.text}")
        schema = requests.get(f"http://127.0.0.1:{port}/openapi.json", timeout=10)
        schema.raise_for_status()
        paths = schema.json().get("paths", {})
        if not paths:
            raise RuntimeError("OpenAPI schema did not expose any paths")
        log(f"Local OpenAPI exposed {len(paths)} path(s)")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


def run_docker_openapi(config_path: Path) -> None:
    tag = "proxmox-mcp-plus-live-e2e:latest"
    port = free_port()
    build_cmd = ["docker", "build", "-t", tag, "."]
    run_cmd = [
        "docker",
        "run",
        "--rm",
        "-d",
        "-p",
        f"{port}:8811",
        "-v",
        f"{config_path}:/app/proxmox-config/config.json:ro",
        tag,
    ]
    container_id = ""
    subprocess.run(build_cmd, cwd=ROOT, check=True)
    try:
        container_id = subprocess.check_output(run_cmd, cwd=ROOT, text=True).strip()
        health = wait_for_http(f"http://127.0.0.1:{port}/health")
        log(f"Docker OpenAPI health: {health.text}")
        schema = requests.get(f"http://127.0.0.1:{port}/openapi.json", timeout=10)
        schema.raise_for_status()
        paths = schema.json().get("paths", {})
        if not paths:
            raise RuntimeError("Docker OpenAPI schema did not expose any paths")
        log(f"Docker OpenAPI exposed {len(paths)} path(s)")
    finally:
        if container_id:
            subprocess.run(["docker", "stop", container_id], check=False)


def prepare_live_config(config_path: Path) -> tuple[Path, str | None]:
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    proxmox = raw.get("proxmox", {})
    security = raw.setdefault("security", {})
    if proxmox.get("verify_ssl", True) is False and not security.get("dev_mode", False):
        security["dev_mode"] = True
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        with tmp:
            json.dump(raw, tmp, indent=4)
        return Path(tmp.name), "Enabled security.dev_mode in a temporary test config because verify_ssl=false."
    return config_path, None


def assert_config_is_live_ready(config_path: Path, config: Any) -> None:
    proxmox_host = str(config.proxmox.host)
    if config_path == DEFAULT_CONFIG_PATH and proxmox_host in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError(
            "Refusing to run live e2e against the default proxmox-config/config.json because it still "
            "points at a local-only API target. Use proxmox-config/config.live.json or PROXMOX_MCP_E2E_CONFIG."
        )


def main() -> int:
    from proxmox_mcp.config.loader import load_config
    from proxmox_mcp.core.proxmox import ProxmoxManager
    from proxmox_mcp.server import ProxmoxMCPServer

    source_config_path = resolve_live_config_path()
    if not source_config_path.exists():
        raise FileNotFoundError(f"Config file not found: {source_config_path}")

    config_path, config_note = prepare_live_config(source_config_path)
    try:
        if config_note:
            log(config_note)
        config = load_config(str(config_path))
        assert_config_is_live_ready(source_config_path, config)
        validate_live_connectivity(config)
        api = ProxmoxManager(config.proxmox, config.auth).get_api()
        server = ProxmoxMCPServer(str(config_path))

        log(f"Using config: {config_path}")
        version = api.version.get()
        log(f"Connected to Proxmox version payload: {version}")

        node = choose_online_node(api)
        vm_storage = choose_storage(api, node, "images")
        ct_storage = choose_container_storage(api, node)
        backup_storage = choose_storage(api, node, "backup")
        iso_storage = choose_storage(api, node, "iso")
        template = ensure_template(api, node)

        log(
            "Selected node="
            f"{node}, vm_storage={vm_storage}, ct_storage={ct_storage}, "
            f"backup_storage={backup_storage}, iso_storage={iso_storage}"
        )
        log(f"Selected LXC template: {template}")

        vmid, restore_vmid, ctid = reserve_vmids(api, 3)
        restored_vmids = [restore_vmid]
        snapshot_name = f"codex-snap-{vmid}"
        iso_name = f"codex-live-{int(time.time())}.iso"
        backup_volid: str | None = None

        log(f"Creating VM {vmid}")
        upid = extract_task_id(server.vm_tools.create_vm(node, str(vmid), f"codex-vm-{vmid}", 1, 1024, 8, vm_storage))
        wait_for_task(api, node, upid)
        wait_for_guest_status(lambda: api.nodes(node).qemu(vmid).status.current.get(), "stopped")
        log(f"Disabling KVM acceleration for nested test VM {vmid}")
        api.nodes(node).qemu(vmid).config.post(kvm=0)

        log(f"Starting VM {vmid}")
        upid = extract_task_id(server.vm_tools.start_vm(node, str(vmid)))
        wait_for_task(api, node, upid)
        wait_for_guest_status(lambda: api.nodes(node).qemu(vmid).status.current.get(), "running")

        log(f"Stopping VM {vmid}")
        upid = extract_task_id(server.vm_tools.stop_vm(node, str(vmid)))
        wait_for_task(api, node, upid)
        wait_for_guest_status(lambda: api.nodes(node).qemu(vmid).status.current.get(), "stopped")

        log(f"Creating snapshot {snapshot_name} for VM {vmid}")
        upid = extract_task_id(server.snapshot_tools.create_snapshot(node, str(vmid), snapshot_name, vm_type="qemu"))
        wait_for_task(api, node, upid)

        log(f"Rolling back snapshot {snapshot_name} for VM {vmid}")
        upid = extract_task_id(server.snapshot_tools.rollback_snapshot(node, str(vmid), snapshot_name, vm_type="qemu"))
        wait_for_task(api, node, upid)

        log(f"Creating backup for VM {vmid}")
        upid = extract_task_id(server.backup_tools.create_backup(node, str(vmid), backup_storage))
        wait_for_task(api, node, upid, timeout=1800)
        backup_volid = newest_backup(api, node, backup_storage, vmid)
        log(f"Created backup: {backup_volid}")

        log(f"Restoring VM backup to {restore_vmid}")
        upid = extract_task_id(server.backup_tools.restore_backup(node, backup_volid, str(restore_vmid), storage=vm_storage))
        wait_for_task(api, node, upid, timeout=1800)
        wait_for_guest_status(lambda: api.nodes(node).qemu(restore_vmid).status.current.get(), "stopped")

        log(f"Deleting snapshot {snapshot_name} for VM {vmid}")
        upid = extract_task_id(server.snapshot_tools.delete_snapshot(node, str(vmid), snapshot_name, vm_type="qemu"))
        wait_for_task(api, node, upid)

        log(f"Downloading test ISO {iso_name}")
        upid = extract_task_id(
            server.iso_tools.download_iso(
                node,
                iso_storage,
                "https://raw.githubusercontent.com/github/gitignore/main/Python.gitignore",
                iso_name,
            )
        )
        wait_for_task(api, node, upid, timeout=1800)

        log(f"Deleting test ISO {iso_name}")
        iso_delete = server.iso_tools.delete_iso(node, iso_storage, iso_name)
        iso_text = iso_delete[0].text
        match = TASK_RE.search(iso_text)
        if match:
            wait_for_task(api, node, match.group(1))

        log(f"Creating container {ctid}")
        upid = extract_task_id(
            server.container_tools.create_container(
                node=node,
                vmid=str(ctid),
                ostemplate=template,
                hostname=f"codex-ct-{ctid}",
                storage=ct_storage,
            )
        )
        wait_for_task(api, node, upid, timeout=1800)
        wait_for_guest_status(lambda: api.nodes(node).lxc(ctid).status.current.get(), "stopped")

        log(f"Starting container {ctid}")
        result = server.container_tools.start_container(selector=str(ctid), format_style="json")
        start_json = parse_json_text(result)
        wait_for_task(api, node, extract_task_id_from_item(start_json[0]))
        wait_for_guest_status(lambda: api.nodes(node).lxc(ctid).status.current.get(), "running")

        log(f"Fetching container config and IP for {ctid}")
        parse_json_text(server.container_tools.get_container_config(node, str(ctid)))
        parse_json_text(server.container_tools.get_container_ip(node, str(ctid)))

        if config.ssh is not None:
            log(f"Executing SSH command inside container {ctid}")
            exec_result = parse_json_text(server.container_tools.execute_command(str(ctid), "uname -a"))
            if not exec_result.get("success"):
                raise RuntimeError(f"Container command execution failed: {exec_result}")

            log(f"Updating authorized_keys inside container {ctid}")
            key_result = parse_json_text(server.container_tools.update_container_ssh_keys(node, str(ctid), TEST_KEY))
            if not key_result.get("success"):
                raise RuntimeError(f"Container SSH key update failed: {key_result}")
        else:
            raise RuntimeError("Live SSH execution requested but config.ssh is not configured")

        log(f"Stopping container {ctid}")
        result = server.container_tools.stop_container(selector=str(ctid), format_style="json")
        stop_json = parse_json_text(result)
        wait_for_task(api, node, extract_task_id_from_item(stop_json[0]))
        wait_for_guest_status(lambda: api.nodes(node).lxc(ctid).status.current.get(), "stopped")

        log("Starting local OpenAPI proxy against the live MCP child")
        run_local_openapi(config_path)

        log("Building and running Docker image")
        run_docker_openapi(config_path)

        log("Live end-to-end checks completed successfully")
        return 0
    finally:
        locals_map = locals()

        if "api" in locals_map and "node" in locals_map:
            for guest_vmid in locals_map.get("restored_vmids", []):
                try:
                    api.nodes(node).qemu(guest_vmid).status.stop.post()
                except Exception:
                    pass
                try:
                    upid = api.nodes(node).qemu(guest_vmid).delete()
                    if isinstance(upid, str):
                        wait_for_task(api, node, upid, timeout=900)
                except Exception:
                    pass

            if "vmid" in locals_map:
                try:
                    api.nodes(node).qemu(vmid).status.stop.post()
                except Exception:
                    pass
                try:
                    upid = api.nodes(node).qemu(vmid).delete()
                    if isinstance(upid, str):
                        wait_for_task(api, node, upid, timeout=900)
                except Exception:
                    pass

            if "ctid" in locals_map:
                try:
                    api.nodes(node).lxc(ctid).status.stop.post()
                except Exception:
                    pass
                try:
                    upid = api.nodes(node).lxc(ctid).delete()
                    if isinstance(upid, str):
                        wait_for_task(api, node, upid, timeout=900)
                except Exception:
                    pass

            backup_to_delete = locals_map.get("backup_volid")
            if isinstance(backup_to_delete, str):
                try:
                    server.backup_tools.delete_backup(node, backup_storage, backup_to_delete)
                except Exception:
                    pass

            if "server" in locals_map and "iso_storage" in locals_map and "iso_name" in locals_map:
                try:
                    server.iso_tools.delete_iso(node, iso_storage, iso_name)
                except Exception:
                    pass

        if config_path != source_config_path and config_path.exists():
            config_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
