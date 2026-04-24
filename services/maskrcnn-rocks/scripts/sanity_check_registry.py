#!/usr/bin/env python3
"""
sanity_check_registry.py — run the registry scanner against the mounted
WEIGHTS_ROOT and dump the discovered ids.  Useful for verifying the scaffold
before we build/launch the container.

    python sanity_check_registry.py /mnt/22tb-hdd/maskrcnn
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from registry import discover, pick_default, to_public_json  # noqa: E402


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else "/mnt/22tb-hdd/maskrcnn"
    entries = discover(root)
    print(json.dumps({
        "count": len(entries),
        "default": pick_default(entries, None),
        "families": sorted({e.family for e in entries.values()}),
        "ids_first_30": [e["id"] for e in to_public_json(entries)[:30]],
        "bishop": [e["id"] for e in to_public_json(entries)
                   if e["family"] == "bishop"],
        "gobabeb": [e["id"] for e in to_public_json(entries)
                    if e["family"] == "gobabeb"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
