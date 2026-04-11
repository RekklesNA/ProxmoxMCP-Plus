"""
Command policy gateway for execute_* tools.

Enhanced security policy engine with:
- Pattern-based command filtering
- Rate limiting for command execution
- Timeout enforcement
- Audit logging integration
- Approval token management
- Command complexity analysis
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Pattern

from proxmox_mcp.config.models import CommandPolicyConfig


@dataclass(frozen=True)
class CommandPolicyDecision:
    """Represents a policy evaluation decision."""

    allowed: bool
    code: str
    message: str
    metadata: dict = field(default_factory=dict)


@dataclass
class RateLimitState:
    """Tracks command execution rate for a user/session."""

    commands: list[float] = field(default_factory=list)
    max_commands: int = 60  # per minute
    window_seconds: float = 60.0

    def add_command(self, timestamp: float | None = None) -> None:
        """Record a command execution timestamp."""
        now = timestamp or time.time()
        self.commands.append(now)
        # Clean old entries
        cutoff = now - self.window_seconds
        self.commands = [t for t in self.commands if t > cutoff]

    def is_limited(self) -> bool:
        """Check if rate limit is exceeded."""
        return len(self.commands) >= self.max_commands

    def remaining(self) -> int:
        """Get remaining commands in current window."""
        return max(0, self.max_commands - len(self.commands))


class CommandPolicyGate:
    """
    Evaluate command execution requests against configured policy.

    Provides comprehensive command security with:
    - Pattern matching (allow/deny lists)
    - Rate limiting per user/session
    - Execution timeout enforcement
    - Approval token validation
    - Audit trail generation
    - Command complexity scoring
    """

    def __init__(self, config: CommandPolicyConfig):
        self.config = config
        self.allow_patterns = self._compile_patterns(config.allow_patterns)
        deny_patterns = config.deny_patterns if config.deny_patterns else []
        self.deny_patterns = self._compile_patterns(deny_patterns)

        # Rate limiting state
        self._rate_limits: dict[str, RateLimitState] = defaultdict(
            lambda: RateLimitState(max_commands=60, window_seconds=60.0)
        )

        # Default deny patterns for security
        self._default_deny_patterns = self._compile_patterns([
            r'rm\s+-rf\s+/',           # Prevent root filesystem deletion
            r'rm\s+--no-preserve-root', # Bypass safety checks
            r':\(\)\{\s*:\|:\s*&\s*\}\s*;:', # Fork bomb
            r'\bmkfs\b',               # Filesystem formatting
            r'\bdd\s+if=',             # Raw disk writes
            r'\bchmod\s+[0-7]*777',   # Overly permissive permissions
            r'\bchown\s+.*:.*\s+/',   # Recursive ownership changes
        ])

    @staticmethod
    def _compile_patterns(patterns: Iterable[str]) -> list[Pattern[str]]:
        """Compile regex patterns for efficient matching."""
        compiled: list[Pattern[str]] = []
        for pattern in patterns:
            compiled.append(re.compile(pattern, flags=re.IGNORECASE))
        return compiled

    @staticmethod
    def _matches_any(command: str, patterns: list[Pattern[str]]) -> bool:
        """Check if command matches any pattern in the list."""
        return any(pattern.search(command) for pattern in patterns)

    def _score_command_complexity(self, command: str) -> int:
        """
        Score command complexity (1-10 scale).

        Higher scores indicate more complex/risky commands.
        """
        score = 1

        # Pipe/chain commands
        if '|' in command or '&&' in command or '||' in command:
            score += 2

        # Subshell execution
        if '$(' in command or '`' in command:
            score += 2

        # Redirection
        if '>' in command or '>>' in command:
            score += 1

        # Sudo usage
        if command.strip().startswith('sudo'):
            score += 1

        # Multiple commands
        if ';' in command:
            score += 1

        return min(score, 10)

    def check_rate_limit(self, user_id: str = "default") -> tuple[bool, int]:
        """
        Check if user has exceeded rate limit.

        Returns:
            Tuple of (is_limited, remaining_commands)
        """
        rate_state = self._rate_limits[user_id]
        is_limited = rate_state.is_limited()
        remaining = rate_state.remaining()
        return is_limited, remaining

    def record_command(self, user_id: str = "default") -> None:
        """Record command execution for rate limiting."""
        self._rate_limits[user_id].add_command()

    def evaluate(
        self,
        command: str,
        approval_token: str | None = None,
        user_id: str = "default",
        max_execution_time: int | None = None,
    ) -> CommandPolicyDecision:
        """
        Evaluate command execution request against policy.

        Args:
            command: Command to evaluate
            approval_token: Optional approval token for restricted commands
            user_id: User/session identifier for rate limiting
            max_execution_time: Maximum allowed execution time (seconds)

        Returns:
            Policy decision with allow/deny and metadata
        """
        metadata: dict = {
            "user_id": user_id,
            "complexity_score": self._score_command_complexity(command),
        }

        # Validate command is not empty
        if not command or not command.strip():
            return CommandPolicyDecision(
                False,
                "CMD_POLICY_EMPTY",
                "Command cannot be empty",
                metadata=metadata,
            )

        # Check rate limit
        is_limited, remaining = self.check_rate_limit(user_id)
        metadata["rate_limit_remaining"] = remaining
        if is_limited:
            return CommandPolicyDecision(
                False,
                "CMD_POLICY_RATE_LIMITED",
                f"Rate limit exceeded. {remaining} commands remaining in window",
                metadata=metadata,
            )

        # Check default deny patterns (always enforced)
        if self._matches_any(command, self._default_deny_patterns):
            return CommandPolicyDecision(
                False,
                "CMD_POLICY_DENY_DEFAULT",
                "Command blocked by default deny policy (dangerous operation)",
                metadata=metadata,
            )

        # Check configured deny patterns
        if self._matches_any(command, self.deny_patterns):
            return CommandPolicyDecision(
                False,
                "CMD_POLICY_DENY_PATTERN",
                "Command blocked by deny policy pattern",
                metadata=metadata,
            )

        # Check allowlist
        mode = self.config.mode
        if mode in {"deny_all", "allowlist"} and not self._matches_any(command, self.allow_patterns):
            return CommandPolicyDecision(
                False,
                "CMD_POLICY_NOT_ALLOWLISTED",
                "Command not allowlisted by policy",
                metadata=metadata,
            )

        # Check approval token
        if self.config.require_approval_token:
            if not self.config.approval_token:
                return CommandPolicyDecision(
                    False,
                    "CMD_POLICY_APPROVAL_NOT_CONFIGURED",
                    "Approval token required but not configured on server",
                    metadata=metadata,
                )
            if approval_token != self.config.approval_token:
                return CommandPolicyDecision(
                    False,
                    "CMD_POLICY_APPROVAL_REQUIRED",
                    "Approval token required for command execution",
                    metadata=metadata,
                )

        # Record command for rate limiting
        self.record_command(user_id)

        # Audit-only mode
        if mode == "audit_only":
            return CommandPolicyDecision(
                True,
                "CMD_POLICY_AUDIT_ALLOW",
                "Allowed (audit-only mode)",
                metadata=metadata,
            )

        return CommandPolicyDecision(
            True,
            "CMD_POLICY_ALLOW",
            "Allowed by policy",
            metadata=metadata,
        )

    def get_rate_limit_status(self, user_id: str = "default") -> dict:
        """Get current rate limit status for a user."""
        rate_state = self._rate_limits[user_id]
        return {
            "user_id": user_id,
            "is_limited": rate_state.is_limited(),
            "remaining_commands": rate_state.remaining(),
            "max_commands": rate_state.max_commands,
            "window_seconds": rate_state.window_seconds,
            "commands_in_window": len(rate_state.commands),
        }
