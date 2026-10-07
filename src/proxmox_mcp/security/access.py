"""Optional per-client authorization, independent of transport authentication."""

from typing import Any
from mcp.server.auth.middleware.auth_context import get_access_token


def client_principal(transport: str) -> str:
    token = get_access_token()
    return token.client_id if token is not None else ("_local" if transport == "STDIO" else "_shared_key")


def permitted_targets(policies: dict[str, Any], principal: str) -> set[str] | None:
    if not policies:
        return None
    policy = policies.get(principal)
    if policy is None:
        return set()
    targets = policy.targets if hasattr(policy, "targets") else policy.get("targets", [])
    return None if "*" in targets else set(targets)


def authorize_client(policies: dict[str, Any], principal: str, tool: str, target: str | None) -> None:
    if not policies:
        return
    policy = policies.get(principal)
    if policy is None:
        raise PermissionError("Client has no configured operation permissions")
    tools = policy.tools if hasattr(policy, "tools") else policy.get("tools", [])
    targets = policy.targets if hasattr(policy, "targets") else policy.get("targets", [])
    if "*" not in tools and tool not in tools:
        raise PermissionError("Client is not authorized for this tool")
    if target is not None and "*" not in targets and target not in targets:
        raise PermissionError("Client is not authorized for this target")
