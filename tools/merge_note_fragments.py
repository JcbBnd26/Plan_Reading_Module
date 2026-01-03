#!/usr/bin/env python3
"""
tools/merge_note_fragments.py

Stage 3: merge "note" fragments into larger note groups (per-column).

Primary goal (stability milestone)
---------------------------------
This tool must ALWAYS:
- read input JSON
- write output JSON
- never "silently succeed" without producing output

It also fixes two correctness drifts:
1) BBox schema drift:
   - accepts dict/list bbox, writes canonical dict bbox
2) Header-vs-note overlap bug:
   - never merges notes across header regions
   - optionally excludes note candidates that overlap header bboxes too much

What it merges (conservative)
-----------------------------
- Only merges chunks of type "note_group" on the target page.
- Does NOT merge headers.
- Does NOT merge across columns (columns inferred by clustering x0).

If you later want to merge additional types, add them to MERGE_TYPES below.
"""

from __future__ import annotations

import argparse
import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import bbox_utils


# Conservative: only merge these types
MERGE_TYPES = {"note_group"}


# -----------------------------------------------------------------------------
# JSON I/O (atomic writes)
# -----------------------------------------------------------------------------


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_json(path: Path, obj: Any) -> None:
    """
    Write JSON atomically to avoid half-written stage files on crash.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _get_chunks(root: Any) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Returns (chunks, wrapper_dict_or_None). If wrapper is not None, caller should write back wrapper["chunks"].
    """
    if isinstance(root, dict) and isinstance(root.get("chunks"), list):
        return root["chunks"], root
    if isinstance(root, list):
        # legacy list root
        return [c for c in root if isinstance(c, dict)], None
    raise ValueError("Unsupported JSON root. Expected {'chunks':[...]} or a list of chunks.")


# -----------------------------------------------------------------------------
# Header detection
# -----------------------------------------------------------------------------


def _is_header(ch: Dict[str, Any]) -> bool:
    """
    Robust header detection:
    - explicit type == "header"
    - or metadata["header_candidate"] == True
    """
    if str(ch.get("type", "")).lower() == "header":
        return True
    md = ch.get("metadata")
    if isinstance(md, dict) and md.get("header_candidate") is True:
        return True
    return False


# -----------------------------------------------------------------------------
# Column clustering
# -----------------------------------------------------------------------------


def _cluster_by_x0(items: List[Tuple[int, Dict[str, Any], bbox_utils.BBox]], x_bin_tol: float) -> Dict[int, int]:
    """
    Cluster items into columns using their x0 coordinate.

    Returns:
      dict: item_index_in_items_list -> column_index
    """
    if not items:
        return {}

    xs: List[Tuple[int, float]] = []
    for i, _, b in items:
        xs.append((i, float(b.x0)))
    xs.sort(key=lambda t: t[1])

    clusters: List[Dict[str, Any]] = []
    for idx, x0 in xs:
        if not clusters:
            clusters.append({"rep": x0, "members": [idx], "xs": [x0]})
            continue
        last = clusters[-1]
        if abs(x0 - float(last["rep"])) <= float(x_bin_tol):
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
# Merge logic
# -----------------------------------------------------------------------------


def _has_header_between(
    headers: List[bbox_utils.BBox],
    a: bbox_utils.BBox,
    b: bbox_utils.BBox,
    *,
    min_h_overlap: float = 0.10,
) -> bool:
    """
    True if any header bbox sits between a (above) and b (below) vertically AND overlaps horizontally.

    This is the "never wrap a header inside a merged note" guard.
    """
    # Require b below a in y-order for the between check.
    if b.y0 < a.y1:
        return False

    for hb in headers:
        # Header must live in the vertical gap between the two notes.
        if hb.y0 >= a.y1 and hb.y1 <= b.y0:
            # Must overlap horizontally with BOTH (loosely).
            if hb.horizontal_overlap_ratio(a) >= min_h_overlap and hb.horizontal_overlap_ratio(b) >= min_h_overlap:
                return True
    return False


def _merge_text(parts: List[str]) -> str:
    parts2 = []
    for p in parts:
        p = (p or "").strip()
        if p:
            parts2.append(p)
    # Keep newlines to preserve "note-like" formatting.
    return "\n".join(parts2)


@dataclass
class MergeStats:
    candidates: int = 0
    excluded_under_headers: int = 0
    merged_groups: int = 0
    merged_chunks_removed: int = 0


def merge_note_fragments(
    root: Any,
    *,
    target_page: int,
    max_gap: float,
    min_overlap: float,
    x_bin_tol: float,
    x_shift_hard: float,
    exclude_under_headers: bool,
    header_overlap_thresh: float,
    debug: bool = False,
) -> Tuple[Any, MergeStats]:
    chunks, wrapper = _get_chunks(root)
    page_str = str(target_page)

    # Collect header bboxes on target page
    header_boxes: List[bbox_utils.BBox] = []
    for ch in chunks:
        if str(ch.get("page")) != page_str:
            continue
        if not _is_header(ch):
            continue
        hb = bbox_utils.extract_bbox(ch)
        if hb:
            header_boxes.append(hb)

    # Collect merge candidates (note_group only, target page, has bbox)
    candidates: List[Tuple[int, Dict[str, Any], bbox_utils.BBox]] = []
    for idx, ch in enumerate(chunks):
        if str(ch.get("page")) != page_str:
            continue
        if _is_header(ch):
            continue
        if str(ch.get("type", "")).lower() not in MERGE_TYPES:
            continue

        box = bbox_utils.extract_bbox(ch)
        if box is None:
            continue
        candidates.append((idx, ch, box))

    stats = MergeStats(candidates=len(candidates))

    # Exclude candidates that overlap headers "too much" (but keep them as standalone chunks)
    mergeable: List[Tuple[int, Dict[str, Any], bbox_utils.BBox]] = []
    for idx, ch, box in candidates:
        if exclude_under_headers and header_boxes:
            if any(bbox_utils.overlap_ratio(box, hb) >= float(header_overlap_thresh) for hb in header_boxes):
                stats.excluded_under_headers += 1
                md = ch.get("metadata")
                if not isinstance(md, dict):
                    md = {}
                    ch["metadata"] = md
                md["merge_excluded_under_header"] = True
                md["merge_header_overlap_thresh"] = float(header_overlap_thresh)
                # Still normalize bbox schema
                bbox_utils.write_bbox(ch, box, bbox_format="dict", sync_top_level=True)
                continue
        mergeable.append((idx, ch, box))

    # Column assignment
    col_map = _cluster_by_x0(mergeable, x_bin_tol=float(x_bin_tol))

    # Build per-column lists
    cols: Dict[int, List[Tuple[int, Dict[str, Any], bbox_utils.BBox]]] = {}
    for idx, ch, box in mergeable:
        # idx is original chunk index; use it for deterministic tie-breaking.
        col = col_map.get(idx, 0)
        cols.setdefault(int(col), []).append((idx, ch, box))

    # Walk each column and merge adjacent chunks
    skip_ids: set[str] = set()

    for col_idx in sorted(cols.keys()):
        items = cols[col_idx]

        def sort_key(item: Tuple[int, Dict[str, Any], bbox_utils.BBox]):
            idx0, ch0, b0 = item
            return (float(b0.y0), float(b0.x0), int(idx0))

        items.sort(key=sort_key)

        i = 0
        while i < len(items):
            rep_idx, rep_ch, rep_box = items[i]
            group = [(rep_idx, rep_ch, rep_box)]
            group_box = rep_box

            j = i + 1
            while j < len(items):
                n_idx, n_ch, n_box = items[j]

                # Merge gates
                gap = group_box.vertical_gap_to(n_box)
                if gap > float(max_gap):
                    break

                if group_box.horizontal_overlap_ratio(n_box) < float(min_overlap):
                    break

                # Hard x-shift break (prevents weird cross-indent merges)
                if abs(float(n_box.x0) - float(group_box.x0)) > float(x_shift_hard):
                    break

                # Header barrier: never merge across a header sitting between them.
                if header_boxes and _has_header_between(header_boxes, group_box, n_box):
                    break

                # OK merge
                group.append((n_idx, n_ch, n_box))
                group_box = group_box.union(n_box)
                j += 1

            # Apply merge to representative chunk
            if len(group) == 1:
                # Still normalize bbox schema for stability.
                bbox_utils.write_bbox(rep_ch, rep_box, bbox_format="dict", sync_top_level=True)
            else:
                stats.merged_groups += 1

                texts: List[str] = []
                ids: List[str] = []
                for g_idx, g_ch, g_box in group:
                    ids.append(str(g_ch.get("id")))
                    t = g_ch.get("content") or g_ch.get("text") or ""
                    texts.append(str(t))

                merged_text = _merge_text(texts)

                # Representative chunk gets updated in-place.
                rep_ch["type"] = "note_group"
                rep_ch["content"] = merged_text
                rep_ch["text"] = merged_text
                bbox_utils.write_bbox(rep_ch, group_box, bbox_format="dict", sync_top_level=True)

                md = rep_ch.get("metadata")
                if not isinstance(md, dict):
                    md = {}
                    rep_ch["metadata"] = md

                md["merged"] = True
                md["merged_from_ids"] = ids
                md["merged_count"] = len(group)
                md["merge_column_index"] = int(col_idx)
                md["merge_params"] = {
                    "max_gap": float(max_gap),
                    "min_overlap": float(min_overlap),
                    "x_bin_tol": float(x_bin_tol),
                    "x_shift_hard": float(x_shift_hard),
                    "exclude_under_headers": bool(exclude_under_headers),
                    "header_overlap_thresh": float(header_overlap_thresh),
                }

                # All other chunks in group are removed (skipped) from output.
                for g_idx, g_ch, _ in group[1:]:
                    skip_ids.add(str(g_ch.get("id")))
                    stats.merged_chunks_removed += 1

            i = j

    # Build output chunks list (preserve original ordering, minus skipped chunks)
    out_chunks: List[Dict[str, Any]] = []
    for ch in chunks:
        cid = str(ch.get("id"))
        if cid in skip_ids:
            continue
        out_chunks.append(ch)

    if wrapper is not None:
        wrapper2 = copy.deepcopy(wrapper)
        wrapper2["chunks"] = out_chunks
        return wrapper2, stats

    # Legacy list-root
    return out_chunks, stats


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--page", type=int, required=True)

    ap.add_argument("--max-gap", type=float, default=34.0)
    ap.add_argument("--min-overlap", type=float, default=0.28)
    ap.add_argument("--x-bin-tol", type=float, default=140.0)
    ap.add_argument("--x-shift-hard", type=float, default=150.0)

    ap.add_argument("--exclude-under-headers", action="store_true", default=True)
    ap.add_argument("--header-overlap-thresh", type=float, default=0.35)

    ap.add_argument("--debug", action="store_true")
    return ap.parse_args()


def main() -> int:
    a = parse_args()
    inp = Path(a.input)
    out = Path(a.output)

    if not inp.exists():
        raise FileNotFoundError(f"Input JSON not found: {inp}")

    root = _load_json(inp)
    merged, stats = merge_note_fragments(
        root,
        target_page=int(a.page),
        max_gap=float(a.max_gap),
        min_overlap=float(a.min_overlap),
        x_bin_tol=float(a.x_bin_tol),
        x_shift_hard=float(a.x_shift_hard),
        exclude_under_headers=bool(a.exclude_under_headers),
        header_overlap_thresh=float(a.header_overlap_thresh),
        debug=bool(a.debug),
    )

    _atomic_write_json(out, merged)

    print(f"[OK] Wrote: {out}")
    if a.debug:
        print(
            "[INFO] merge_note_fragments:",
            f"candidates={stats.candidates}",
            f"excluded_under_headers={stats.excluded_under_headers}",
            f"merged_groups={stats.merged_groups}",
            f"removed={stats.merged_chunks_removed}",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
