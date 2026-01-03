#!/usr/bin/env python3
"""
tools/fix_split_notes_postmerge.py

Post-merge “stitcher” for notes.

Stability fixes:
- Checks input existence with a clear error.
- Validates JSON root shape.
- Reads bbox via bbox_utils (dict/list/top-level), WRITES canonical dict bbox.
- Never silently writes list-bbox again (kills schema drift).

Behavior (intentionally conservative)
-------------------------------------
Within each page + column:
- Find a bullet-starting chunk (e.g., "9.", "A)", "-", "•").
- Merge it with immediate non-bullet chunks below it if:
    - vertical gap <= --max-gap
    - horizontal overlap ratio >= --min-overlap

This tool remains a "safety net" even if merge_note_fragments improves.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import bbox_utils


# -----------------------------------------------------------------------------
# Text + bullets
# -----------------------------------------------------------------------------


BULLET_RE = re.compile(
    r"^\s*(?:\d{1,3}[\.)]|[A-Z][\.)]|[-*•+])(?:\s+|$)",
    flags=re.UNICODE,
)


def looks_like_bullet(text: str) -> bool:
    return bool(BULLET_RE.match(text or ""))


def get_text(ch: Dict[str, Any]) -> str:
    if isinstance(ch.get("text"), str):
        return ch["text"]
    if isinstance(ch.get("content"), str):
        return ch["content"]
    return ""


def set_text(ch: Dict[str, Any], text: str) -> None:
    ch["text"] = text
    ch["content"] = text


def merge_text(a: str, b: str) -> str:
    """
    Merge two text blobs with a space (not a newline) because this stage is about
    "wrapped continuation lines".
    """
    a = (a or "").rstrip()
    b = (b or "").lstrip()
    if not a:
        return b
    if not b:
        return a
    return f"{a} {b}"


# -----------------------------------------------------------------------------
# Columns
# -----------------------------------------------------------------------------


def _get_visual_column_index(ch: Dict[str, Any]) -> Optional[int]:
    v = ch.get("visual_column_index")
    if isinstance(v, int):
        return v
    meta = ch.get("metadata")
    if isinstance(meta, dict) and isinstance(meta.get("visual_column_index"), int):
        return int(meta["visual_column_index"])
    return None


def assign_fallback_columns_by_x0(
    items: List[Tuple[int, Dict[str, Any], bbox_utils.BBox]],
    x0_tolerance: float,
) -> Dict[int, int]:
    """
    Cluster by x0 into columns. Returns map: original_chunk_index -> column_index.
    """
    xs: List[Tuple[int, float]] = [(idx, float(box.x0)) for idx, _, box in items]
    if not xs:
        return {}

    xs.sort(key=lambda t: t[1])

    clusters: List[Dict[str, Any]] = []
    for idx, x0 in xs:
        if not clusters:
            clusters.append({"rep": x0, "members": [idx], "xs": [x0]})
            continue
        last = clusters[-1]
        if abs(x0 - float(last["rep"])) <= float(x0_tolerance):
            last["members"].append(idx)
            last["xs"].append(x0)
            last["rep"] = sum(last["xs"]) / len(last["xs"])
        else:
            clusters.append({"rep": x0, "members": [idx], "xs": [x0]})

    clusters.sort(key=lambda c: float(c["rep"]))

    col_map: Dict[int, int] = {}
    for col_idx, cl in enumerate(clusters):
        for idx in cl["members"]:
            col_map[int(idx)] = int(col_idx)
    return col_map


# -----------------------------------------------------------------------------
# Stitching
# -----------------------------------------------------------------------------


def get_page_num(ch: Dict[str, Any]) -> int:
    for key in ("page", "page_index", "page_number", "page_num"):
        if key in ch:
            try:
                return int(ch[key])
            except Exception:
                pass
    return 0


def stitch_page(
    page_num: int,
    page_items: List[Tuple[int, Dict[str, Any], bbox_utils.BBox]],
    max_gap: float,
    min_overlap: float,
    x0_tolerance: float,
) -> List[Dict[str, Any]]:
    """
    Returns stitched chunks for this page (only for the subset passed in).
    """
    # Column strategy
    visual_cols = [
        _get_visual_column_index(ch)
        for _, ch, _ in page_items
        if _get_visual_column_index(ch) is not None
    ]
    use_visual = len(set(visual_cols)) >= 2

    fallback = {} if use_visual else assign_fallback_columns_by_x0(page_items, x0_tolerance)

    cols: Dict[int, List[Tuple[int, Dict[str, Any], bbox_utils.BBox]]] = {}
    for idx, ch, box in page_items:
        vcol = _get_visual_column_index(ch) if use_visual else None
        col = vcol if vcol is not None else fallback.get(idx, 0)
        cols.setdefault(int(col), []).append((idx, ch, box))

    out: List[Dict[str, Any]] = []

    for col_idx in sorted(cols.keys()):
        items = cols[col_idx]

        def sort_key(item: Tuple[int, Dict[str, Any], bbox_utils.BBox]):
            idx0, ch0, b0 = item
            return (float(b0.y0), float(b0.x0), int(idx0))

        items.sort(key=sort_key)

        i = 0
        while i < len(items):
            idx, ch, box = items[i]
            text = get_text(ch)

            # If this isn't a bullet start, pass-through.
            if not looks_like_bullet(text):
                out.append(ch)
                i += 1
                continue

            # Start a stitched group from this bullet chunk.
            merged = copy.deepcopy(ch)
            merged_text = text
            merged_box = box
            merged_from = [str(ch.get("id"))]

            j = i + 1
            while j < len(items):
                n_idx, n_ch, n_box = items[j]
                n_text = get_text(n_ch)

                # Stop at the next bullet.
                if looks_like_bullet(n_text):
                    break

                gap = merged_box.vertical_gap_to(n_box)
                overlap = merged_box.horizontal_overlap_ratio(n_box)

                if gap > float(max_gap) or overlap < float(min_overlap):
                    break

                # Merge
                merged_text = merge_text(merged_text, n_text)
                merged_box = merged_box.union(n_box)
                merged_from.append(str(n_ch.get("id")))
                j += 1

            set_text(merged, merged_text)
            bbox_utils.write_bbox(merged, merged_box, bbox_format="dict", sync_top_level=True)

            meta = merged.get("metadata")
            if not isinstance(meta, dict):
                meta = {}
                merged["metadata"] = meta

            meta["postmerge_stitched"] = True
            meta["postmerge_stitched_from_ids"] = merged_from
            meta["postmerge_column_index"] = int(col_idx)

            out.append(merged)
            i = j

    # Keep page set (ensure correct type)
    for ch in out:
        ch["page"] = page_num

    return out


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Stitch split notes after a merge step.")
    ap.add_argument("--input", required=True, help="Input JSON")
    ap.add_argument("--output", required=True, help="Output JSON")
    ap.add_argument("--only-page", type=int, default=None, help="Only process this page")
    ap.add_argument("--max-gap", type=float, default=28.0, help="Max vertical gap (PDF units)")
    ap.add_argument("--min-overlap", type=float, default=0.60, help="Min horizontal overlap ratio")
    ap.add_argument(
        "--x0-tolerance",
        type=float,
        default=100.0,
        help="Fallback column clustering tolerance (PDF units)",
    )
    return ap.parse_args()


def _load_root(in_path: Path) -> Tuple[Any, List[Dict[str, Any]]]:
    root = json.loads(in_path.read_text(encoding="utf-8"))
    if isinstance(root, dict) and isinstance(root.get("chunks"), list):
        return root, [c for c in root["chunks"] if isinstance(c, dict)]
    if isinstance(root, list):
        return root, [c for c in root if isinstance(c, dict)]
    raise ValueError("Expected JSON root to be either a list or a {'chunks': [...]} dict")


def main() -> int:
    args = parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)

    if not in_path.exists():
        raise FileNotFoundError(
            f"Input stage file not found: {in_path}\n"
            "Upstream stage likely failed. Fix the root cause, not this tool."
        )

    root, chunks = _load_root(in_path)

    # Build per-page items (only those we will process)
    pages: Dict[int, List[Tuple[int, Dict[str, Any], bbox_utils.BBox]]] = {}
    for idx, ch in enumerate(chunks):
        p = get_page_num(ch)
        if args.only_page is not None and p != args.only_page:
            continue
        box = bbox_utils.extract_bbox(ch)
        if box is None:
            # Non-geometry chunks are passed through untouched.
            continue
        pages.setdefault(p, []).append((idx, ch, box))

    out_chunks: List[Dict[str, Any]] = []

    # Pass-through pages we aren't processing (if only-page used)
    if args.only_page is not None:
        for ch in chunks:
            if get_page_num(ch) != args.only_page:
                out_chunks.append(ch)

    for p in sorted(pages.keys()):
        stitched = stitch_page(
            page_num=p,
            page_items=pages[p],
            max_gap=float(args.max_gap),
            min_overlap=float(args.min_overlap),
            x0_tolerance=float(args.x0_tolerance),
        )
        out_chunks.extend(stitched)

    # Preserve wrapper shape
    if isinstance(root, dict):
        root2 = copy.deepcopy(root)
        root2["chunks"] = out_chunks
        out_obj: Any = root2
    else:
        out_obj = out_chunks

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_obj, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[OK] Wrote {len(out_chunks)} chunks to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
