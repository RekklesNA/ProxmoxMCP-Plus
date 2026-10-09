"""SQLite persistence, target isolation and append-only job audit storage."""
from __future__ import annotations
import json
import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from .job_models import JobRecord, JobAuditEvent, JobNotFoundError, _sanitize, _utcnow
from .job_polling import PollCoordinator


class JobPersistence:
    _lock: Any
    _conn: sqlite3.Connection
    _jobs: dict[str, JobRecord]
    _polling: PollCoordinator
    target_name: str | None
    legacy_mode: bool
    audit_retention_days: int | None

    @contextmanager
    def _write_transaction(self) -> Iterator[None]:
        # Never hold this transaction during network I/O.
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            yield

    def _configure_connection(self) -> None:
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA foreign_keys = ON")

    def _init_db(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
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
                retry_spec_json TEXT,
                retry_spec_redacted INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        try:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN retry_spec_redacted INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs (created_at DESC)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status_created_at ON jobs (status, created_at DESC)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_tool_created_at ON jobs (tool_name, created_at DESC)")
        self._conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (1, _utcnow()),
        )
        self._conn.commit()
        with self._write_transaction():
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS job_audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    event TEXT NOT NULL,
                    details_json TEXT NOT NULL
                )
            """)
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_job_audit_job_time "
                "ON job_audit_events(job_id, timestamp)"
            )
            for row in self._conn.execute(
                "SELECT job_id, audit_log_json FROM jobs WHERE audit_log_json != '[]'"
            ).fetchall():
                for item in json.loads(row["audit_log_json"] or "[]"):
                    self._conn.execute(
                        "INSERT INTO job_audit_events(job_id, timestamp, event, details_json) VALUES (?, ?, ?, ?)",
                        (row["job_id"], item["timestamp"], item["event"], json.dumps(_sanitize(item.get("details", {})))),
                    )
                self._conn.execute("UPDATE jobs SET audit_log_json = '[]' WHERE job_id = ?", (row["job_id"],))
            self._conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)", (2, _utcnow()),
            )
        # Migration warning: legacy jobs without target metadata cannot be safely
        # isolated between named targets. In legacy mode this store owns the whole
        # database and still serves those jobs, so no warning is warranted.
        if self.target_name is not None and not self.legacy_mode:
            count = self._conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE json_extract(metadata_json, '$.target') IS NULL"
            ).fetchone()[0]
            if count:
                import logging
                logging.getLogger("proxmox-mcp.jobs").warning(
                    "Job DB contains %s legacy jobs without target metadata; run migration or clear DB", count
                )

    def _load_records(self) -> None:
        with self._lock:
            for record in self._query_records(limit=500, include_audit=False):
                self._jobs[record.job_id] = record

    def _row_to_record(self, row: sqlite3.Row, audit_rows: list[Any] | None = None) -> JobRecord:
        job_id = str(row["job_id"])
        existing = self._jobs.get(job_id)
        audit = audit_rows if audit_rows is not None else self._conn.execute(
            "SELECT timestamp, event, details_json FROM job_audit_events WHERE job_id = ? ORDER BY id", (job_id,),
        ).fetchall()
        return JobRecord(
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
                    details=json.loads(item["details_json"]),
                )
                for item in audit
            ],
            _persisted_audit_count=len(audit),
            retry_spec=json.loads(row["retry_spec_json"]) if row["retry_spec_json"] else None,
            retry_spec_redacted=bool(row["retry_spec_redacted"]) if "retry_spec_redacted" in row.keys() else False,
            retry_factory=existing.retry_factory if existing is not None else None,
            cancel_factory=existing.cancel_factory if existing is not None else None,
        )

    def _target_matches(self, stored_target: Any) -> bool:
        """Whether a stored job belongs to this store's target.

        In legacy mode the store owns the entire database, so jobs written
        before target metadata existed (stored_target is None) remain visible.
        Named targets never inherit untargeted jobs.
        """
        if self.target_name is None:
            return True
        if stored_target == self.target_name:
            return True
        return self.legacy_mode and stored_target is None

    def _load_record_from_db(self, job_id: str, *, include_audit: bool = True) -> JobRecord:
        row = self._conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            self._jobs.pop(job_id, None)
            raise JobNotFoundError(f"Unknown job_id: {job_id}")
        stored_target = json.loads(row["metadata_json"] or "{}").get("target")
        if not self._target_matches(stored_target):
            raise JobNotFoundError(f"Unknown job_id: {job_id}")
        record = self._row_to_record(row, None if include_audit else [])
        if record.status == "retrying":
            expires = record.metadata.get("retry_lease_expires", record.updated_at)
            if expires <= _utcnow():
                record.status = "needs_reconciliation"
                record.add_audit("retry_lease_expired")
                self._save_record(record)
        self._jobs[record.job_id] = record
        self._trim_cache()
        return record

    def _query_records(
        self,
        *,
        status: Optional[str] = None,
        tool_name: Optional[str] = None,
        limit: int = 100,
        include_audit: bool = True,
    ) -> list[JobRecord]:
        safe_limit = max(1, min(int(limit), 500))
        where: list[str] = []
        params: list[Any] = []
        if status:
            where.append("status = ?")
            params.append(status)
        if tool_name:
            where.append("tool_name = ?")
            params.append(tool_name)
        if self.target_name is not None:
            if self.legacy_mode:
                # Legacy upgrade: this store owns the database, so also surface
                # jobs recorded before target metadata was introduced.
                where.append(
                    "(json_extract(metadata_json, '$.target') = ? "
                    "OR json_extract(metadata_json, '$.target') IS NULL)"
                )
            else:
                where.append("json_extract(metadata_json, '$.target') = ?")
            params.append(self.target_name)
        where_clause = f"WHERE {' AND '.join(where)}" if where else ""
        rows = self._conn.execute(
            f"SELECT * FROM jobs {where_clause} ORDER BY created_at DESC LIMIT ?",
            (*params, safe_limit),
        ).fetchall()
        audit_by_job: dict[str, list[Any]] = {row["job_id"]: [] for row in rows}
        if rows and include_audit:
            placeholders = ",".join("?" for _ in rows)
            for event in self._conn.execute(f"SELECT job_id,timestamp,event,details_json FROM job_audit_events WHERE job_id IN ({placeholders}) ORDER BY id", tuple(audit_by_job)).fetchall():
                audit_by_job[event["job_id"]].append(event)
        records = [self._row_to_record(row, audit_by_job[row["job_id"]]) for row in rows]
        for record in records:
            self._jobs[record.job_id] = record
        self._trim_cache()
        return records

    def _trim_cache(self) -> None:
        while len(self._jobs) > 500:
            self._jobs.pop(next(iter(self._jobs)))

    def _save_record(self, record: JobRecord) -> None:
        self._polling.invalidate(record.job_id)
        self._trim_cache()
        self._conn.execute(
            """
            INSERT OR REPLACE INTO jobs (
                job_id, tool_name, summary, node, upid, created_at, updated_at, status,
                progress, attempts, retry_count, last_error, completed_at, result_json,
                metadata_json, previous_upids_json, audit_log_json, retry_spec_json, retry_spec_redacted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                _sanitize(record.last_error),
                record.completed_at,
                json.dumps(_sanitize(record.result), sort_keys=True) if record.result is not None else None,
                json.dumps(_sanitize(record.metadata), sort_keys=True),
                json.dumps(record.previous_upids),
                "[]",
                json.dumps(record.retry_spec, sort_keys=True) if record.retry_spec is not None else None,
                int(record.retry_spec_redacted),
            ),
        )
        for event in record.audit_log[record._persisted_audit_count:]:
            self._conn.execute(
                "INSERT INTO job_audit_events(job_id, timestamp, event, details_json) VALUES (?, ?, ?, ?)",
                (record.job_id, event.timestamp, event.event, json.dumps(_sanitize(event.details))),
            )
        record._persisted_audit_count = len(record.audit_log)
        if self.audit_retention_days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=self.audit_retention_days)).isoformat()
            self._conn.execute(
                "DELETE FROM job_audit_events WHERE job_id = ? AND timestamp < ?", (record.job_id, cutoff),
            )
            record.audit_log = [event for event in record.audit_log if event.timestamp >= cutoff]
            record._persisted_audit_count = len(record.audit_log)

