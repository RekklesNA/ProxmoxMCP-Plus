"""Require every executable runtime statement to be covered, without rounding."""

import json
import sys
from pathlib import Path


def main() -> None:
    report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    source = Path(__file__).resolve().parents[1] / "src" / "proxmox_mcp"
    expected = {path.relative_to(source).as_posix() for path in source.rglob("*.py")}
    files = report["files"]
    measured = {name.replace("\\", "/").split("proxmox_mcp/", 1)[-1] for name in files}
    uncovered = {name: data["missing_lines"] for name, data in files.items() if data["missing_lines"]}
    if expected != measured or uncovered:
        raise SystemExit(f"Coverage gate failed: missing files={sorted(expected - measured)}, extra files={sorted(measured - expected)}, uncovered={uncovered}")
    print(f"All {len(expected)} runtime modules have zero uncovered statements.")


if __name__ == "__main__":
    main()
