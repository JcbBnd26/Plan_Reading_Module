#!/usr/bin/env python
"""
filter_notes_for_overlay.py

Create a JSON snapshot that excludes legend-region chunks so overlays
only show notes + title-block content.

Usage:
    python filter_notes_for_overlay.py ^
        --input  exports/all_pages_notes_merged_v4.json ^
        --output exports/all_pages_notes_merged_v4_notes_only.json
"""

from __future__ import annotations

import argparse
import json
from typing import Dict, Any, List


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Filter merged notes JSON to drop legend-region chunks."
    )
    p.add_argument(
        "--input",
        required=True,
        help="Path to merged JSON (with region_type metadata).",
    )
    p.add_argument(
        "--output",
        required=True,
        help="Path to write notes-only JSON (legend removed).",
    )
    p.add_argument(
        "--indent",
        type=int,
        default=2,
        help="Pretty-print indent (default: 2).",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        raw: Dict[str, Any] = json.load(f)

    chunks: List[Dict[str, Any]] = raw.get("chunks", [])

    filtered: List[Dict[str, Any]] = []
    for ch in chunks:
        md = ch.get("metadata") or {}
        region = md.get("region_type", "unknown")
        if region == "legend":
            continue
        filtered.append(ch)

    raw["chunks"] = filtered

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=args.indent, ensure_ascii=False)


if __name__ == "__main__":
    main()
