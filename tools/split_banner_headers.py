# tools/split_banner_headers.py
"""
Milestone 3: Split "banner" header chunks that contain multiple headers
(e.g. "EROSION CONTROL NOTES: SITE DEMOLITION NOTES: SITE CONSTRUCTION NOTES:")
into separate header chunks.

Key improvement:
- Adds a tiny gutter between split parts so overlay boxes don't "touch".

Why this exists:
- Some PDFs produce a single wide header bbox spanning multiple columns.
- Downstream logic needs distinct header chunks (and you need a sane overlay).

This tool is geometry-light by design:
- If we DON'T have per-word/line boxes for the header itself, we split the bbox evenly.
- We then apply a controlled "split-gap" and "edge-inset" so the overlay looks correct.
"""

from __future__ import annotations

import argparse
import json
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def _page_eq(chunk_page: Any, target_page: int) -> bool:
    # Your files sometimes store page as int, sometimes as string.
    return str(chunk_page) == str(target_page)


def _get_bbox_xyxy(chunk: Dict[str, Any]) -> Tuple[float, float, float, float]:
    """
    Supports bbox as:
      - [x0, y0, x1, y1]
      - {"x0":..., "y0":..., "x1":..., "y1":...}
    """
    b = chunk.get("bbox")
    if isinstance(b, list) and len(b) == 4:
        return float(b[0]), float(b[1]), float(b[2]), float(b[3])
    if isinstance(b, dict):
        return float(b["x0"]), float(b["y0"]), float(b["x1"]), float(b["y1"])
    raise ValueError(f"Unsupported bbox format for chunk id={chunk.get('id')}: {type(b)}")


def _set_bbox_dict(chunk: Dict[str, Any], x0: float, y0: float, x1: float, y1: float) -> None:
    # Keep header bboxes as dicts (matches your current header bbox style).
    chunk["bbox"] = {"x0": float(x0), "y0": float(y0), "x1": float(x1), "y1": float(y1)}


_SEGMENT_RE = re.compile(r"(.*?NOTES(?:\s*\(CONT'D\))?:)", re.IGNORECASE)


def _split_header_text(content: str) -> List[str]:
    """
    Prefer splitting into segments ending with "NOTES:" or "NOTES (CONT'D):".
    Falls back to simple colon-based splitting if needed.
    """
    if not content:
        return []

    s = " ".join(str(content).split())
    matches = [m.group(1).strip() for m in _SEGMENT_RE.finditer(s)]
    if len(matches) >= 2:
        return matches

    # Fallback: split by colon boundaries; keep colons.
    # Example: "A NOTES: B NOTES: C NOTES:" => ["A NOTES:", "B NOTES:", "C NOTES:"]
    parts = re.split(r":\s+", s)
    if len(parts) <= 1:
        return []
    segs = []
    for i, p in enumerate(parts):
        p = p.strip()
        if not p:
            continue
        # Re-add ":" except maybe last if original didn't end with ":"
        if i < len(parts) - 1 or s.endswith(":"):
            p = p + ":"
        segs.append(p)
    return segs


def _is_banner_header(chunk: Dict[str, Any]) -> bool:
    if chunk.get("type") != "header":
        return False
    content = (chunk.get("content") or "").strip()
    # A "banner" we care about is one header chunk containing multiple NOTES segments.
    # This catches your "EROSION CONTROL NOTES: SITE DEMOLITION NOTES: ..." cases.
    return len(_split_header_text(content)) >= 2


def _clamp_min_width(x0: float, x1: float, min_w: float = 1.0) -> Tuple[float, float]:
    if (x1 - x0) < min_w:
        mid = (x0 + x1) / 2.0
        x0 = mid - (min_w / 2.0)
        x1 = mid + (min_w / 2.0)
    return x0, x1


def split_banner_headers(
    obj: Dict[str, Any],
    target_page: int,
    split_gap: float,
    edge_inset: float,
    min_banner_width: float,
    debug: bool = False,
) -> Tuple[Dict[str, Any], int]:
    chunks: List[Dict[str, Any]] = obj.get("chunks", [])
    if not isinstance(chunks, list):
        raise ValueError("JSON missing 'chunks' list")

    # Debug: list pages in file
    if debug:
        pages = sorted({str(c.get("page")) for c in chunks if "page" in c})
        print(f"[DEBUG] target_page={target_page}")
        print(f"[DEBUG] unique_pages_in_file={pages}")

    page_chunks = [c for c in chunks if _page_eq(c.get("page"), target_page)]
    if debug:
        print(f"[DEBUG] page_chunks={len(page_chunks)} other_chunks={len(chunks) - len(page_chunks)} total={len(chunks)}")

    headers_on_page = [c for c in page_chunks if c.get("type") == "header"]
    if debug:
        print(f"[DEBUG] headers_on_page={len(headers_on_page)}")

    new_chunks: List[Dict[str, Any]] = []
    split_count = 0

    for c in chunks:
        if not _page_eq(c.get("page"), target_page) or not _is_banner_header(c):
            new_chunks.append(c)
            continue

        x0, y0, x1, y1 = _get_bbox_xyxy(c)
        w = x1 - x0
        if w < min_banner_width:
            new_chunks.append(c)
            continue

        seg_texts = _split_header_text((c.get("content") or "").strip())
        n = len(seg_texts)
        if n < 2:
            new_chunks.append(c)
            continue

        seg_w = w / float(n)
        orig_id = c.get("id")
        base_meta = dict(c.get("metadata") or {})

        # Build split chunks with gutter:
        # - internal boundaries get +/- split_gap/2 so boxes don't touch
        # - edge_inset shrinks each box slightly so it hugs better
        for i, text in enumerate(seg_texts):
            sx0 = x0 + (i * seg_w)
            sx1 = x0 + ((i + 1) * seg_w)

            # Gutter between neighbors
            if i > 0:
                sx0 += split_gap / 2.0
            if i < n - 1:
                sx1 -= split_gap / 2.0

            # Small inset on both edges (prevents "touching" even when gaps are tiny)
            sx0 += edge_inset
            sx1 -= edge_inset

            sx0, sx1 = _clamp_min_width(sx0, sx1, min_w=1.0)

            nc = dict(c)
            nc["id"] = str(uuid.uuid4())
            nc["type"] = "header"
            nc["content"] = text.strip()

            meta = dict(base_meta)
            meta.update(
                {
                    "split_from": orig_id,
                    "split_index": i,
                    "split_total": n,
                    "split_gap": split_gap,
                    "edge_inset": edge_inset,
                }
            )
            nc["metadata"] = meta

            _set_bbox_dict(nc, sx0, y0, sx1, y1)
            new_chunks.append(nc)

        split_count += 1

    obj["chunks"] = new_chunks
    return obj, split_count


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Split multi-column banner headers into separate header chunks.")
    ap.add_argument("--input", required=True, help="Input JSON path")
    ap.add_argument("--output", required=True, help="Output JSON path")
    ap.add_argument("--page", required=True, type=int, help="Page to process")
    ap.add_argument("--x-tol", type=float, default=140.0, help="Kept for compatibility (not used in this splitter).")

    # The knobs you actually care about for “touching boxes”
    ap.add_argument("--split-gap", type=float, default=2.0, help="Gap between split header boxes (PDF units).")
    ap.add_argument("--edge-inset", type=float, default=0.75, help="Inset applied to each split box edge (PDF units).")
    ap.add_argument("--min-banner-width", type=float, default=250.0, help="Skip splitting if bbox width is smaller than this.")
    ap.add_argument("--debug", action="store_true", help="Verbose debug output")
    return ap.parse_args()


def main() -> int:
    a = parse_args()
    inp = Path(a.input)
    out = Path(a.output)

    if not inp.exists():
        raise FileNotFoundError(f"Input JSON not found: {inp}")

    obj = _load_json(inp)
    obj2, split_n = split_banner_headers(
        obj=obj,
        target_page=a.page,
        split_gap=a.split_gap,
        edge_inset=a.edge_inset,
        min_banner_width=a.min_banner_width,
        debug=a.debug,
    )

    _write_json(out, obj2)
    print(f"[OK] Wrote: {out}")
    print(f"[INFO] Split {split_n} banner header chunk(s) on page {a.page}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
