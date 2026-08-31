"""Named Proxmox target resolution and safe discovery metadata."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from proxmox_mcp.config.models import Config, ProxmoxConfig, AuthConfig, TargetConfig


@dataclass(frozen=True)
class ResolvedTarget:
    name: str
    config: ProxmoxConfig
    auth: AuthConfig
    kind: str
    readonly: bool
    api_tunnel: Any | None = None
    ssh: Any | None = None
    command_policy: Any | None = None


class TargetRegistry:
    """Resolve legacy or named target configuration without guessing."""

    def __init__(self, config: Config):
        self.is_legacy = config.targets is None
        if config.targets is not None and (config.proxmox is not None or config.auth is not None):
            raise ValueError("Use either legacy proxmox/auth configuration or targets, not both")
        if not self.is_legacy:
            if not config.targets:
                raise ValueError("At least one Proxmox target must be configured")
            self._targets = {
                name: self._from_named(name, target)
                for name, target in config.targets.items()
            }
        elif config.proxmox is not None and config.auth is not None:
            self._targets = {"default": ResolvedTarget(
                name="default", config=config.proxmox, auth=config.auth,
                kind="standalone", readonly=False,
                api_tunnel=config.api_tunnel, ssh=config.ssh,
                command_policy=config.command_policy,
            )}
        else:
            raise ValueError("Proxmox configuration requires either targets or proxmox/auth")

    @staticmethod
    def _from_named(name: str, target: TargetConfig) -> ResolvedTarget:
        if not name.strip():
            raise ValueError("Proxmox target names cannot be empty")
        proxmox = ProxmoxConfig(
            host=target.host, port=target.port, timeout=target.timeout,
            verify_ssl=target.verify_ssl, service=target.service,
        )
        return ResolvedTarget(
            name=name, config=proxmox, auth=target.auth, kind=target.kind,
            readonly=target.readonly, api_tunnel=target.api_tunnel,
            ssh=target.ssh, command_policy=target.command_policy,
        )

    def resolve(self, requested: str | None = None) -> ResolvedTarget:
        if requested is not None:
            try:
                return self._targets[requested]
            except KeyError as exc:
                available = ", ".join(sorted(self._targets))
                raise ValueError(f"Unknown Proxmox target {requested!r}; available targets: {available}") from exc
        if len(self._targets) == 1:
            return next(iter(self._targets.values()))
        available = ", ".join(sorted(self._targets))
        raise ValueError(f"Multiple Proxmox targets are configured; specify target: {available}")

    def describe(
        self,
        discover: Callable[[ResolvedTarget], dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        descriptions = []
        for target in sorted(self._targets.values(), key=lambda item: item.name):
            item = {
                "name": target.name,
                "kind": target.kind,
                "host": target.config.host,
                "port": target.config.port,
                "readonly": target.readonly,
            }
            if discover is not None:
                try:
                    discovery = discover(target)
                    item.update({
                        "reachable": bool(discovery.get("reachable", False)),
                        "nodes": list(discovery.get("nodes", [])),
                    })
                except Exception:
                    item.update({
                        "reachable": False,
                        "nodes": [],
                        "error": f"Unable to reach target '{target.name}'",
                    })
            descriptions.append(item)
        return descriptions

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._targets))
