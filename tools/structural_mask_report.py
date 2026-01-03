#!/usr/bin/env python
"""
structural_mask_report.py

Compare an original notes JSON against a structurally-masked version
(e.g. with legend + project_info_panel stripped) and report:

- total chunks before / after / removed
- per-page counts before / after / removed

This helps verify that our structural masking is doing what we expect.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from typing import Dict, Any, List, Tuple


def load_chunks(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    chunks = data.get("chunks", [])
    if not isinstance(chunks, list):
        raise SystemExit(f"{path} does not look like a notes JSON with a 'chunks' list")
    return chunks


def count_per_page(chunks: List[Dict[str, Any]]) -> Dict[int, int]:
    counts = defaultdict(int)
    for ch in chunks:
        page = ch.get("page")
        if page is None:
            continue
        try:
            p = int(page)
        except (TypeError, ValueError):
            continue
        counts[p] += 1
    return dict(counts)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Report how many chunks were removed by structural masking "
            "(legend / project_info_panel) per page."
        )
    )
    p.add_argument(
        "--original-json",
        required=True,
        help="Original notes JSON (e.g. exports/all_pages_notes_sheetwide.json)",
    )
    p.add_argument(
        "--masked-json",
        required=True,
        help="Masked notes JSON (e.g. exports/all_pages_notes_sheetwide_no_legend_structural.json)",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    orig_chunks = load_chunks(args.original_json)
    masked_chunks = load_chunks(args.masked_json)

    orig_total = len(orig_chunks)
    masked_total = len(masked_chunks)
    removed_total = orig_total - masked_total

    print("=== Structural Mask Report ===")
    print(f"Original chunks: {orig_total}")
    print(f"Masked   chunks: {masked_total}")
    print(f"Removed  chunks: {removed_total}")
    print()

    orig_by_page = count_per_page(orig_chunks)
    masked_by_page = count_per_page(masked_chunks)

    all_pages = sorted(set(orig_by_page) | set(masked_by_page))

    print("Per-page counts:")
    print("page | original | masked | removed")
    print("-----+----------+--------+--------")

    for p in all_pages:
        o = orig_by_page.get(p, 0)
        m = masked_by_page.get(p, 0)
        r = o - m
        print(f"{p:4d} | {o:8d} | {m:6d} | {r:7d}")

    print("\nPages with removals:")
    for p in all_pages:
        o = orig_by_page.get(p, 0)
        m = masked_by_page.get(p, 0)
        r = o - m
        if r > 0:
            print(f"  page {p}: removed {r} chunk(s)")


if __name__ == "__main__":
    main()
