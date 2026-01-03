#!/usr/bin/env python
"""
promote_headers_from_textlines.py

Fallback header detection:
- If a page has header-looking text_line chunks that were NOT promoted to type=header,
  create header chunks from them.

Why:
- Some titles (like "SITE GRADING NOTES:") are currently getting left as text_line and/or
  absorbed into note_group, so they never become green header boxes in the overlay.

Heuristic:
- text is ALL CAPS-ish
- contains "NOTES"
- ends with ":" (or "(CONT'D):")
"""

from __future__ import annotations

import argparse
import json
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

BBox = Union[List[float], Dict[str, float]]

HEADER_RE = re.compile(r"^[A-Z0-9\s\-\(\)\'\.\&\/]+NOTES(\s*\(CONT\'D\))?:\s*$")


def _load_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def _save_json(p: Path, obj: Dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def bbox_to_xyxy(b: BBox) -> Tuple[float, float, float, float]:
    if isinstance(b, dict):
        return float(b["x0"]), float(b["y0"]), float(b["x1"]), float(b["y1"])
    return float(b[0]), float(b[1]), float(b[2]), float(b[3])


def overlap_frac(a: BBox, b: BBox) -> float:
    ax0, ay0, ax1, ay1 = bbox_to_xyxy(a)
    bx0, by0, bx1, by1 = bbox_to_xyxy(b)

    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)

    iw = max(0.0, ix1 - ix0)
    ih = max(0.0, iy1 - iy0)
    inter = iw * ih

    aa = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    if aa <= 0:
        return 0.0
    return inter / aa


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--page", required=True)
    p.add_argument("--min-overlap-existing", type=float, default=0.60,
                   help="If a candidate text_line overlaps an existing header bbox >= this, do nothing.")
    p.add_argument("--debug", action="store_true")
    return p.parse_args()


def main() -> int:
    a = parse_args()
    obj = _load_json(Path(a.input))
    chunks: List[Dict[str, Any]] = obj.get("chunks", [])

    target_page = str(a.page)

    page_chunks = [c for c in chunks if str(c.get("page")) == target_page]
    other_chunks = [c for c in chunks if str(c.get("page")) != target_page]

    existing_headers = [c for c in page_chunks if c.get("type") == "header" and c.get("bbox") is not None]
    text_lines = [c for c in page_chunks if c.get("type") == "text_line" and c.get("bbox") is not None]

    added = 0

    for tl in text_lines:
        txt = (tl.get("text") or "").strip()
        if not txt:
            continue

        # Fast normalization: collapse double spaces
        norm = re.sub(r"\s+", " ", txt).strip()

        if not HEADER_RE.match(norm):
            continue

        # If it already overlaps an existing header a lot, skip (avoid duplicates)
        if any(overlap_frac(tl["bbox"], h["bbox"]) >= a.min_overlap_existing for h in existing_headers):
            continue

        header = {
            "id": str(uuid.uuid4()),
            "page": tl.get("page"),
            "type": "header",
            "text": norm,
            "bbox": tl["bbox"],  # start as tight as the text_line
            "metadata": {
                "header_candidate": True,
                "promoted_from": "text_line",
                "source_text_line_id": tl.get("id"),
            },
        }
        page_chunks.append(header)
        existing_headers.append(header)
        added += 1

        if a.debug:
            print(f"[DEBUG] promoted header: {norm}")

    obj["chunks"] = other_chunks + page_chunks
    _save_json(Path(a.output), obj)

    print(f"[INFO] Page {target_page}: promoted {added} header(s) from text_line.")
    print(f"[OK] Wrote: {a.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
