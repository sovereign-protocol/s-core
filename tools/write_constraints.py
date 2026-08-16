"""Render the reviewed inventory as pip constraints.

The inventory is the single source of truth: constraints are generated from it
rather than kept beside it, so the two cannot disagree. Installing the audited
platform's closure under these constraints makes the resolution deterministic -
a release upstream no longer changes what CI installs, so the inventory check
fails only when the closure itself changes shape and a licence needs reviewing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: write_constraints.py <output-path>")
    root = Path(__file__).resolve().parents[1]
    inventory = json.loads(
        (root / "dependency-inventory.json").read_text(encoding="utf-8")
    )
    lines = [
        f"{name}=={item['version']}"
        for name, item in sorted(inventory.items())
    ]
    output = Path(argv[1])
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(lines)} constraints to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
