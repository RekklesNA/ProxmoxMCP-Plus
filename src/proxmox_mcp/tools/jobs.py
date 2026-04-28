"""Job tools for long-running Proxmox operations."""

from __future__ import annotations

import json
from typing import Any, List, Optional

from mcp.types import TextContent as Content


class JobsTools:
    """Read and control jobs tracked by the in-process JobStore."""

    def __init__(self, job_store: Any) -> None:
        self.job_store = job_store

    def _json(self, payload: Any) -> List[Content]:
        return [Content(type="text", text=json.dumps(payload, indent=2, sort_keys=True))]

    def list_jobs(
        self,
        status: Optional[str] = None,
        tool_name: Optional[str] = None,
        limit: int = 100,
    ) -> List[Content]:
        return self._json(self.job_store.list_jobs(status=status, tool_name=tool_name, limit=limit))

    def get_job(self, job_id: str, refresh: bool = False) -> List[Content]:
        if refresh:
            return self._json(self.job_store.poll_job(job_id))
        return self._json(self.job_store.get_job(job_id))

    def poll_job(self, job_id: str) -> List[Content]:
        return self._json(self.job_store.poll_job(job_id))

    def cancel_job(self, job_id: str) -> List[Content]:
        return self._json(self.job_store.cancel_job(job_id))

    def retry_job(self, job_id: str) -> List[Content]:
        return self._json(self.job_store.retry_job(job_id))
