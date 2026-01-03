"""
Image → JSON box auto-detector.

Given a PDF page with color-coded rectangles, this module:
  - rasterizes the page
  - detects connected regions of specific colors
  - converts them back into PDF coordinate space
  - emits a schema-compatible `page_structure` + `color_classes` dict.

Designed for annotated/labeled sheets, NOT raw construction plans.
"""

from __future__ import annotations

from typing import Dict, List, Tuple
from pathlib import Path
from collections import deque

import fitz  # PyMuPDF
from PIL import Image


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def _hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _color_close(c1: Tuple[int, int, int], c2: Tuple[int, int, int], tol: int = 10) -> bool:
    """Return True if two RGB colors are close under the tolerance."""
    return all(abs(a - b) <= tol for a, b in zip(c1, c2))


def _detect_regions_for_color(
    img: Image.Image,
    target_rgb: Tuple[int, int, int],
    tol: int = 10
) -> List[Tuple[int, int, int, int]]:
    """
    Return list of (x0, y0, x1, y1) bounding boxes for contiguous
    pixel regions matching target_rgb within tolerance.
    """
    w, h = img.size
    pix = img.load()

    # CORRECT: visited[y][x]
    visited = [[False for _ in range(w)] for _ in range(h)]
    boxes: List[Tuple[int, int, int, int]] = []

    # Neighbor generator
    def neighbors(x: int, y: int):
        for dx, dy in ((1,0), (-1,0), (0,1), (0,-1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h:
                yield nx, ny

    # Flood-fill through image
    for y in range(h):
        for x in range(w):
            if visited[y][x]:
                continue

            if not _color_close(pix[x, y][:3], target_rgb, tol):
                visited[y][x] = True
                continue

            # Start new region
            q = deque([(x, y)])
            visited[y][x] = True

            min_x = max_x = x
            min_y = max_y = y

            while q:
                cx, cy = q.popleft()
                for nx, ny in neighbors(cx, cy):
                    if visited[ny][nx]:
                        continue
                    if _color_close(pix[nx, ny][:3], target_rgb, tol):
                        visited[ny][nx] = True
                        q.append((nx, ny))
                        min_x = min(min_x, nx)
                        max_x = max(max_x, nx)
                        min_y = min(min_y, ny)
                        max_y = max(max_y, ny)
                    else:
                        visited[ny][nx] = True

            boxes.append((min_x, min_y, max_x+1, max_y+1))

    return boxes


# ------------------------------------------------------------
# Main detection API
# ------------------------------------------------------------

def detect_boxes_from_pdf(
    pdf_path: str,
    page_number: int = 1,
    dpi: int = 150,
    color_classes: Dict[str, Dict[str, str]] | None = None,
    color_tolerance: int = 10,
) -> Dict:
    """
    Detect color-coded boxes on a given PDF page.

    Returns:
    {
      "metadata": {...},
      "color_classes": {...},
      "page_structure": {
          "whole_sheet_bbox": {...} or None,
          "sheet_info_bbox": {...} or None,
          "columns": [...],
          "column_headers": [...],
          "notes": [...],
          "legend_boxes": [...],
          "xenoglyph_boxes": [...],
      }
    }
    """
    pdf_p = Path(pdf_path)
    if not pdf_p.exists():
        raise FileNotFoundError(pdf_path)

    doc = fitz.open(str(pdf_p))
    if not (1 <= page_number <= len(doc)):
        raise ValueError(f"Page {page_number} out of range 1..{len(doc)}")

    page = doc.load_page(page_number - 1)
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

    # Defaults (your annotated color set)
    default_color_classes = {
        "column":        {"hex": "#00FDFF"},
        "column_header": {"hex": "#FF2600"},
        "note":          {"hex": "#00F900"},
        "legend":        {"hex": "#AA7942"},
        "sheet_info":    {"hex": "#0433FF"},
        "whole_sheet":   {"hex": "#FF9300"},
        "xenoglyph":     {"hex": "#FF40FF"},
    }
    color_classes = color_classes or default_color_classes

    detected = {
        "columns": [],
        "column_headers": [],
        "notes": [],
        "legend_boxes": [],
        "xenoglyph_boxes": [],
        "whole_sheet_bbox": None,
        "sheet_info_bbox": None,
    }

    page_w = page.rect.width
    page_h = page.rect.height

    def px_to_pdf(px_box):
        x0, y0, x1, y1 = px_box
        fx = page_w / pix.width
        fy = page_h / pix.height
        return [x0*fx, y0*fy, x1*fx, y1*fy]

    # Detect by classes
    for cls_name, color_info in color_classes.items():
        rgb = _hex_to_rgb(color_info.get("hex", "#000000"))
        px_boxes = _detect_regions_for_color(img, rgb, tol=color_tolerance)
        pdf_boxes = [px_to_pdf(b) for b in px_boxes]

        if cls_name == "whole_sheet":
            if pdf_boxes:
                detected["whole_sheet_bbox"] = {
                    "bbox": pdf_boxes[0],
                    "class": "whole_sheet",
                    "page_number": page_number,
                    "color_hex": color_info.get("hex"),
                }

        elif cls_name == "sheet_info":
            if pdf_boxes:
                detected["sheet_info_bbox"] = {
                    "bbox": pdf_boxes[0],
                    "class": "sheet_info",
                    "page_number": page_number,
                    "color_hex": color_info.get("hex"),
                }

        elif cls_name == "column":
            for i, b in enumerate(pdf_boxes):
                detected["columns"].append({
                    "id": f"col_{i+1}",
                    "bbox": b,
                    "class": "column",
                    "page_number": page_number,
                    "color_hex": color_info.get("hex"),
                })

        elif cls_name == "column_header":
            for i, b in enumerate(pdf_boxes):
                detected["column_headers"].append({
                    "id": f"hdr_{i+1}",
                    "bbox": b,
                    "class": "column_header",
                    "page_number": page_number,
                    "color_hex": color_info.get("hex"),
                })

        elif cls_name == "note":
            for i, b in enumerate(pdf_boxes):
                detected["notes"].append({
                    "id": f"note_{i+1}",
                    "bbox": b,
                    "class": "note",
                    "page_number": page_number,
                    "color_hex": color_info.get("hex"),
                })

        elif cls_name == "legend":
            for i, b in enumerate(pdf_boxes):
                detected["legend_boxes"].append({
                    "id": f"legend_{i+1}",
                    "bbox": b,
                    "class": "legend",
                    "page_number": page_number,
                    "color_hex": color_info.get("hex"),
                })

        elif cls_name == "xenoglyph":
            for i, b in enumerate(pdf_boxes):
                detected["xenoglyph_boxes"].append({
                    "id": f"xeno_{i+1}",
                    "bbox": b,
                    "class": "xenoglyph",
                    "page_number": page_number,
                    "color_hex": color_info.get("hex"),
                })

    return {
        "metadata": {
            "source_file": pdf_p.name,
            "version": "auto-1.0",
            "page_number": page_number,
            "notes": "Auto-generated via color-coded detection.",
        },
        "color_classes": color_classes,
        "page_structure": detected,
    }
