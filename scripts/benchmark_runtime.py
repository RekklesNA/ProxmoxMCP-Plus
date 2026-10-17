"""Reproducible synthetic polling and independent-session throughput baselines.

Run with the project source on PYTHONPATH. Results are local simulation data,
not production latency or a forecast of real-cluster throughput.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
from unittest.mock import Mock

from proxmox_mcp.core.session_pool import SessionPool
from proxmox_mcp.services.jobs import JobStore


def session_trial(size: int) -> float:
    def request(*args, **kwargs):
        time.sleep(.01)
        return SimpleNamespace(status_code=200)
    sessions = [SimpleNamespace(request=request, close=lambda: None) for _ in range(size)]
    pool = SessionPool(sessions, 5, lambda: None, lambda *args: None)
    start = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(lambda _: pool.request("GET", "/version"), range(32)))
        return time.perf_counter() - start
    finally:
        pool.close()


def polling_trial(ttl: float) -> dict:
    api = Mock()
    api.nodes.return_value.tasks.return_value.status.get.return_value = {"status": "running"}
    api.nodes.return_value.tasks.return_value.log.get.return_value = []
    with TemporaryDirectory() as directory, JobStore(api, str(Path(directory) / "jobs.db"), poll_cache_ttl=ttl) as store:
        job = store.register_task(tool_name="start_vm", summary="Synthetic task", node="pve", upid="UPID:pve:bench")
        start = time.perf_counter()
        for _ in range(50):
            store.poll_job(job["job_id"], include_audit=False)
        return {"seconds": time.perf_counter() - start,
                "backend_gets": api.nodes.return_value.tasks.return_value.status.get.call_count + api.nodes.return_value.tasks.return_value.log.get.call_count,
                "audit_events": len(store.get_audit(job["job_id"]))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = {"kind": "synthetic", "runs": 3, "pool_requests": 32, "request_delay_seconds": .01,
              "pool_seconds_median": {str(size): median(session_trial(size) for _ in range(3)) for size in (1, 4)},
              "polling": {"cache_disabled": polling_trial(0), "cache_enabled": polling_trial(60)}}
    encoded = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
