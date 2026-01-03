#!/usr/bin/env python
"""
trim_groups_by_headers.py

If a note_group bbox overlaps a header at the top, trim the group's y0 down to sit under the header.

Why:
- You can have the header text physically inside the note_group bbox.
- Even if we promote/create a header, the red note_group can "swallow" it visually and logically.

This is a geometry fix (bbox-only). It does NOT delete children.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

BBox = Union[List[float], Dict[str, float]]


def _load_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def _save_json(p: Path, obj: Dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def bbox_to_xyxy(b: BBox) -> Tuple[float, float, float, float]:
    if isinstance(b, dict):
        return float(b["x0"]), float(b["y0"]), float(b["x1"]), float(b["y1"])
    return float(b[0]), float(b[1]), float(b[2]), float(b[3])


def xyxy_to_bbox_like(x0: float, y0: float, x1: float, y1: float, like: BBox) -> BBox:
    if isinstance(like, dict):
        return {"x0": x0, "y0": y0, "x1": x1, "y1": y1}
    return [x0, y0, x1, y1]


def x_overlap_frac(a: BBox, b: BBox) -> float:
    ax0, _, ax1, _ = bbox_to_xyxy(a)
    bx0, _, bx1, _ = bbox_to_xyxy(b)
    inter = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    aw = max(1e-6, ax1 - ax0)
    return inter / aw


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--page", required=True)
    p.add_argument("--group-type", default="note_group")
    p.add_argument("--gap", type=float, default=2.0, help="Gap under header (PDF units).")
    p.add_argument("--min-x-overlap", type=float, default=0.50, help="Require x overlap fraction.")
    p.add_argument("--top-tol", type=float, default=25.0,
                   help="Only trim groups where header is near the group's top (header.y0 - group.y0 <= tol).")
    p.add_argument("--debug", action="store_true")
    return p.parse_args()


def main() -> int:
    a = parse_args()
    obj = _load_json(Path(a.input))
    chunks: List[Dict[str, Any]] = obj.get("chunks", [])

    target_page = str(a.page)

    page_chunks = [c for c in chunks if str(c.get("page")) == target_page]
    other_chunks = [c for c in chunks if str(c.get("page")) != target_page]

    headers = [c for c in page_chunks if c.get("type") == "header" and c.get("bbox") is not None]
    groups = [c for c in page_chunks if c.get("type") == a.group_type and c.get("bbox") is not None]

    trimmed = 0

    for g in groups:
        gx0, gy0, gx1, gy1 = bbox_to_xyxy(g["bbox"])
        for h in headers:
            hx0, hy0, hx1, hy1 = bbox_to_xyxy(h["bbox"])

            # Header should be near top of this group
            if (hy0 - gy0) > a.top_tol:
                continue

            # Must overlap in x meaningfully
            if x_overlap_frac(h["bbox"], g["bbox"]) < a.min_x_overlap:
                continue

            # If header is inside group's vertical span, trim group down
            if gy0 <= hy1 <= gy1:
                new_y0 = max(gy0, hy1 + a.gap)
                if new_y0 < gy1 - 1.0:  # keep at least 1 unit height
                    g["bbox"] = xyxy_to_bbox_like(gx0, new_y0, gx1, gy1, g["bbox"])
                    trimmed += 1
                    if a.debug:
                        print(f"[DEBUG] trimmed group {g.get('id')} under header '{(h.get('text') or '').strip()}'")
                break

    obj["chunks"] = other_chunks + page_chunks
    _save_json(Path(a.output), obj)

    print(f"[INFO] Page {target_page}: trimmed {trimmed} {a.group_type}(s) under headers.")
    print(f"[OK] Wrote: {a.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
