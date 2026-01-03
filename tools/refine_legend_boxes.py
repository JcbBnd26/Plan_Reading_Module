#!/usr/bin/env python
"""
refine_legend_boxes.py

Post-process page_box_classes JSON to clean up and consolidate panels:

  * Merge vertically stacked boxes of selected types
      - e.g. legend header + legend body -> one legend column
      - e.g. stacked pieces of the project_info_panel (title_block)

  * Reconstruct a unified project_info_panel (the tall right-hand sidebar)
    even when some internal boxes were not detected by the box detector.

Inputs
------
- Classified boxes JSON from tools/classify_page_boxes.py

Outputs
-------
- A refined JSON with:
    - merged legend columns
    - merged project_info_panel (type = "title_block")
    - fixed parent_id / children_ids

Usage example (page 3)
----------------------
py tools\\refine_legend_boxes.py ^
  --input exports\\page_box_classes_p3.json ^
  --output exports\\page_box_classes_p3_refined_projectpanel.json ^
  --pages 3 ^
  --max-area-frac 0.2
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Set


# ---------------------------------------------------------------------------
# Basic geometry helpers
# ---------------------------------------------------------------------------


@dataclass
class BBox:
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
    def area(self) -> float:
        return self.w * self.h

    def to_list(self) -> List[float]:
        return [self.x0, self.y0, self.x1, self.y1]


def bbox_from_list(vals: List[float]) -> BBox:
    if len(vals) != 4:
        raise ValueError(f"Expected 4 values for bbox, got: {vals!r}")
    return BBox(float(vals[0]), float(vals[1]), float(vals[2]), float(vals[3]))


def bbox_union(a: BBox, b: BBox) -> BBox:
    return BBox(
        x0=min(a.x0, b.x0),
        y0=min(a.y0, b.y0),
        x1=max(a.x1, b.x1),
        y1=max(a.y1, b.y1),
    )


def horizontal_iou(a: BBox, b: BBox) -> float:
    """
    1D IoU along the X axis, used to test "same column" alignment.
    """
    inter_x0 = max(a.x0, b.x0)
    inter_x1 = min(a.x1, b.x1)
    if inter_x1 <= inter_x0:
        return 0.0
    inter = inter_x1 - inter_x0
    denom = max(1.0, min(a.w, b.w))
    return inter / denom


def vertical_gap(a: BBox, b: BBox) -> float:
    """
    Vertical gap between two boxes (positive when stacked with a gap).
    Returns 0 if they overlap vertically.
    """
    top, bottom = (a, b) if a.y0 <= b.y0 else (b, a)
    if bottom.y0 >= top.y1:
        return bottom.y0 - top.y1
    return 0.0


# ---------------------------------------------------------------------------
# Core merge logic
# ---------------------------------------------------------------------------


def collect_candidates(
    boxes: List[Dict[str, Any]],
    merge_type: str,
    min_area_frac: float,
    max_area_frac: float,
) -> List[Dict[str, Any]]:
    """
    Filter boxes of a given type in the desired area fraction band.
    """
    candidates: List[Dict[str, Any]] = []
    for b in boxes:
        if b.get("type") != merge_type:
            continue
        area_frac = float(b.get("area_frac", 0.0))
        if area_frac < min_area_frac or area_frac > max_area_frac:
            continue
        candidates.append(b)
    return candidates


def merge_stacked_for_type(
    page_key: str,
    page_data: Dict[str, Any],
    merge_type: str,
    min_area_frac: float,
    max_area_frac: float,
    min_horizontal_iou: float,
    max_vertical_gap: float,
) -> Tuple[int, Dict[int, int]]:
    """
    Merge vertically stacked boxes of a single type on one page.

    Returns:
      (num_merges, id_map)

    id_map maps old_id -> anchor_id for merged-away boxes, used later to
    fix parent/children references.
    """
    boxes: List[Dict[str, Any]] = page_data["boxes"]

    candidates = collect_candidates(boxes, merge_type, min_area_frac, max_area_frac)
    if not candidates:
        return 0, {}

    candidates = sorted(
        candidates,
        key=lambda b: (float(b["bbox_pdf"][1]), float(b["bbox_pdf"][0])),
    )

    removed_ids: Set[int] = set()
    id_map: Dict[int, int] = {}
    merges = 0

    # Page area for area_frac recompute
    min_x = float(page_data.get("min_x", 0.0))
    max_x = float(page_data.get("max_x", 1.0))
    min_y = float(page_data.get("min_y", 0.0))
    max_y = float(page_data.get("max_y", 1.0))
    page_area = max(1.0, (max_x - min_x) * (max_y - min_y))

    for anchor in candidates:
        anchor_id = int(anchor["id"])
        if anchor_id in removed_ids:
            continue

        anchor_bbox = bbox_from_list(anchor["bbox_pdf"])

        for other in candidates:
            other_id = int(other["id"])
            if other_id == anchor_id or other_id in removed_ids:
                continue

            other_bbox = bbox_from_list(other["bbox_pdf"])

            x_iou = horizontal_iou(anchor_bbox, other_bbox)
            gap_y = vertical_gap(anchor_bbox, other_bbox)

            if x_iou < min_horizontal_iou:
                continue
            if gap_y > max_vertical_gap:
                continue

            merged_bbox = bbox_union(anchor_bbox, other_bbox)
            anchor["bbox_pdf"] = merged_bbox.to_list()
            anchor_bbox = merged_bbox

            a_chunks = list(anchor.get("chunk_indices") or [])
            o_chunks = list(other.get("chunk_indices") or [])
            anchor["chunk_indices"] = sorted(set(a_chunks + o_chunks))

            anchor["area_frac"] = merged_bbox.area / page_area

            removed_ids.add(other_id)
            id_map[other_id] = anchor_id
            merges += 1

            print(
                f"[merge] page={page_key} type={merge_type} "
                f"anchor={anchor_id} other={other_id} "
                f"x_iou={x_iou:.3f} gap_y={gap_y:.2f} "
                f"anchor_bbox={anchor_bbox.to_list()} other_bbox={other_bbox.to_list()}"
            )

    if merges:
        page_data["boxes"] = [b for b in boxes if int(b["id"]) not in removed_ids]

    return merges, id_map


def apply_id_map_to_page(page_data: Dict[str, Any], id_map: Dict[int, int]) -> None:
    """
    Fix parent_id / children_ids after merges using id_map.
    """
    if not id_map:
        return

    boxes: List[Dict[str, Any]] = page_data["boxes"]
    new_children: Dict[int, List[int]] = {}

    for b in boxes:
        bid = int(b["id"])

        parent_id = b.get("parent_id")
        if parent_id is not None:
            parent_id = int(parent_id)
            if parent_id in id_map:
                parent_id = id_map[parent_id]
            if parent_id == bid:
                parent_id = None
            b["parent_id"] = parent_id

        b["children_ids"] = []

    for b in boxes:
        parent_id = b.get("parent_id")
        if parent_id is None:
            continue
        pid = int(parent_id)
        new_children.setdefault(pid, []).append(int(b["id"]))

    for b in boxes:
        bid = int(b["id"])
        if bid in new_children:
            b["children_ids"] = sorted(set(new_children[bid]))


# ---------------------------------------------------------------------------
# Project_info_panel reconstruction
# ---------------------------------------------------------------------------


def reconstruct_project_info_panel(
    page_key: str,
    page_data: Dict[str, Any],
    panel_type: str = "title_block",
    min_panel_height_frac: float = 0.3,
    candidate_min_height_frac: float = 0.05,
    max_aspect: float = 0.7,
    right_edge_x1_frac: float = 0.9,
    min_panel_area_frac: float = 0.02,
) -> None:
    """
    Build a unified project_info_panel (title_block) from the union of
    skinny right-edge boxes, even if some internal boxes were not detected.

    Candidates:
      - any box with type == panel_type
      - OR any box that is:
          * skinny (aspect <= max_aspect)
          * at the right edge
          * at least candidate_min_height_frac tall

    The final unified panel must still satisfy:
      - height_frac >= min_panel_height_frac
      - area_frac >= min_panel_area_frac
    """
    boxes: List[Dict[str, Any]] = page_data["boxes"]
    if not boxes:
        return

    min_x = float(page_data.get("min_x", 0.0))
    max_x = float(page_data.get("max_x", 1.0))
    min_y = float(page_data.get("min_y", 0.0))
    max_y = float(page_data.get("max_y", 1.0))
    page_w = max(1.0, max_x - min_x)
    page_h = max(1.0, max_y - min_y)
    page_area = page_w * page_h

    candidates: List[Tuple[Dict[str, Any], BBox]] = []

    for b in boxes:
        bbox = bbox_from_list(b["bbox_pdf"])
        if bbox.h <= 0:
            continue
        aspect = bbox.w / bbox.h
        x1_frac = bbox.x1 / page_w
        cx_frac = (bbox.x0 + bbox.x1) / 2.0 / page_w
        height_frac = bbox.h / page_h

        looks_like_panel_part = (
            aspect <= max_aspect
            and height_frac >= candidate_min_height_frac
            and (x1_frac >= right_edge_x1_frac or cx_frac >= right_edge_x1_frac)
        )

        if b.get("type") == panel_type or looks_like_panel_part:
            candidates.append((b, bbox))

    if not candidates:
        return

    union_bbox = candidates[0][1]
    for _, bb in candidates[1:]:
        union_bbox = bbox_union(union_bbox, bb)

    height_frac = union_bbox.h / page_h
    aspect = union_bbox.w / union_bbox.h if union_bbox.h > 0 else max_aspect
    area_frac = union_bbox.area / page_area

    if height_frac < min_panel_height_frac:
        return
    if aspect > max_aspect:
        return
    if area_frac < min_panel_area_frac:
        return

    anchor_box, _ = candidates[0]
    anchor_id = int(anchor_box["id"])

    all_chunks: List[int] = []
    for b, _ in candidates:
        all_chunks.extend(list(b.get("chunk_indices") or []))

    anchor_box["bbox_pdf"] = union_bbox.to_list()
    anchor_box["type"] = panel_type
    anchor_box["chunk_indices"] = sorted(set(all_chunks))
    anchor_box["area_frac"] = area_frac

    ids_to_remove: Set[int] = {int(b["id"]) for (b, _) in candidates[1:]}
    if not ids_to_remove:
        return

    page_data["boxes"] = [b for b in boxes if int(b["id"]) not in ids_to_remove]
    id_map = {rid: anchor_id for rid in ids_to_remove}
    apply_id_map_to_page(page_data, id_map)

    print(
        f"[panel] page={page_key} unified project_info_panel "
        f"anchor={anchor_id} from {len(candidates)} pieces, "
        f"bbox={union_bbox.to_list()}, area_frac={area_frac:.4f}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Merge vertically stacked legend / project_info_panel boxes in "
            "page_box_classes JSON and reconstruct a unified sidebar panel."
        )
    )
    p.add_argument(
        "--input",
        required=True,
        help="Input page_box_classes JSON (from classify_page_boxes.py)",
    )
    p.add_argument(
        "--output",
        required=True,
        help="Output refined JSON path",
    )
    p.add_argument(
        "--pages",
        type=int,
        nargs="*",
        help="Optional list of page numbers to restrict processing to",
    )
    p.add_argument(
        "--merge-types",
        nargs="+",
        default=["legend", "title_block"],
        help=(
            "Box types to merge vertically first. "
            "Default: legend title_block (title_block is the project_info_panel)."
        ),
    )
    p.add_argument(
        "--min-area-frac",
        type=float,
        default=0.0005,
        help="Minimum area fraction for candidate boxes (default: 0.0005)",
    )
    p.add_argument(
        "--max-area-frac",
        type=float,
        default=0.08,
        help="Maximum area fraction for candidate boxes (override up to 0.2 for big legends)",
    )
    p.add_argument(
        "--min-horizontal-iou",
        type=float,
        default=0.8,
        help="Minimum 1D IoU in X to consider boxes aligned in a column",
    )
    p.add_argument(
        "--max-vertical-gap",
        type=float,
        default=40.0,
        help="Maximum vertical gap (PDF units) allowed between boxes for merging",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    args = parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    pages = data.get("pages", {})
    pages_filter = set(args.pages or [])

    total_merges = 0

    for page_key, page_data in pages.items():
        page_num = int(page_key)
        if pages_filter and page_num not in pages_filter:
            continue

        if "boxes" not in page_data:
            continue

        print(f"[page {page_key}] Starting refinement with {len(page_data['boxes'])} boxes")

        page_merges = 0
        cumulative_id_map: Dict[int, int] = {}

        for merge_type in args.merge_types:
            merges, id_map = merge_stacked_for_type(
                page_key=page_key,
                page_data=page_data,
                merge_type=merge_type,
                min_area_frac=args.min_area_frac,
                max_area_frac=args.max_area_frac,
                min_horizontal_iou=args.min_horizontal_iou,
                max_vertical_gap=args.max_vertical_gap,
            )
            if merges:
                print(
                    f"[page {page_key}] Applied {merges} merge(s) "
                    f"for type '{merge_type}'."
                )
                page_merges += merges
                cumulative_id_map.update(id_map)

        if cumulative_id_map:
            apply_id_map_to_page(page_data, cumulative_id_map)

        reconstruct_project_info_panel(page_key, page_data, panel_type="title_block")

        if page_merges:
            print(f"[page {page_key}] Total merges on page (stacked): {page_merges}")
        else:
            print(f"[page {page_key}] No stacked merges applied.")

        total_merges += page_merges

    print(f"[summary] Total merges across all pages (stacked only): {total_merges}")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"[info] Wrote refined boxes JSON to {args.output}")


if __name__ == "__main__":
    main()
