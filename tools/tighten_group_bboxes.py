#!/usr/bin/env python3
"""
tools/tighten_group_bboxes.py

Milestone helper: tighten "group" bboxes (ex: note_group, header) to the bboxes
of overlapping "child" chunks (ex: text_line).

This file is part of the pipeline stability milestone:
- supports bbox dicts AND lists on input
- writes canonical bbox dicts on output
- never silently no-ops due to schema drift

Typical use:
  py tools\\tighten_group_bboxes.py ^
    --input  exports\\Runs\\<run>\\stage2_headers_split.json ^
    --output exports\\Runs\\<run>\\stage2b_headers_split_tight.json ^
    --page 3 ^
    --group-types header ^
    --child-types text_line ^
    --min-child-overlap 0.20 ^
    --pad 1.5 ^
    --debug
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import bbox_utils


# -----------------------------------------------------------------------------
# JSON helpers (atomic write)
# -----------------------------------------------------------------------------


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _get_chunks(root: Any) -> Tuple[List[Dict[str, Any]], Any]:
    if isinstance(root, dict) and isinstance(root.get("chunks"), list):
        return root["chunks"], root
    if isinstance(root, list):
        return [c for c in root if isinstance(c, dict)], root
    raise ValueError("Unsupported JSON root. Expected {'chunks':[...]} or list root.")


def _parse_csv(s: str) -> List[str]:
    return [p.strip() for p in (s or "").split(",") if p.strip()]


@dataclass
class Stats:
    considered: int = 0
    tightened: int = 0
    skipped_no_children: int = 0
    skipped_no_bbox: int = 0


# -----------------------------------------------------------------------------
# Geometry
# -----------------------------------------------------------------------------


def _intersection_area(a: bbox_utils.BBox, b: bbox_utils.BBox) -> float:
    inter = a.intersection(b)
    return inter.area if inter else 0.0


def _union_from(boxes: List[bbox_utils.BBox]) -> bbox_utils.BBox:
    out = boxes[0]
    for b in boxes[1:]:
        out = out.union(b)
    return out


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--page", required=True, type=int)

    # Primary
    ap.add_argument("--group-types", default="note_group",
                    help="Comma-separated group types to tighten (ex: header,note_group).")

    # Back-compat / alias
    ap.add_argument("--include-types", default=None,
                    help="ALIAS for --group-types (kept to prevent wasted time).")

    ap.add_argument("--child-types", default="text_line",
                    help="Comma-separated child types to tighten against (ex: text_line).")

    ap.add_argument("--min-child-overlap", type=float, default=0.20,
                    help="Intersection area / child area threshold to count a child as belonging to group.")
    ap.add_argument("--pad", type=float, default=0.0,
                    help="Padding applied after tightening. Positive expands; negative shrinks.")
    ap.add_argument("--debug", action="store_true")
    return ap.parse_args()


def main() -> int:
    a = parse_args()

    inp = Path(a.input)
    out = Path(a.output)
    if not inp.exists():
        raise FileNotFoundError(f"Input JSON not found: {inp}")

    group_types = _parse_csv(a.group_types)
    if a.include_types:
        group_types = _parse_csv(a.include_types)

    child_types = _parse_csv(a.child_types)
    page_str = str(a.page)

    root = _load_json(inp)
    chunks, wrapper = _get_chunks(root)

    # Pre-filter child chunks for speed
    child_chunks: List[Tuple[Dict[str, Any], bbox_utils.BBox]] = []
    for c in chunks:
        if str(c.get("page")) != page_str:
            continue
        if c.get("type") not in child_types:
            continue
        cb = bbox_utils.extract_bbox(c)
        if cb is None:
            continue
        child_chunks.append((c, cb))

    stats = Stats()

    for g in chunks:
        if str(g.get("page")) != page_str:
            continue
        if g.get("type") not in group_types:
            continue

        gb = bbox_utils.extract_bbox(g)
        if gb is None:
            stats.skipped_no_bbox += 1
            continue

        stats.considered += 1

        matched: List[bbox_utils.BBox] = []
        for _, cb in child_chunks:
            inter_area = _intersection_area(gb, cb)
            if cb.area <= 0.0:
                continue
            ratio = inter_area / cb.area
            if ratio >= float(a.min_child_overlap):
                matched.append(cb)

        if not matched:
            stats.skipped_no_children += 1
            # Still normalize bbox schema (canonical dict)
            bbox_utils.write_bbox(g, gb, bbox_format="dict", sync_top_level=True)
            continue

        tight = _union_from(matched).pad(float(a.pad))
        bbox_utils.write_bbox(g, tight, bbox_format="dict", sync_top_level=True)
        stats.tightened += 1

    # Write back
    if isinstance(wrapper, dict):
        wrapper2 = dict(wrapper)
        wrapper2["chunks"] = chunks
        _atomic_write_json(out, wrapper2)
    else:
        _atomic_write_json(out, chunks)

    if a.debug:
        print(f"[INFO] Page {a.page}: considered {stats.considered} group(s)")
        print(f"[INFO] Page {a.page}: tightened  {stats.tightened} group(s)")
        print(f"[INFO] Page {a.page}: skipped    {stats.skipped_no_children} (no matching children)")
        print(f"[INFO] Page {a.page}: skipped    {stats.skipped_no_bbox} (missing bbox)")
    print(f"[OK] Wrote: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
