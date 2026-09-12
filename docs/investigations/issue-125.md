# Issue #125: standalone node reported as non-quorate

Investigated on 2026-09-12 against main commit
`0f79c56460caae5576a899f1be49bfa4924c6cab` (v0.5.15).
Local repair branch: `Dev-issue-125-cluster-status`.

## Finding and upstream evidence

[Issue #125](https://github.com/RekklesNA/ProxmoxMCP-Plus/issues/125)
is reproducible in the application using a mocked Proxmox API response.
The upstream [Proxmox status implementation](https://github.com/proxmox/pve-manager/blob/master/PVE/API2/Cluster.pm)
defines `quorate` as an optional cluster-only boolean and returns a local
`type: node` entry when no cluster is defined (reviewed on the investigation date).

Two application assumptions cause the false alarm:

1. `ClusterTools.get_cluster_status()` reads `result[0]` as cluster metadata,
   regardless of its `type`. A standalone node's name becomes the cluster name.
2. `ProxmoxTemplates.cluster_status()` uses a truthiness check that maps both
   missing quorum information and an actual false verdict to `NOT OK`.

This is a read-only reporting error. It can mislead clients and operators;
the affected query does not modify quorum configuration or VM state.

## Reproduction

Run this Python snippet with the checkout's `src` directory on `PYTHONPATH`
and the project's dependencies installed. No live host or credentials are needed.

```python
from unittest.mock import Mock
from proxmox_mcp.tools.cluster import ClusterTools

api = Mock()
api.cluster.status.get.return_value = [
    {"type": "node", "name": "pve", "local": 1, "online": 1}
]
print(ClusterTools(api).get_cluster_status()[0].text)
```

Observed on the unmodified main implementation:

```text
[config] Proxmox Cluster

  - Name: pve
  - Quorum: NOT OK
  - Nodes: 1
```

The first regression run, before the production repair, had **8 failed,
5 passed**. Failures covered standalone output, empty/null responses,
cluster records appearing after node records, and missing/null quorum values.

## Repair and expected behavior

Select cluster metadata by `type == "cluster"`, independently of record order.
Retain cluster membership separately from quorum, including in cached data.
Format explicitly absent quorum as unknown, preserving real false verdicts.

| API evidence | Cluster name | Quorum output |
| --- | --- | --- |
| Node records without cluster metadata | `n/a (not clustered)` | `n/a (not clustered)` |
| Cluster record with `quorate=1` | Actual cluster name | `OK` |
| Cluster record with `quorate=0` | Actual cluster name | `NOT OK` |
| Cluster record with missing/null `quorate` | Actual name, or `unknown` if absent | `unknown` |
| Empty/null response | `unknown` | `unknown` |
| API exception | Existing error handling | No standalone success response |

Unlike a simple absence-of-cluster check, an empty response is treated as
unknown: it supplies no positive evidence of standalone operation.
Node count is not used to infer membership; a one-node cluster can still
report a real non-quorate state. Existing template callers without the new
`clustered` field retain their known true/false quorum verdicts.

Observed after repair using the same reproduction input:

```text
[config] Proxmox Cluster

  - Name: n/a (not clustered)
  - Quorum: n/a (not clustered)
  - Nodes: 1
```

## Validation

Environment: Windows, Python 3.13.6, existing project virtual environment.
`PYTHONPATH` explicitly pointed to this worktree's `src`, including for
subprocess tests.

- Targeted tests: **17 passed**, including the existing healthy-cluster test,
  new standalone/lost/unknown quorum calls through `server.mcp.call_tool`,
  cache consistency, legacy formatter compatibility, and API failure handling.
- Full suite: **374 passed, 2 skipped**, coverage **80.38%** against a 75% gate.
- `cluster.py`: 100% statement coverage in this run.
- Ruff, Mypy (47 source files), and `git diff --check`: passed.
- The full suite emitted three SQLite connection ResourceWarnings.

Commands from the repair worktree, with the project environment active:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -m pytest tests/test_cluster_status.py tests/test_server.py -k cluster_status -q
python -m pytest -q --cov=proxmox_mcp --cov-report=term-missing --cov-fail-under=75
python -m ruff check .
python -m mypy src --ignore-missing-imports
git diff --check
```

These initial investigation results are local automated tests with mocked
Proxmox responses, not a live Proxmox or HTTP transport reproduction.
Publication validation is recorded separately in the release PR and its
GitHub Actions runs; this section describes the pre-publication investigation.
