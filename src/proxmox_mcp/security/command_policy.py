"""Command and operation policy gateway for runtime safety controls."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Pattern

from proxmox_mcp.config.models import CommandPolicyConfig


@dataclass(frozen=True)
class CommandPolicyDecision:
    allowed: bool
    code: str
    message: str


class CommandPolicyGate:
    """Evaluate command and high-risk operation requests against configured policy."""

    def __init__(self, config: CommandPolicyConfig):
        self.config = config
        self.allow_patterns = self._compile_patterns(config.allow_patterns)
        deny_patterns = config.deny_patterns if config.deny_patterns else []
        self.deny_patterns = self._compile_patterns(deny_patterns)

    @staticmethod
    def _compile_patterns(patterns: Iterable[str]) -> list[Pattern[str]]:
        compiled: list[Pattern[str]] = []
        for pattern in patterns:
            compiled.append(re.compile(pattern, flags=re.IGNORECASE))
        return compiled

    @staticmethod
    def _matches_any(command: str, patterns: list[Pattern[str]]) -> bool:
        return any(pattern.search(command) for pattern in patterns)

    def evaluate(self, command: str, approval_token: str | None = None) -> CommandPolicyDecision:
        if not command or not command.strip():
            return CommandPolicyDecision(False, "CMD_POLICY_EMPTY", "Command cannot be empty")

        if self._matches_any(command, self.deny_patterns):
            return CommandPolicyDecision(
                False,
                "CMD_POLICY_DENY_PATTERN",
                "Command blocked by deny policy pattern",
            )

        mode = self.config.mode
        if mode in {"deny_all", "allowlist"} and not self._matches_any(command, self.allow_patterns):
            return CommandPolicyDecision(
                False,
                "CMD_POLICY_NOT_ALLOWLISTED",
                "Command not allowlisted by policy",
            )

        if self.config.require_approval_token:
            if not self.config.approval_token:
                return CommandPolicyDecision(
                    False,
                    "CMD_POLICY_APPROVAL_NOT_CONFIGURED",
                    "Approval token required but not configured on server",
                )
            if approval_token != self.config.approval_token:
                return CommandPolicyDecision(
                    False,
                    "CMD_POLICY_APPROVAL_REQUIRED",
                    "Approval token required for command execution",
                )

        if mode == "audit_only":
            return CommandPolicyDecision(True, "CMD_POLICY_AUDIT_ALLOW", "Allowed (audit-only mode)")

        return CommandPolicyDecision(True, "CMD_POLICY_ALLOW", "Allowed by policy")

    def evaluate_operation(
        self,
        operation_name: str,
        *,
        approval_token: str | None = None,
    ) -> CommandPolicyDecision:
        if not operation_name:
            return CommandPolicyDecision(False, "OP_POLICY_EMPTY", "Operation name cannot be empty")

        if operation_name not in set(self.config.high_risk_operations):
            return CommandPolicyDecision(True, "OP_POLICY_ALLOW", "Operation is not classified as high risk")

        mode = self.config.high_risk_mode
        if mode == "disabled":
            return CommandPolicyDecision(True, "OP_POLICY_DISABLED", "High-risk policy is disabled")

        expected_token = self.config.high_risk_approval_token or self.config.approval_token
        requires_token = self.config.high_risk_require_approval_token
        if requires_token:
            if not expected_token:
                return CommandPolicyDecision(
                    False,
                    "OP_POLICY_APPROVAL_NOT_CONFIGURED",
                    "High-risk approval token required but not configured on server",
                )
            if approval_token != expected_token:
                return CommandPolicyDecision(
                    False,
                    "OP_POLICY_APPROVAL_REQUIRED",
                    f"High-risk operation '{operation_name}' requires an approval token",
                )

        if mode == "audit_only":
            return CommandPolicyDecision(
                True,
                "OP_POLICY_AUDIT_ALLOW",
                f"High-risk operation '{operation_name}' allowed in audit-only mode",
            )

        return CommandPolicyDecision(
            True,
            "OP_POLICY_ALLOW",
            f"High-risk operation '{operation_name}' allowed by policy",
        )
