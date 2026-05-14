"""Tests for the command and high-risk operation policy gateway."""

from __future__ import annotations

from typing import Any

import pytest

from proxmox_mcp.config.models import CommandPolicyConfig
from proxmox_mcp.security.command_policy import CommandPolicyGate


def _gate(**overrides: Any) -> CommandPolicyGate:
    return CommandPolicyGate(CommandPolicyConfig(**overrides))


def test_command_approval_token_match_allows():
    gate = _gate(
        mode="audit_only",
        require_approval_token=True,
        approval_token="s3cret-token",
    )

    decision = gate.evaluate("uname -a", approval_token="s3cret-token")

    assert decision.allowed is True


@pytest.mark.parametrize(
    "supplied",
    [
        None,
        "",
        "wrong",
        "s3cret-toke",   # prefix
        "s3cret-token!", # suffix
    ],
)
def test_command_approval_token_mismatch_denies(supplied):
    gate = _gate(
        mode="audit_only",
        require_approval_token=True,
        approval_token="s3cret-token",
    )

    decision = gate.evaluate("uname -a", approval_token=supplied)

    assert decision.allowed is False
    assert decision.code == "CMD_POLICY_APPROVAL_REQUIRED"


def test_command_approval_token_not_configured_denies():
    gate = _gate(
        mode="audit_only",
        require_approval_token=True,
        approval_token=None,
    )

    decision = gate.evaluate("uname -a", approval_token="anything")

    assert decision.allowed is False
    assert decision.code == "CMD_POLICY_APPROVAL_NOT_CONFIGURED"


def test_high_risk_operation_token_match_allows():
    gate = _gate(
        high_risk_mode="enforce",
        high_risk_require_approval_token=True,
        high_risk_approval_token="approve-me",
    )

    decision = gate.evaluate_operation("delete_vm", approval_token="approve-me")

    assert decision.allowed is True


@pytest.mark.parametrize(
    "supplied",
    [
        None,
        "",
        "wrong",
        "approve-m",
        "approve-me ",
    ],
)
def test_high_risk_operation_token_mismatch_denies(supplied):
    gate = _gate(
        high_risk_mode="enforce",
        high_risk_require_approval_token=True,
        high_risk_approval_token="approve-me",
    )

    decision = gate.evaluate_operation("delete_vm", approval_token=supplied)

    assert decision.allowed is False
    assert decision.code == "OP_POLICY_APPROVAL_REQUIRED"


def test_high_risk_operation_falls_back_to_command_token():
    """When high_risk_approval_token is None, the command-level approval_token applies."""
    gate = _gate(
        high_risk_mode="enforce",
        approval_token="cmd-token",
        high_risk_require_approval_token=True,
        high_risk_approval_token=None,
    )

    assert gate.evaluate_operation("delete_vm", approval_token="cmd-token").allowed is True
    assert gate.evaluate_operation("delete_vm", approval_token="other").allowed is False
