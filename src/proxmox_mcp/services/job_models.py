"""Persisted job records and outbound sanitization contracts."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from proxmox_mcp.security.sanitization import is_secret_key, sanitize_string, sanitize_value

def _is_secret_key(key: str) -> bool:
    return is_secret_key(key)


def _sanitize_string(text: str) -> str:
    return sanitize_string(text)


def _sanitize(value: Any) -> Any:
    """Outbound-only sanitization — redacts secrets for API responses/logs.
    Uses regex sweeps so innocent URLs are not re-encoded or corrupted.
    Persisted retry_spec is handled separately (see register_task)."""
    return sanitize_value(value)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobNotFoundError(ValueError):
    """Raised when a job_id does not exist."""


class JobConflictError(ValueError):
    """Raised when a requested job operation is not currently valid."""


@dataclass
class JobAuditEvent:
    timestamp: str
    event: str
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "event": self.event,
            "details": _sanitize(self.details),
        }


@dataclass
class JobRecord:
    job_id: str
    tool_name: str
    summary: str
    node: Optional[str]
    upid: Optional[str]
    created_at: str
    updated_at: str
    status: str = "running"
    progress: Optional[int] = None
    attempts: int = 1
    retry_count: int = 0
    last_error: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    previous_upids: list[str] = field(default_factory=list)
    audit_log: list[JobAuditEvent] = field(default_factory=list)
    retry_spec: Optional[dict[str, Any]] = None
    retry_spec_redacted: bool = False
    _persisted_audit_count: int = field(default=0, repr=False)
    retry_factory: Optional[Callable[[], Any]] = field(default=None, repr=False)
    cancel_factory: Optional[Callable[[str], Any]] = field(default=None, repr=False)

    def add_audit(self, event: str, **details: Any) -> None:
        self.audit_log.append(JobAuditEvent(timestamp=_utcnow(), event=event, details=details))
        self.updated_at = _utcnow()

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "tool_name": self.tool_name,
            "summary": self.summary,
            "node": self.node,
            "upid": self.upid,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "progress": self.progress,
            "attempts": self.attempts,
            "retry_count": self.retry_count,
            "last_error": _sanitize(self.last_error),
            "result": _sanitize(self.result),
            "metadata": _sanitize(self.metadata),
            "previous_upids": self.previous_upids,
            "audit_log": [item.as_dict() for item in self.audit_log],
            "retry_spec": _sanitize(self.retry_spec),
            "retry_spec_redacted": self.retry_spec_redacted,
        }


