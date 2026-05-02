"""Persistent job orchestration for long-running Proxmox tasks."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional


_PROGRESS_RE = re.compile(r"(?P<value>\d{1,3})%")


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
            "details": self.details,
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
            "status": self.status,
            "progress": self.progress,
            "attempts": self.attempts,
            "retry_count": self.retry_count,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "result": self.result,
            "metadata": self.metadata,
            "previous_upids": self.previous_upids,
            "audit_log": [item.as_dict() for item in self.audit_log],
            "retry_spec": self.retry_spec,
        }


class JobStore:
    """Tracks long-running Proxmox tasks behind stable job IDs."""

    def __init__(self, proxmox_api: Any, sqlite_path: str = "proxmox-jobs.sqlite3") -> None:
        self.proxmox = proxmox_api
        self.sqlite_path = str(Path(sqlite_path).expanduser())
        Path(self.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, JobRecord] = {}
        self._lock = threading.RLock()
        self._retry_handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}
        self._conn = sqlite3.connect(self.sqlite_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()
        self._register_builtin_retry_handlers()
        self._load_records()

    def register_retry_handler(self, kind: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        self._retry_handlers[kind] = handler

    def register_task(
        self,
        *,
        tool_name: str,
        summary: str,
        node: Optional[str],
        upid: Optional[str],
        metadata: Optional[dict[str, Any]] = None,
        retry_spec: Optional[dict[str, Any]] = None,
        retry_factory: Optional[Callable[[], Any]] = None,
        cancel_factory: Optional[Callable[[str], Any]] = None,
    ) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        now = _utcnow()
        record = JobRecord(
            job_id=job_id,
            tool_name=tool_name,
            summary=summary,
            node=node,
            upid=str(upid) if upid is not None else None,
            created_at=now,
            updated_at=now,
            metadata=dict(metadata or {}),
            retry_spec=dict(retry_spec) if retry_spec else None,
            retry_factory=retry_factory,
            cancel_factory=cancel_factory,
        )
        record.add_audit("created", upid=upid, metadata=record.metadata)
        with self._lock:
            self._jobs[job_id] = record
            self._save_record(record)
        return record.as_dict()

    def list_jobs(
        self,
        *,
        status: Optional[str] = None,
        tool_name: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._lock:
            self._refresh_records_from_db()
            rows = list(self._jobs.values())
        rows.sort(key=lambda item: item.created_at, reverse=True)
        filtered: list[JobRecord] = []
        for item in rows:
            if status and item.status != status:
                continue
            if tool_name and item.tool_name != tool_name:
                continue
            filtered.append(item)
        return [item.as_dict() for item in filtered[:limit]]

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            self._refresh_records_from_db()
            return self._get_record(job_id).as_dict()

    def poll_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            self._refresh_records_from_db()
            record = self._get_record(job_id)
            if not record.upid or not record.node:
                record.add_audit("poll_skipped", reason="missing_upid_or_node")
                self._save_record(record)
                return record.as_dict()
            upid = record.upid
            node = record.node

        status_payload = self.proxmox.nodes(node).tasks(upid).status.get()
        log_payload = self.proxmox.nodes(node).tasks(upid).log.get()
        progress = self._extract_progress(log_payload)
        status, last_error, completed_at = self._normalize_status(status_payload)

        with self._lock:
            self._refresh_records_from_db()
            record = self._get_record(job_id)
            record.progress = progress
            record.status = status
            record.last_error = last_error
            record.completed_at = completed_at
            record.result = status_payload if isinstance(status_payload, dict) else {"raw": status_payload}
            record.add_audit(
                "polled",
                status=status,
                progress=progress,
                exitstatus=record.result.get("exitstatus") if record.result else None,
            )
            self._save_record(record)
            return record.as_dict()

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            self._refresh_records_from_db()
            record = self._get_record(job_id)
            if not record.upid or not record.node:
                raise JobConflictError(f"Job {job_id} has no task UPID to cancel")
            upid = record.upid
            node = record.node
            cancel_factory = record.cancel_factory

        if cancel_factory is not None:
            cancel_factory(upid)
        else:
            self.proxmox.nodes(node).tasks(upid).status.stop.post()

        with self._lock:
            self._refresh_records_from_db()
            record = self._get_record(job_id)
            record.status = "cancel_requested"
            record.add_audit("cancel_requested", upid=upid)
            self._save_record(record)
            return record.as_dict()

    def retry_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            self._refresh_records_from_db()
            record = self._get_record(job_id)
            retry_factory = record.retry_factory
            retry_spec = dict(record.retry_spec or {})

        if retry_factory is not None:
            new_upid = retry_factory()
        else:
            if not retry_spec:
                raise JobConflictError(f"Job {job_id} does not support retry")
            kind = str(retry_spec.get("kind", "") or "")
            params = retry_spec.get("params")
            if not kind or not isinstance(params, dict):
                raise JobConflictError(f"Job {job_id} has an invalid retry recipe")
            handler = self._retry_handlers.get(kind)
            if handler is None:
                raise JobConflictError(f"Retry handler '{kind}' is not available")
            new_upid = handler(params)

        with self._lock:
            self._refresh_records_from_db()
            record = self._get_record(job_id)
            if record.upid:
                record.previous_upids.append(record.upid)
            record.upid = str(new_upid)
            record.status = "running"
            record.progress = 0
            record.last_error = None
            record.completed_at = None
            record.result = None
            record.attempts += 1
            record.retry_count += 1
            record.add_audit("retried", new_upid=record.upid)
            self._save_record(record)
            return record.as_dict()

    def _get_record(self, job_id: str) -> JobRecord:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise JobNotFoundError(f"Unknown job_id: {job_id}") from exc

    def _init_db(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                tool_name TEXT NOT NULL,
                summary TEXT NOT NULL,
                node TEXT,
                upid TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER,
                attempts INTEGER NOT NULL,
                retry_count INTEGER NOT NULL,
                last_error TEXT,
                completed_at TEXT,
                result_json TEXT,
                metadata_json TEXT NOT NULL,
                previous_upids_json TEXT NOT NULL,
                audit_log_json TEXT NOT NULL,
                retry_spec_json TEXT
            )
            """
        )
        self._conn.commit()

    def _load_records(self) -> None:
        with self._lock:
            self._refresh_records_from_db()

    def _refresh_records_from_db(self) -> None:
        rows = self._conn.execute("SELECT * FROM jobs").fetchall()
        refreshed: dict[str, JobRecord] = {}
        for row in rows:
            job_id = str(row["job_id"])
            existing = self._jobs.get(job_id)
            record = JobRecord(
                job_id=job_id,
                tool_name=str(row["tool_name"]),
                summary=str(row["summary"]),
                node=row["node"],
                upid=row["upid"],
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
                status=str(row["status"]),
                progress=row["progress"],
                attempts=int(row["attempts"]),
                retry_count=int(row["retry_count"]),
                last_error=row["last_error"],
                completed_at=row["completed_at"],
                result=json.loads(row["result_json"]) if row["result_json"] else None,
                metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
                previous_upids=json.loads(row["previous_upids_json"]) if row["previous_upids_json"] else [],
                audit_log=[
                    JobAuditEvent(
                        timestamp=item["timestamp"],
                        event=item["event"],
                        details=item.get("details", {}),
                    )
                    for item in (json.loads(row["audit_log_json"]) if row["audit_log_json"] else [])
                ],
                retry_spec=json.loads(row["retry_spec_json"]) if row["retry_spec_json"] else None,
                retry_factory=existing.retry_factory if existing is not None else None,
                cancel_factory=existing.cancel_factory if existing is not None else None,
            )
            refreshed[record.job_id] = record
        self._jobs = refreshed

    def _save_record(self, record: JobRecord) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO jobs (
                job_id, tool_name, summary, node, upid, created_at, updated_at, status,
                progress, attempts, retry_count, last_error, completed_at, result_json,
                metadata_json, previous_upids_json, audit_log_json, retry_spec_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.job_id,
                record.tool_name,
                record.summary,
                record.node,
                record.upid,
                record.created_at,
                record.updated_at,
                record.status,
                record.progress,
                record.attempts,
                record.retry_count,
                record.last_error,
                record.completed_at,
                json.dumps(record.result, sort_keys=True) if record.result is not None else None,
                json.dumps(record.metadata, sort_keys=True),
                json.dumps(record.previous_upids),
                json.dumps([item.as_dict() for item in record.audit_log]),
                json.dumps(record.retry_spec, sort_keys=True) if record.retry_spec is not None else None,
            ),
        )
        self._conn.commit()

    def _extract_progress(self, log_payload: Any) -> Optional[int]:
        max_progress: Optional[int] = None
        if not isinstance(log_payload, list):
            return None
        for item in log_payload:
            text = ""
            if isinstance(item, dict):
                text = str(item.get("t", "") or item.get("msg", "") or "")
            else:
                text = str(item)
            for match in _PROGRESS_RE.finditer(text):
                value = int(match.group("value"))
                if value > 100:
                    continue
                max_progress = value if max_progress is None else max(max_progress, value)
        return max_progress

    def _normalize_status(self, status_payload: Any) -> tuple[str, Optional[str], Optional[str]]:
        now = _utcnow()
        if not isinstance(status_payload, dict):
            return "unknown", None, None

        state = str(status_payload.get("status", "") or "").lower()
        exit_status = str(status_payload.get("exitstatus", "") or "")
        if exit_status == "OK":
            return "completed", None, now
        if exit_status:
            return "failed", exit_status, now
        if state in {"stopped", "stop"}:
            return "cancelled", None, now
        if state in {"running", "queued"}:
            return "running", None, None
        if state in {"error", "failed"}:
            return "failed", state, now
        return "running", None, None

    def _register_builtin_retry_handlers(self) -> None:
        self.register_retry_handler("vm.create", lambda params: self.proxmox.nodes(params["node"]).qemu.create(**params["vm_config"]))
        self.register_retry_handler("vm.start", lambda params: self.proxmox.nodes(params["node"]).qemu(params["vmid"]).status.start.post())
        self.register_retry_handler("vm.stop", lambda params: self.proxmox.nodes(params["node"]).qemu(params["vmid"]).status.stop.post())
        self.register_retry_handler("vm.shutdown", lambda params: self.proxmox.nodes(params["node"]).qemu(params["vmid"]).status.shutdown.post())
        self.register_retry_handler("vm.reset", lambda params: self.proxmox.nodes(params["node"]).qemu(params["vmid"]).status.reset.post())
        self.register_retry_handler("vm.delete", lambda params: self.proxmox.nodes(params["node"]).qemu(params["vmid"]).delete())
        self.register_retry_handler("ct.start", lambda params: self.proxmox.nodes(params["node"]).lxc(params["vmid"]).status.start.post())
        self.register_retry_handler(
            "ct.stop",
            lambda params: (
                self.proxmox.nodes(params["node"]).lxc(params["vmid"]).status.shutdown.post(timeout=params.get("timeout_seconds", 10))
                if params.get("graceful", True)
                else self.proxmox.nodes(params["node"]).lxc(params["vmid"]).status.stop.post()
            ),
        )
        self.register_retry_handler("ct.restart", lambda params: self.proxmox.nodes(params["node"]).lxc(params["vmid"]).status.reboot.post())
        self.register_retry_handler("ct.create", lambda params: self.proxmox.nodes(params["node"]).lxc.create(**params["ct_config"]))
        self.register_retry_handler("ct.delete", lambda params: self.proxmox.nodes(params["node"]).lxc(params["vmid"]).delete())
        self.register_retry_handler(
            "snapshot.create",
            lambda params: (
                self.proxmox.nodes(params["node"]).lxc(params["vmid"]).snapshot.post(**params["request"])
                if params["vm_type"] == "lxc"
                else self.proxmox.nodes(params["node"]).qemu(params["vmid"]).snapshot.post(**params["request"])
            ),
        )
        self.register_retry_handler(
            "snapshot.delete",
            lambda params: (
                self.proxmox.nodes(params["node"]).lxc(params["vmid"]).snapshot(params["snapname"]).delete()
                if params["vm_type"] == "lxc"
                else self.proxmox.nodes(params["node"]).qemu(params["vmid"]).snapshot(params["snapname"]).delete()
            ),
        )
        self.register_retry_handler(
            "snapshot.rollback",
            lambda params: (
                self.proxmox.nodes(params["node"]).lxc(params["vmid"]).snapshot(params["snapname"]).rollback.post()
                if params["vm_type"] == "lxc"
                else self.proxmox.nodes(params["node"]).qemu(params["vmid"]).snapshot(params["snapname"]).rollback.post()
            ),
        )
        self.register_retry_handler("backup.create", lambda params: self.proxmox.nodes(params["node"]).vzdump.post(**params["request"]))
        self.register_retry_handler(
            "backup.restore",
            lambda params: (
                self.proxmox.nodes(params["node"]).lxc.post(**params["request"])
                if params.get("is_lxc")
                else self.proxmox.nodes(params["node"]).qemu.post(**params["request"])
            ),
        )
        self.register_retry_handler(
            "backup.delete",
            lambda params: self.proxmox.nodes(params["node"]).storage(params["storage"]).content(params["volid"]).delete(),
        )
        self.register_retry_handler(
            "iso.download",
            lambda params: self.proxmox.nodes(params["node"]).storage(params["storage"])("download-url").post(**params["request"]),
        )
        self.register_retry_handler(
            "iso.delete",
            lambda params: self.proxmox.nodes(params["node"]).storage(params["storage"]).content(params["volid"]).delete(),
        )
