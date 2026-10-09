"""Persistent job orchestration for long-running Proxmox tasks."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
import weakref
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from requests.exceptions import ConnectionError as RequestConnectionError, Timeout as RequestTimeout
from proxmox_mcp.security.resources import delete_volume, validate_segment, submit_snapshot_rollback
from .job_models import (
    JobRecord as JobRecord, JobAuditEvent as JobAuditEvent,
    JobConflictError as JobConflictError, JobNotFoundError as JobNotFoundError,
    _sanitize as _sanitize, _utcnow as _utcnow,
    _is_secret_key as _is_secret_key, _sanitize_string as _sanitize_string,
)
from .job_persistence import JobPersistence
from .job_polling import PollCoordinator

_PROGRESS_RE = re.compile(r"(?P<value>\d{1,3})%")
_RETRYABLE_STATUSES = {"failed", "cancelled"}
_RETRYING_STATUS = "retrying"
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def target_job_sqlite_path(base_path: str, target_name: str) -> str:
    """Derive the per-target database path shared by MCP and OpenAPI."""
    base = Path(base_path)
    return str(base.with_name(f"{base.name}.target-{target_name}"))


class JobStore(JobPersistence):
    """Tracks long-running Proxmox tasks behind stable job IDs."""

    def __init__(self, proxmox_api: Any, sqlite_path: str = "proxmox-jobs.sqlite3", target_name: str | None = None, legacy_mode: bool = False, audit_retention_days: int | None = None, poll_cache_ttl: float = 0.0) -> None:
        if audit_retention_days is not None and audit_retention_days < 1:
            raise ValueError("audit_retention_days must be positive")
        if not 0 <= poll_cache_ttl <= 60:
            raise ValueError('poll_cache_ttl must be between 0 and 60 seconds')
        self._polling = PollCoordinator(poll_cache_ttl)
        self.audit_retention_days = audit_retention_days
        self.proxmox = proxmox_api
        self.target_name = target_name
        # Legacy mode: a single unambiguous target owns the whole database, so
        # jobs written before target metadata existed must stay reachable.
        self.legacy_mode = legacy_mode
        self.sqlite_path = str(Path(sqlite_path).expanduser())
        Path(self.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, JobRecord] = {}
        self._lock = threading.RLock()
        self._retry_handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}
        self.retry_lease_seconds = 300
        self._conn = sqlite3.connect(self.sqlite_path, check_same_thread=False, timeout=30.0)
        self._finalizer = weakref.finalize(self, self._conn.close)
        self._conn.row_factory = sqlite3.Row
        try:
            self._configure_connection()
            self._init_db()
            if self.audit_retention_days is not None:
                self.prune_audit_events()
            self._register_builtin_retry_handlers()
            self._load_records()
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        with self._lock:
            self._finalizer()

    def __enter__(self) -> "JobStore":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def register_retry_handler(self, kind: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        self._retry_handlers[kind] = handler

    def prune_audit_events(self) -> None:
        """Prune expired history only for jobs owned by this target."""
        if self.audit_retention_days is None:
            return
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.audit_retention_days)).isoformat()
        with self._write_transaction():
            where = ""
            params: list[Any] = [cutoff]
            if self.target_name is not None:
                target_filter = "json_extract(metadata_json, '$.target') = ?"
                if self.legacy_mode:
                    target_filter += " OR json_extract(metadata_json, '$.target') IS NULL"
                where = f" AND job_id IN (SELECT job_id FROM jobs WHERE {target_filter})"
                params.append(self.target_name)
            self._conn.execute(
                "DELETE FROM job_audit_events WHERE timestamp < ?" + where, params,
            )

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
        job_metadata = dict(metadata or {})
        if self.target_name is not None:
            job_metadata["target"] = self.target_name
        record = JobRecord(
            job_id=job_id,
            tool_name=tool_name,
            summary=summary,
            node=node,
            upid=str(upid) if upid is not None else None,
            created_at=now,
            updated_at=now,
            metadata=job_metadata,
            retry_spec=_sanitize(retry_spec) if retry_spec else None,
            retry_spec_redacted=bool(retry_spec and _sanitize(retry_spec) != retry_spec),
            retry_factory=retry_factory,
            cancel_factory=cancel_factory,
        )
        record.add_audit("created", upid=upid, metadata=record.metadata)
        with self._write_transaction():
            self._jobs[job_id] = record
            self._save_record(record)
        return record.as_dict()

    def list_jobs(
        self,
        *,
        status: Optional[str] = None,
        tool_name: Optional[str] = None,
        limit: int = 100,
        include_audit: bool = False,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._query_records(status=status, tool_name=tool_name, limit=limit, include_audit=include_audit)
            return [item.as_dict() for item in rows]

    def get_audit(self, job_id: str, *, after_id: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        """Return a bounded, target-checked audit page with stable cursors."""
        with self._lock:
            row = self._conn.execute("SELECT metadata_json FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None or not self._target_matches(json.loads(row[0]).get("target")):
                raise JobNotFoundError("Unknown job_id")
            rows = self._conn.execute("SELECT id,timestamp,event,details_json FROM job_audit_events WHERE job_id = ? AND id > ? ORDER BY id LIMIT ?",
                                      (job_id, max(0, after_id), max(1, min(limit, 500)))).fetchall()
            return [{"id": row["id"], "timestamp": row["timestamp"], "event": row["event"], "details": _sanitize(json.loads(row["details_json"]))} for row in rows]

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._write_transaction():
            return self._load_record_from_db(job_id).as_dict()

    def reconcile_job(self, job_id: str, *, upid: str | None = None, confirmed_not_submitted: bool = False) -> dict[str, Any]:
        """Resolve an uncertain submission only with explicit operator evidence."""
        if bool(upid) == confirmed_not_submitted:
            raise ValueError("Provide either a verified UPID or confirmation that no task was submitted")
        with self._write_transaction():
            record = self._load_record_from_db(job_id)
            if record.status != "needs_reconciliation":
                raise JobConflictError("Only uncertain retries may be reconciled")
            if upid:
                validate_segment(upid)
                if not upid.startswith("UPID:" + str(record.node) + ":"):
                    raise ValueError("UPID must belong to the original node")
                record.previous_upids.append(record.upid or "")
                record.upid = upid
                record.status = "running"
                record.attempts += 1
                record.retry_count += 1
            else:
                record.status = "failed"
            record.metadata.pop("retry_lease_expires", None)
            record.add_audit("retry_reconciled", upid=upid, confirmed_not_submitted=confirmed_not_submitted)
            self._save_record(record)
            return record.as_dict()

    def poll_job(self, job_id: str, *, include_audit: bool = True, force: bool = False) -> dict[str, Any]:
        with self._polling.serialize(job_id):
            return self._poll_job(job_id, include_audit=include_audit, force=force)

    def _poll_job(self, job_id: str, *, include_audit: bool, force: bool) -> dict[str, Any]:
        with self._write_transaction():
            record = self._load_record_from_db(job_id, include_audit=include_audit)
            if record.status in {_RETRYING_STATUS, "needs_reconciliation"}:
                return record.as_dict()
            if not force and (self._polling.fresh(record) or (record.status in _TERMINAL_STATUSES and record.result is not None)):
                return record.as_dict()
            if not record.upid or not record.node:
                record.add_audit("poll_skipped", reason="missing_upid_or_node")
                self._save_record(record)
                return record.as_dict()
            upid = record.upid
            node = record.node
            observed_updated_at = record.updated_at

        status_payload = self.proxmox.nodes(node).tasks(upid).status.get()
        log_payload = self.proxmox.nodes(node).tasks(upid).log.get()
        progress = self._extract_progress(log_payload)
        status, last_error, completed_at = self._normalize_status(status_payload)

        with self._write_transaction():
            record = self._load_record_from_db(job_id, include_audit=include_audit)
            if (record.upid != upid or record.status in {_RETRYING_STATUS, "needs_reconciliation"}
                    or (record.status in _TERMINAL_STATUSES and record.updated_at != observed_updated_at)):
                record.add_audit("poll_discarded", stale_upid=upid, current_upid=record.upid)
                self._save_record(record)
                return record.as_dict()
            if record.status == "cancel_requested" and status == "running":
                status = "cancel_requested"
            record.progress = progress
            record.status = status
            record.last_error = last_error
            record.completed_at = record.completed_at or completed_at
            record.result = status_payload if isinstance(status_payload, dict) else {"raw": status_payload}
            record.add_audit(
                "polled",
                status=status,
                progress=progress,
                exitstatus=record.result.get("exitstatus") if record.result else None,
            )
            self._save_record(record)
            self._polling.remember(record)
            return record.as_dict()

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        with self._write_transaction():
            record = self._load_record_from_db(job_id)
            if not record.upid or not record.node:
                raise JobConflictError(f"Job {job_id} has no task UPID to cancel")
            if record.status in _TERMINAL_STATUSES or record.status in {_RETRYING_STATUS, "needs_reconciliation"}:
                raise JobConflictError(f"Job {job_id} cannot be cancelled while status is '{record.status}'")
            upid = record.upid
            node = record.node
            cancel_factory = record.cancel_factory

        if cancel_factory is not None:
            cancel_factory(upid)
        else:
            self.proxmox.nodes(node).tasks(upid).delete()

        with self._write_transaction():
            record = self._load_record_from_db(job_id)
            if record.upid != upid:
                record.add_audit("cancel_discarded", stale_upid=upid, current_upid=record.upid)
                self._save_record(record)
                return record.as_dict()
            if record.status in _TERMINAL_STATUSES or record.status in {_RETRYING_STATUS, "needs_reconciliation"}:
                record.add_audit("cancel_discarded", upid=upid, current_status=record.status)
                self._save_record(record)
                return record.as_dict()
            record.status = "cancel_requested"
            record.add_audit("cancel_requested", upid=upid)
            self._save_record(record)
            return record.as_dict()

    def retry_job(self, job_id: str) -> dict[str, Any]:
        with self._write_transaction():
            record = self._load_record_from_db(job_id)
            if record.retry_spec_redacted and record.retry_factory is None:
                raise JobConflictError(f"Job {job_id} retry recipe was redacted and cannot be retried")
            if record.status not in _RETRYABLE_STATUSES:
                raise JobConflictError(
                    f"Job {job_id} cannot be retried while status is '{record.status}'. "
                    "Poll the job first and retry only failed or cancelled jobs."
                )
            retry_factory = record.retry_factory
            retry_spec = dict(record.retry_spec or {})
            kind = ""
            params: dict[str, Any] | None = None
            handler: Callable[[dict[str, Any]], Any] | None = None
            if retry_factory is None:
                if not retry_spec:
                    raise JobConflictError(f"Job {job_id} does not support retry")
                kind = str(retry_spec.get("kind", "") or "")
                retry_params = retry_spec.get("params")
                if not kind or not isinstance(retry_params, dict):
                    raise JobConflictError(f"Job {job_id} has an invalid retry recipe")
                params = retry_params
                handler = self._retry_handlers.get(kind)
                if handler is None:
                    raise JobConflictError(f"Retry handler '{kind}' is not available")
            previous_status = record.status
            original_upid = record.upid
            self._claim_retry(record)

        try:
            if retry_factory is not None:
                new_upid = retry_factory()
            else:
                assert handler is not None and params is not None
                new_upid = handler(params)
        except (TimeoutError, ConnectionError, RequestConnectionError, RequestTimeout):
            self._mark_retry_uncertain(job_id, original_upid)
            raise
        except Exception as exc:
            self._rollback_retry_claim(job_id, original_upid, previous_status, exc)
            raise
        except BaseException:
            self._mark_retry_uncertain(job_id, original_upid)
            raise

        with self._write_transaction():
            record = self._load_record_from_db(job_id)
            conflict = record.status != _RETRYING_STATUS or record.upid != original_upid
            if conflict:
                record.add_audit(
                    "retry_result_discarded",
                    stale_upid=original_upid,
                    current_upid=record.upid,
                    current_status=record.status,
                    new_upid=str(new_upid),
                )
                self._save_record(record)
            else:
                if original_upid:
                    record.previous_upids.append(original_upid)
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
                result = record.as_dict()
        if conflict:
            raise JobConflictError(f"Job {job_id} changed while retry was running")
        return result

    def _mark_retry_uncertain(self, job_id: str, original_upid: Optional[str]) -> None:
        """Preserve concurrent state while recording an ambiguous remote submission."""
        with self._write_transaction():
            record = self._load_record_from_db(job_id)
            if record.status == _RETRYING_STATUS and record.upid == original_upid:
                record.status = "needs_reconciliation"
            record.add_audit("retry_interrupted", upid=original_upid)
            self._save_record(record)

    def _claim_retry(self, record: JobRecord) -> None:
        previous_status = record.status
        record.status = _RETRYING_STATUS
        record.metadata["retry_lease_expires"] = (datetime.now(timezone.utc) + timedelta(seconds=self.retry_lease_seconds)).isoformat()
        record.add_audit("retry_started", previous_status=previous_status, upid=record.upid)
        placeholders = ", ".join("?" for _ in _RETRYABLE_STATUSES)
        cursor = self._conn.execute(
            f"""
            UPDATE jobs
            SET status = ?, updated_at = ?
            WHERE job_id = ? AND status IN ({placeholders})
            """,
            (
                record.status,
                record.updated_at,
                record.job_id,
                *sorted(_RETRYABLE_STATUSES),
            ),
        )
        if cursor.rowcount != 1:
            fresh = self._load_record_from_db(record.job_id)
            raise JobConflictError(
                f"Job {record.job_id} cannot be retried while status is '{fresh.status}'"
            )
        self._save_record(record)
        self._jobs[record.job_id] = record

    def _rollback_retry_claim(
        self,
        job_id: str,
        original_upid: str | None,
        previous_status: str,
        error: Exception,
    ) -> None:
        with self._write_transaction():
            record = self._load_record_from_db(job_id)
            if record.status != _RETRYING_STATUS or record.upid != original_upid:
                record.add_audit(
                    "retry_failure_discarded",
                    stale_upid=original_upid,
                    current_upid=record.upid,
                    current_status=record.status,
                    error=str(error)[:500],
                )
                self._save_record(record)
                return
            record.status = previous_status
            record.last_error = str(error)
            record.add_audit("retry_failed", error=str(error)[:500])
            self._save_record(record)

    def _get_record(self, job_id: str) -> JobRecord:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise JobNotFoundError(f"Unknown job_id: {job_id}") from exc

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

    @staticmethod
    def _lxc_restore_request(request: dict[str, Any]) -> dict[str, Any]:
        request = dict(request)
        if "archive" in request:
            request["ostemplate"] = request.pop("archive")
        request["restore"] = 1
        return request

    def _register_builtin_retry_handlers(self) -> None:
        self.register_retry_handler("vm.create", lambda params: self.proxmox.nodes(params["node"]).qemu.create(**params["vm_config"]))
        self.register_retry_handler(
            "vm.clone",
            lambda params: self.proxmox.nodes(params["node"]).qemu(params["source_vmid"]).clone.post(**params["clone_payload"]),
        )
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
            lambda params: submit_snapshot_rollback(self.proxmox, params["node"], params["vmid"], params["snapname"], params["vm_type"]),
        )
        self.register_retry_handler("backup.create", lambda params: self.proxmox.nodes(params["node"]).vzdump.post(**params["request"]))
        self.register_retry_handler(
            "backup.restore",
            lambda params: (
                self.proxmox.nodes(params["node"]).lxc.post(**self._lxc_restore_request(params["request"]))
                if params.get("is_lxc")
                else self.proxmox.nodes(params["node"]).qemu.post(**params["request"])
            ),
        )
        self.register_retry_handler(
            "backup.delete",
            lambda params: delete_volume(self.proxmox, params["node"], params["storage"], params["volid"], {"backup"}),
        )
        self.register_retry_handler(
            "iso.download",
            lambda params: self.proxmox.nodes(params["node"]).storage(params["storage"])("download-url").post(**params["request"]),
        )
        self.register_retry_handler(
            "iso.delete",
            lambda params: delete_volume(self.proxmox, params["node"], params["storage"], params["volid"], {"iso", "vztmpl"}),
        )
