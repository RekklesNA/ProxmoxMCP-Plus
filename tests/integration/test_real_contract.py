"""Integration wrapper for the live Proxmox end-to-end harness."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "test_scripts" / "run_real_e2e.py"


@pytest.mark.integration
def test_real_contract_suite() -> None:
    if os.getenv("PROXMOX_RUN_INTEGRATION") != "1":
        pytest.skip("Set PROXMOX_RUN_INTEGRATION=1 to run live Proxmox integration tests.")

    result = subprocess.run(
        [sys.executable, str(HARNESS)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=os.environ.copy(),
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            "Live integration harness failed.\n"
            f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
        )
