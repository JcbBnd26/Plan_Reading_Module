#!/usr/bin/env python
"""
classify_page_boxes.py

Stage 2 of shape-based OCR:

Given:
  1) Box candidates from detect_page_boxes.py
  2) OCR chunks JSON (all_pages_notes_sheetwide.json style)

Classify each rectangular frame on each page as:
  - page_border
  - title_block
  - sheet_info   (small sheet name / notes band)
  - legend       (header + body)
  - data_table
  - location_map
  - notes_box
  - callout
  - unknown

We do NOT mutate the OCR JSON. Instead, we output a separate
classification JSON that later stages can use to assign box_type
to each chunk.

CLI example:

  python tools/classify_page_boxes.py \
    --boxes-json exports/page_boxes_p3.json \
    --ocr-json exports/all_pages_notes_sheetwide.json \
    --out exports/page_box_classes_p3.json
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------
# Basic geometry helpers
# ---------------------------------------------------------------------


@dataclass
class Box:
    """
    Axis-aligned rectangle in PDF coordinates.
    """

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def w(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def h(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2.0

    def contains_point(self, x: float, y: float, margin: float = 0.0) -> bool:
        """
        Check whether a point lies inside the box (with optional margin).
        """
        return (
            x >= self.x0 + margin
            and x <= self.x1 - margin
            and y >= self.y0 + margin
            and y <= self.y1 - margin
        )

    def contains_box(self, other: "Box", margin: float = 0.0) -> bool:
        """
        Check whether 'other' is fully inside this box (with optional margin).
        """
        return (
            other.x0 >= self.x0 + margin
            and other.y0 >= self.y0 + margin
            and other.x1 <= self.x1 - margin
            and other.y1 <= self.y1 - margin
        )


@dataclass
class Chunk:
    """
    Minimal representation of an OCR chunk we care about.
    """

    idx: int
    page: int
    bbox: Box
    text: str


@dataclass
class BoxCandidate:
    """
    Box plus classification metadata.
    """

    id: int
    bbox: Box
    area_frac: float
    is_page_border_hint: bool

    parent_id: Optional[int] = None
    children_ids: List[int] = field(default_factory=list)

    box_type: str = "unknown"
    header_text: str = ""
    text_sample: str = ""
    chunk_indices: List[int] = field(default_factory=list)


# ---------------------------------------------------------------------
# OCR JSON helpers
# ---------------------------------------------------------------------


def parse_bbox(raw: Any) -> Box:
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        x0, y0, x1, y1 = raw
        return Box(float(x0), float(y0), float(x1), float(y1))
    if isinstance(raw, dict):
        return Box(
            float(raw.get("x0", 0.0)),
            float(raw.get("y0", 0.0)),
            float(raw.get("x1", 0.0)),
            float(raw.get("y1", 0.0)),
        )
    raise ValueError(f"Unsupported bbox format in OCR JSON: {raw!r}")


def get_text(d: Dict[str, Any]) -> str:
    # Prefer 'content' (our sheetwide format), fall back to 'text'
    if "content" in d and isinstance(d["content"], str):
        return d["content"]
    if "text" in d and isinstance(d["text"], str):
        return d["text"]
    return ""


def load_chunks_by_page(ocr_path: str) -> Dict[int, List[Chunk]]:
    """
    Load OCR chunks from a sheetwide JSON into a per-page dict.
    """
    with open(ocr_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    chunks_by_page: Dict[int, List[Chunk]] = {}

    for idx, d in enumerate(raw.get("chunks", [])):
        page = int(d.get("page", 0))
        bbox = parse_bbox(d.get("bbox"))
        text = get_text(d)
        chunk = Chunk(idx=idx, page=page, bbox=bbox, text=text)
        chunks_by_page.setdefault(page, []).append(chunk)

    return chunks_by_page


# ---------------------------------------------------------------------
# Box JSON helpers
# ---------------------------------------------------------------------


def load_boxes_by_page(
    boxes_path: str,
    pages_filter: Optional[List[int]] = None,
) -> Dict[int, Dict[str, Any]]:
    """
    Load box candidates from detect_page_boxes.py JSON.

    Returns per-page dict:

      {
        page_num: {
          "boxes": [BoxCandidate, ...],
          "min_x": float,
          "max_x": float,
          "min_y": float,
          "max_y": float,
        },
        ...
      }
    """
    with open(boxes_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    pages_raw = raw.get("pages", {})
    result: Dict[int, Dict[str, Any]] = {}

    for page_key, page_info in pages_raw.items():
        page_num = int(page_key)
        if pages_filter is not None and page_num not in pages_filter:
            continue

        boxes_list = page_info.get("boxes", [])
        candidates: List[BoxCandidate] = []

        min_x = float("inf")
        max_x = float("-inf")
        min_y = float("inf")
        max_y = float("-inf")

        for b in boxes_list:
            bid = int(b.get("id"))
            x0, y0, x1, y1 = [float(v) for v in b.get("bbox_pdf", [0, 0, 0, 0])]
            area_frac = float(b.get("area_frac", 0.0))
            border_hint = bool(b.get("is_page_border_hint", False))

            box = Box(x0, y0, x1, y1)
            candidates.append(
                BoxCandidate(
                    id=bid,
                    bbox=box,
                    area_frac=area_frac,
                    is_page_border_hint=border_hint,
                )
            )

            min_x = min(min_x, box.x0)
            max_x = max(max_x, box.x1)
            min_y = min(min_y, box.y0)
            max_y = max(max_y, box.y1)

        if not candidates:
            continue

        result[page_num] = {
            "boxes": candidates,
            "min_x": min_x,
            "max_x": max_x,
            "min_y": min_y,
            "max_y": max_y,
        }

    return result


# ---------------------------------------------------------------------
# Box hierarchy (parent/children)
# ---------------------------------------------------------------------


def assign_box_hierarchy(page_data: Dict[str, Any]) -> None:
    """
    For each box, determine its parent box (if any) and children.

    Parent = smallest-area box that fully contains this box.

    Tolerance is scaled per candidate box to be less brittle than
    a global page-size tolerance.
    """
    boxes: List[BoxCandidate] = page_data["boxes"]
    if not boxes:
        return

    # Reset children lists (in case of reuse)
    for b in boxes:
        b.children_ids.clear()
        b.parent_id = None

    areas = {b.id: b.bbox.w * b.bbox.h for b in boxes}
    id_to_box = {b.id: b for b in boxes}

    for b in boxes:
        best_parent_id: Optional[int] = None
        best_parent_area: Optional[float] = None

        for candidate in boxes:
            if candidate.id == b.id:
                continue

            # Parent must be strictly larger area
            if areas[candidate.id] <= areas[b.id]:
                continue

            # Per-candidate tolerance based on its size
            tol = 0.01 * min(candidate.bbox.w, candidate.bbox.h)

            if not candidate.bbox.contains_box(b.bbox, margin=tol):
                continue

            area_c = areas[candidate.id]
            if best_parent_area is None or area_c < best_parent_area:
                best_parent_area = area_c
                best_parent_id = candidate.id

        b.parent_id = best_parent_id
        if best_parent_id is not None:
            id_to_box[best_parent_id].children_ids.append(b.id)


# ---------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------


def classify_boxes_for_page(
    page_num: int,
    page_data: Dict[str, Any],
    page_chunks: List[Chunk],
) -> None:
    """
    Assign box_type/header_text/text_sample/chunk_indices for each box on a page.

    Flow:
      1) Attach chunks to boxes by point-in-rect.
      2) First-pass classification (page_border, title_block, legend header, etc.).
      3) Second pass: promote large boxes under a legend header to legend "body".
    """
    boxes: List[BoxCandidate] = page_data["boxes"]
    if not boxes:
        return

    # Page extents and relative scale
    min_x = page_data["min_x"]
    max_x = page_data["max_x"]
    min_y = page_data["min_y"]
    max_y = page_data["max_y"]
    page_w = max_x - min_x if max_x > min_x else 1.0
    page_h = max_y - min_y if max_y > min_y else 1.0

    # Index chunks by idx for quick lookup
    chunks_by_idx: Dict[int, Chunk] = {c.idx: c for c in page_chunks}

    # Attach chunks to boxes (by center point)
    for b in boxes:
        b.chunk_indices.clear()

    for ch in page_chunks:
        cx = ch.bbox.cx
        cy = ch.bbox.cy
        for b in boxes:
            if b.bbox.contains_point(cx, cy, margin=0.0):
                b.chunk_indices.append(ch.idx)

    # First-pass classification
    for b in boxes:
        # Gather text inside box
        texts: List[str] = []
        header_candidates: List[Chunk] = []

        for idx in b.chunk_indices:
            ch = chunks_by_idx.get(idx)
            if ch is None:
                continue
            if ch.text:
                texts.append(ch.text)
                header_candidates.append(ch)

        header_candidates.sort(key=lambda c: c.bbox.y0)
        header_text = " ".join(c.text for c in header_candidates[:3] if c.text).strip()
        all_text = " ".join(texts).strip()

        b.header_text = header_text
        b.text_sample = all_text[:200] if all_text else ""

        header_u = header_text.upper()
        all_u = all_text.upper()

        # Geometry features
        bw = b.bbox.w
        bh = b.bbox.h
        aspect = bw / bh if bh > 0 else 999.0
        cx = b.bbox.cx
        cy = b.bbox.cy
        cx_frac = (cx - min_x) / page_w
        cy_frac = (cy - min_y) / page_h

        near_right = cx_frac > 0.80
        tall_skinny = aspect < 0.6 and bh > 0.4 * page_h

        # ------------------------------------------------------------------
        # Heuristic rules (ordered)
        # ------------------------------------------------------------------

        # 1) Page border: very large / explicit hint
        if b.area_frac >= 0.80 or b.is_page_border_hint:
            b.box_type = "page_border"
            continue

        # 2) Title block (info bar): tall, skinny, near right edge
        # Detect the vertical sidebar column common on plan sheets.
        is_tall = b.bbox.h >= 0.5 * page_h
        is_skinny = (b.bbox.w / b.bbox.h) <= 0.6
        is_right_edge = (b.bbox.x1 / page_w) >= 0.92 or (b.bbox.cx / page_w) >= 0.85
        if is_tall and is_skinny and is_right_edge and 0.02 <= b.area_frac <= 0.15:
            b.box_type = "title_block"
            continue


        # 2.5) Sheet info band: "SHEET NAME" + "NOTES & LEGEND" inside title column
        sheet_info_cue = (
            ("SHEET NAME" in header_u or "SHEET NAME" in all_u)
            and (
                "NOTES & LEGEND" in header_u
                or "NOTES & LEGEND" in all_u
                or "NOTES AND LEGEND" in header_u
                or "NOTES AND LEGEND" in all_u
            )
        )
        if sheet_info_cue and near_right:
            b.box_type = "sheet_info"
            continue

        # 3) Legend header: text cue "LEGEND" (small-ish, usually)
        if "LEGEND" in header_u or " LEGEND" in all_u:
            b.box_type = "legend"
            continue

        # 4) Location map
        if "LOCATION MAP" in all_u or "STATE OF" in all_u:
            b.box_type = "location_map"
            continue

        # 5) Explicit tables
        if "TABLE" in header_u or "TABLE" in all_u or "QTY" in all_u:
            b.box_type = "data_table"
            continue

        # 6) Note box (e.g., "WATER DETAIL NOTES")
        if "NOTES" in header_u:
            b.box_type = "notes_box"
            continue

        # 7) Small all-caps callouts
        if (
            b.area_frac < 0.01
            and all_text
            and len(all_text) < 80
            and all_text.upper() == all_text
        ):
            b.box_type = "callout"
            continue

        # 8) Fallback
        b.box_type = "unknown"

    # ------------------------------------------------------------------
    # Second pass: promote legend "body" boxes under LEGEND header
    # ------------------------------------------------------------------

    legend_headers = [b for b in boxes if b.box_type == "legend"]

    for header in legend_headers:
        for b in boxes:
            if b is header:
                continue
            # Only promote boxes that are currently unknown (avoid clobbering
            # things we've confidently typed, like title_block or callouts).
            if b.box_type != "unknown":
                continue

            # Big enough to be a legend body
            if b.area_frac < 0.01:
                continue

            # Must be below (or barely overlapping) the legend header vertically
            # Allow a little negative gap in case of slight overlap.
            if b.bbox.y0 < header.bbox.y1 - 0.05 * page_h:
                continue

            # Strong horizontal overlap with the header
            overlap_x = min(header.bbox.x1, b.bbox.x1) - max(header.bbox.x0, b.bbox.x0)
            if overlap_x <= 0:
                continue
            overlap_ratio = overlap_x / max(1.0, min(header.bbox.w, b.bbox.w))
            if overlap_ratio < 0.6:
                continue

            # Looks like the main legend body
            b.box_type = "legend"

            # Optional: promote unknown children of this box as legend too
            for child_id in b.children_ids:
                child = next((x for x in boxes if x.id == child_id), None)
                if child is not None and child.box_type == "unknown":
                    child.box_type = "legend"


# ---------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify rectangular frame boxes on PDF pages using "
        "OCR text + geometry (legend / title_block / tables / etc.)."
    )
    parser.add_argument(
        "--boxes-json",
        required=True,
        help="Box candidates JSON from detect_page_boxes.py",
    )
    parser.add_argument(
        "--ocr-json",
        required=True,
        help="OCR chunks JSON (e.g. exports/all_pages_notes_sheetwide.json)",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output JSON path for classified boxes",
    )
    parser.add_argument(
        "--pages",
        nargs="*",
        type=int,
        default=None,
        help="Optional list of 1-based page numbers to process "
        "(default: all pages present in boxes-json).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    pages_filter = args.pages if args.pages else None

    # Load inputs
    boxes_by_page = load_boxes_by_page(args.boxes_json, pages_filter=pages_filter)
    chunks_by_page = load_chunks_by_page(args.ocr_json)

    # Attach hierarchy + classifications
    for page_num, page_data in boxes_by_page.items():
        assign_box_hierarchy(page_data)
        page_chunks = chunks_by_page.get(page_num, [])
        classify_boxes_for_page(page_num, page_data, page_chunks)

    # Build output structure
    out: Dict[str, Any] = {
        "boxes_source": args.boxes_json,
        "ocr_source": args.ocr_json,
        "pages": {},
    }

    for page_num, page_data in boxes_by_page.items():
        page_entry: Dict[str, Any] = {
            "min_x": page_data["min_x"],
            "max_x": page_data["max_x"],
            "min_y": page_data["min_y"],
            "max_y": page_data["max_y"],
            "boxes": [],
        }

        for b in page_data["boxes"]:
            box_dict = {
                "id": b.id,
                "bbox_pdf": [b.bbox.x0, b.bbox.y0, b.bbox.x1, b.bbox.y1],
                "area_frac": b.area_frac,
                "parent_id": b.parent_id,
                "children_ids": b.children_ids,
                "type": b.box_type,
                "header_text": b.header_text,
                "text_sample": b.text_sample,
                "chunk_indices": b.chunk_indices,
            }
            page_entry["boxes"].append(box_dict)

        out["pages"][str(page_num)] = page_entry

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print(f"Wrote classified box data to {args.out}")


if __name__ == "__main__":
    main()
