"""Test bootstrap helpers.

Ensure pytest imports the repository ``src`` tree before any stale installed
copy in ``site-packages``.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
