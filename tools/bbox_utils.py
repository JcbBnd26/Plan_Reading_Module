#!/usr/bin/env python3
"""
tools/bbox_utils.py

Single source of truth for reading + writing bounding boxes (bbox) across the pipeline.

Why this exists
---------------
Your repo historically drifted into multiple bbox schemas:

  1) list/tuple  [x0, y0, x1, y1]
  2) dict        {"x0":..., "y0":..., "x1":..., "y1":...}
  3) top-level   chunk["x0"], chunk["y0"], chunk["x1"], chunk["y1"]

This module:
- READS all three shapes (for backward compatibility).
- WRITES one canonical shape by default: dict bbox.

Design rules
------------
- Canonical geometry lives in chunk["bbox"] as a dict with x0/y0/x1/y1 floats.
- For compatibility, we also sync top-level x0/y0/x1/y1 fields by default.
  (These can be removed later once all tools stop reading them.)

This is intentionally boring and deterministic — boring code is the most reusable code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


def _to_float(v: Any) -> Optional[float]:
    """Best-effort float conversion. Returns None if not parseable."""
    try:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip()
        if not s:
            return None
        return float(s)
    except Exception:
        return None


@dataclass(frozen=True)
class BBox:
    """
    Axis-aligned bounding box in PDF coordinate space (x right, y down for PyMuPDF pixmaps).
    Always normalized such that x0<=x1 and y0<=y1.
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
    def area(self) -> float:
        return self.w * self.h

    def as_tuple(self) -> Tuple[float, float, float, float]:
        return (float(self.x0), float(self.y0), float(self.x1), float(self.y1))

    def as_dict(self) -> Dict[str, float]:
        return {"x0": float(self.x0), "y0": float(self.y0), "x1": float(self.x1), "y1": float(self.y1)}

    def union(self, other: "BBox") -> "BBox":
        return BBox(
            x0=min(self.x0, other.x0),
            y0=min(self.y0, other.y0),
            x1=max(self.x1, other.x1),
            y1=max(self.y1, other.y1),
        )

    def pad(self, pad: float) -> "BBox":
        p = float(pad)
        return BBox(self.x0 - p, self.y0 - p, self.x1 + p, self.y1 + p)

    def intersection(self, other: "BBox") -> Optional["BBox"]:
        x0 = max(self.x0, other.x0)
        y0 = max(self.y0, other.y0)
        x1 = min(self.x1, other.x1)
        y1 = min(self.y1, other.y1)
        if x1 <= x0 or y1 <= y0:
            return None
        return BBox(x0, y0, x1, y1)

    def vertical_gap_to(self, other: "BBox") -> float:
        """
        Vertical distance between boxes if they do not overlap vertically.
        0.0 if they overlap (or touch).
        """
        if other.y0 >= self.y1:
            return other.y0 - self.y1
        if self.y0 >= other.y1:
            return self.y0 - other.y1
        return 0.0

    def horizontal_overlap_ratio(self, other: "BBox") -> float:
        """
        overlap_width / min(widths). Range [0, 1] (approximately).
        """
        overlap = max(0.0, min(self.x1, other.x1) - max(self.x0, other.x0))
        denom = max(min(self.w, other.w), 1.0)
        return overlap / denom


def bbox_from_xyxy(x0: Any, y0: Any, x1: Any, y1: Any, *, allow_swap: bool = True) -> Optional[BBox]:
    """
    Create a normalized BBox from 4 values. If allow_swap=True, will sort x and y pairs.
    """
    fx0, fy0, fx1, fy1 = (_to_float(x0), _to_float(y0), _to_float(x1), _to_float(y1))
    if None in (fx0, fy0, fx1, fy1):
        return None

    if allow_swap:
        nx0, nx1 = sorted((fx0, fx1))
        ny0, ny1 = sorted((fy0, fy1))
    else:
        nx0, ny0, nx1, ny1 = fx0, fy0, fx1, fy1

    return BBox(float(nx0), float(ny0), float(nx1), float(ny1))


def extract_bbox(chunk: Dict[str, Any], *, allow_swap: bool = True) -> Optional[BBox]:
    """
    Read bbox from a chunk in any supported schema.

    Supported:
      - chunk["bbox"] as dict: {"x0","y0","x1","y1"}
      - chunk["bbox"] as list/tuple: [x0,y0,x1,y1]
      - top-level chunk["x0"/"y0"/"x1"/"y1"]

    Returns:
      - BBox (normalized) or None.
    """
    b = chunk.get("bbox")

    # Dict bbox
    if isinstance(b, dict):
        return bbox_from_xyxy(b.get("x0"), b.get("y0"), b.get("x1"), b.get("y1"), allow_swap=allow_swap)

    # List/tuple bbox
    if isinstance(b, (list, tuple)) and len(b) >= 4:
        return bbox_from_xyxy(b[0], b[1], b[2], b[3], allow_swap=allow_swap)

    # Top-level fallback
    return bbox_from_xyxy(chunk.get("x0"), chunk.get("y0"), chunk.get("x1"), chunk.get("y1"), allow_swap=allow_swap)


def write_bbox(
    chunk: Dict[str, Any],
    box: BBox,
    *,
    bbox_format: str = "dict",
    sync_top_level: bool = True,
) -> None:
    """
    Write bbox into the chunk.

    bbox_format:
      - "dict" (default): chunk["bbox"] = {"x0":..,"y0":..,"x1":..,"y1":..}
      - "list": chunk["bbox"] = [x0,y0,x1,y1]   (discouraged; exists for edge compatibility)

    sync_top_level:
      - If True, also writes chunk["x0"/"y0"/"x1"/"y1"] for backwards compatibility.
    """
    if bbox_format not in ("dict", "list"):
        raise ValueError(f"bbox_format must be 'dict' or 'list', got: {bbox_format!r}")

    if bbox_format == "dict":
        chunk["bbox"] = box.as_dict()
    else:
        chunk["bbox"] = [box.x0, box.y0, box.x1, box.y1]

    if sync_top_level:
        chunk["x0"] = float(box.x0)
        chunk["y0"] = float(box.y0)
        chunk["x1"] = float(box.x1)
        chunk["y1"] = float(box.y1)


def ensure_bbox_dict_inplace(chunk: Dict[str, Any], *, sync_top_level: bool = True) -> bool:
    """
    Normalize a chunk to canonical bbox dict format, in-place.

    Returns:
      True if bbox is present and is now a dict,
      False if no bbox was found/parseable.
    """
    box = extract_bbox(chunk)
    if not box:
        return False
    write_bbox(chunk, box, bbox_format="dict", sync_top_level=sync_top_level)
    return True


def overlap_ratio(of_box: BBox, onto_box: BBox) -> float:
    """
    Ratio = intersection_area(of_box, onto_box) / area(of_box).
    """
    inter = of_box.intersection(onto_box)
    if not inter:
        return 0.0
    denom = of_box.area
    if denom <= 0.0:
        return 0.0
    return inter.area / denom
