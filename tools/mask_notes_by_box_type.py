#!/usr/bin/env python
"""
mask_notes_by_box_type.py

Stage 3a helper: mask (filter out) note chunks that fall inside certain
classified page boxes, such as the LEGEND and TITLE BLOCK on C0.1.

This script is intentionally conservative:

- It uses BOTH:
    1) Explicit chunk_indices from the page_box_classes JSON, and
    2) Geometric overlap between note chunk bboxes and the legend / title_block
       boxes for the target page(s).

- A note chunk is dropped if EITHER of these is true:
    * Its global index appears in any excluded box.chunk_indices
    * Its bbox overlaps an excluded box by at least --min-overlap-frac
      (fraction of the NOTE CHUNK area that lies inside the excluded box)

- Chunks with no bbox (missing x0/y0/x1/y1) are always kept, and we print how
  many there were so you can sanity‑check that nothing weird is happening.

Usage example (page 3 only, drop LEGEND + TITLE BLOCK):

    py tools\\mask_notes_by_box_type.py ^
        --notes-json exports\\all_pages_notes_sheetwide.json ^
        --box-classes-json exports\\page_box_classes_p3.json ^
        --out exports\\all_pages_notes_sheetwide_no_legend.json ^
        --exclude-types legend title_block ^
        --only-pages 3

Then run merge_note_fragments.py on the masked JSON and visualize with
visualize_notes_from_json.py to confirm the legend is gone.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple


@dataclass
class Box:
    page: int
    box_id: int
    bbox: Tuple[float, float, float, float]  # (x0, y0, x1, y1) in PDF coords
    box_type: str
    chunk_indices: List[int]


def load_notes(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if "chunks" not in data or not isinstance(data["chunks"], list):
        raise ValueError(f"Notes JSON at {path} must have a top-level 'chunks' list.")
    return data


def load_box_classes(path: Path, only_pages: Optional[Set[int]] = None) -> Dict[int, List[Box]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    pages_raw = data.get("pages") or {}
    boxes_by_page: Dict[int, List[Box]] = {}

    for page_key, page_data in pages_raw.items():
        try:
            page_num = int(page_key)
        except (TypeError, ValueError):
            # Skip weird keys
            continue

        if only_pages and page_num not in only_pages:
            continue

        page_boxes_raw = page_data.get("boxes") or []
        page_boxes: List[Box] = []
        for box in page_boxes_raw:
            try:
                box_id = int(box.get("id"))
            except (TypeError, ValueError):
                continue

            bbox_pdf = box.get("bbox_pdf")
            if (
                not isinstance(bbox_pdf, Sequence)
                or len(bbox_pdf) != 4
            ):
                continue

            x0, y0, x1, y1 = map(float, bbox_pdf)
            box_type = str(box.get("type") or "unknown")
            chunk_indices = box.get("chunk_indices") or []
            # Ensure indices are ints
            chunk_indices = [int(i) for i in chunk_indices if isinstance(i, int) or isinstance(i, float)]

            page_boxes.append(
                Box(
                    page=page_num,
                    box_id=box_id,
                    bbox=(x0, y0, x1, y1),
                    box_type=box_type,
                    chunk_indices=chunk_indices,
                )
            )

        if page_boxes:
            boxes_by_page[page_num] = page_boxes

    return boxes_by_page


def compute_overlap_frac(
    chunk_bbox: Tuple[float, float, float, float],
    box_bbox: Tuple[float, float, float, float],
) -> float:
    """
    Return the fraction of the CHUNK area that lies inside the box.
    0.0 means no overlap or degenerate geometry.
    """
    cx0, cy0, cx1, cy1 = chunk_bbox
    bx0, by0, bx1, by1 = box_bbox

    ix0 = max(cx0, bx0)
    iy0 = max(cy0, by0)
    ix1 = min(cx1, bx1)
    iy1 = min(cy1, by1)

    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0

    inter_area = (ix1 - ix0) * (iy1 - iy0)
    chunk_area = max((cx1 - cx0) * (cy1 - cy0), 0.0)
    if chunk_area <= 0:
        return 0.0

    return inter_area / chunk_area


def extract_chunk_bbox(chunk: Dict) -> Optional[Tuple[float, float, float, float]]:
    """Return (x0, y0, x1, y1) for a chunk.

    Supports both historical shapes:
      - top-level x0/y0/x1/y1
      - chunk["bbox"] as either a dict {x0,y0,x1,y1} or a 4-list [x0,y0,x1,y1]

    Returns None if no usable geometry exists.
    """
    # Preferred: bbox field
    b = chunk.get("bbox")
    if isinstance(b, dict):
        try:
            x0 = float(b.get("x0"))
            y0 = float(b.get("y0"))
            x1 = float(b.get("x1"))
            y1 = float(b.get("y1"))
            cx0, cx1 = sorted((x0, x1))
            cy0, cy1 = sorted((y0, y1))
            return (cx0, cy0, cx1, cy1)
        except Exception:
            pass

    if isinstance(b, (list, tuple)) and len(b) == 4:
        try:
            x0, y0, x1, y1 = map(float, b)
            cx0, cx1 = sorted((x0, x1))
            cy0, cy1 = sorted((y0, y1))
            return (cx0, cy0, cx1, cy1)
        except Exception:
            pass

    # Fallback: top-level x0/y0/x1/y1
    try:
        x0 = float(chunk["x0"])
        y0 = float(chunk["y0"])
        x1 = float(chunk["x1"])
        y1 = float(chunk["y1"])
    except Exception:
        return None

    cx0, cx1 = sorted((x0, x1))
    cy0, cy1 = sorted((y0, y1))
    return (cx0, cy0, cx1, cy1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mask (filter out) note chunks that fall inside selected box types.")
    parser.add_argument(
        "--notes-json",
        required=True,
        type=Path,
        help="Input notes JSON (from export_notes_json.py).",
    )
    parser.add_argument(
        "--box-classes-json",
        required=True,
        type=Path,
        help="Box classification JSON (from classify_page_boxes.py).",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output JSON path for masked notes.",
    )
    parser.add_argument(
        "--exclude-types",
        nargs="+",
        default=["legend", "title_block"],
        help="Box types whose interior note chunks should be removed.",
    )
    parser.add_argument(
        "--only-pages",
        nargs="*",
        type=int,
        default=None,
        help="Optional list of 1-based page numbers to process. "
             "If omitted, all pages in notes JSON are considered.",
    )
    parser.add_argument(
        "--min-overlap-frac",
        type=float,
        default=0.25,
        help="Minimum fraction of a note chunk's area that must lie inside an "
             "excluded box to be masked, when using geometry.",
    )

    args = parser.parse_args()

    notes_path: Path = args.notes_json
    boxes_path: Path = args.box_classes_json
    out_path: Path = args.out
    exclude_types: Set[str] = {t.lower() for t in args.exclude_types}
    only_pages: Optional[Set[int]] = set(args.only_pages) if args.only_pages else None
    min_overlap: float = float(args.min_overlap_frac)

    print(f"[info] Loading notes from {notes_path}")
    notes_data = load_notes(notes_path)
    chunks: List[Dict] = notes_data["chunks"]
    print(f"[info] Loaded {len(chunks)} chunks from notes JSON.")

    print(f"[info] Loading box classes from {boxes_path}")
    boxes_by_page_all = load_box_classes(boxes_path, only_pages=only_pages)

    # Filter boxes down to the requested types and pages
    exclude_boxes_by_page: Dict[int, List[Box]] = {}
    exclude_indices_by_page: Dict[int, Set[int]] = {}
    total_excluded_indices: Set[int] = set()

    for page, boxes in boxes_by_page_all.items():
        filtered = [b for b in boxes if b.box_type.lower() in exclude_types]
        if not filtered:
            continue
        exclude_boxes_by_page[page] = filtered
        page_indices: Set[int] = set()
        for b in filtered:
            page_indices.update(b.chunk_indices)
        if page_indices:
            exclude_indices_by_page[page] = page_indices
            total_excluded_indices.update(page_indices)

    if not exclude_boxes_by_page and not total_excluded_indices:
        print("[warn] No boxes of the requested types were found in the box-classes JSON.")
    else:
        pages_list = sorted(exclude_boxes_by_page.keys())
        print(f"[info] Using excluded boxes on {len(pages_list)} page(s): {pages_list}")
        print(f"[info] Total unique excluded chunk indices = {len(total_excluded_indices)}")

    # Masking loop
    masked_chunks: List[Dict] = []
    dropped_by_index = 0
    dropped_by_overlap_only = 0
    kept_with_no_bbox = 0

    for idx, ch in enumerate(chunks):
        page = int(ch.get("page", -1))

        # If only_pages is set and this chunk's page is not included, keep it verbatim.
        if only_pages and page not in only_pages:
            masked_chunks.append(ch)
            continue

        page_boxes = exclude_boxes_by_page.get(page, [])
        page_excluded_indices = exclude_indices_by_page.get(page, set())

        # Fast path: explicit index mapping
        index_match = idx in page_excluded_indices

        # Geometry path
        bbox = extract_chunk_bbox(ch)
        if bbox is None:
            # No geometry, keep it but track stats
            kept_with_no_bbox += 1
            if not index_match:
                masked_chunks.append(ch)
            else:
                # Index says drop, but no bbox data. We still trust the index.
                dropped_by_index += 1
            continue

        overlap_match = False
        if page_boxes:
            for box in page_boxes:
                overlap = compute_overlap_frac(bbox, box.bbox)
                if overlap >= min_overlap:
                    overlap_match = True
                    break

        should_drop = index_match or overlap_match

        if should_drop:
            if index_match:
                dropped_by_index += 1
            elif overlap_match:
                dropped_by_overlap_only += 1
            # Do not append
        else:
            masked_chunks.append(ch)

    print(f"[info] Masking completed. Dropped {dropped_by_index} chunk(s) via index mapping.")
    print(f"[info] Additionally dropped {dropped_by_overlap_only} chunk(s) via geometric overlap only.")
    print(f"[info] Kept {kept_with_no_bbox} chunk(s) that had no bbox data.")
    print(f"[info] Final chunk count: {len(masked_chunks)} (from {len(chunks)})")

    notes_data_out = dict(notes_data)
    notes_data_out["chunks"] = masked_chunks

    out_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[info] Writing masked notes to {out_path}")
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(notes_data_out, f, ensure_ascii=False, indent=2)

    print("[info] Done.")


if __name__ == "__main__":
    main()
