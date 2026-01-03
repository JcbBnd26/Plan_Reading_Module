#!/usr/bin/env python
"""
detect_page_boxes.py

Stage 1 of shape-based OCR:

Detect all reasonably large rectangular "frames" on each PDF page
using OpenCV. These frames include legends, tables, location maps,
title blocks, note boxes, etc. We DO NOT try to classify them here.

Output JSON is designed to be consumed by later stages that will do
semantic classification (legend vs table vs title block, etc.).

Example output structure:

{
  "pdf_path": "test.pdf",
  "dpi": 200,
  "pages": {
    "3": {
      "image_width_px": 2480,
      "image_height_px": 1664,
      "boxes": [
        {
          "id": 1,
          "bbox_px": [x0, y0, x1, y1],
          "bbox_pdf": [X0, Y0, X1, Y1],
          "area_frac": 0.18,
          "is_page_border_hint": false
        },
        ...
      ]
    }
  }
}
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import fitz  # PyMuPDF
import numpy as np


# ---------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------


BoxPx = Tuple[int, int, int, int]  # x0, y0, x1, y1 in pixel space
BoxPdf = Tuple[float, float, float, float]  # x0, y0, x1, y1 in PDF coords


# ---------------------------------------------------------------------
# PDF → image
# ---------------------------------------------------------------------


def render_page_to_bgr_array(
    doc: fitz.Document,
    page_index: int,
    dpi: int = 200,
) -> Tuple[np.ndarray, fitz.Rect]:
    """
    Render a PDF page to a BGR image (OpenCV format).

    Returns:
        img_bgr: np.ndarray of shape (H, W, 3)
        page_rect: fitz.Rect in PDF coordinate space
    """
    page = doc[page_index]
    page_rect = page.rect

    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)

    img = np.frombuffer(pix.samples, dtype=np.uint8)
    img = img.reshape(pix.height, pix.width, pix.n)

    if pix.n == 4:
        img_bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    else:
        img_bgr = img

    return img_bgr, page_rect


# ---------------------------------------------------------------------
# Box detection per image
# ---------------------------------------------------------------------


def detect_boxes_on_image(
    img_bgr: np.ndarray,
    min_area_frac: float = 0.0005,
    min_size_px: int = 12,
) -> List[Tuple[BoxPx, float, bool]]:
    """
    Detect all reasonably large rectangular frames on an image.

    We intentionally err on the side of *keeping* candidates; Stage 2
    will classify and prune. Here we just try to avoid obvious noise.

    Args:
        img_bgr: BGR image (H, W, 3)
        min_area_frac: minimum box area as fraction of whole page.
                       This filters out tiny cells / specks.
        min_size_px: minimum width/height in pixels.

    Returns:
        List of tuples: (bbox_px, area_frac, is_page_border_hint)
    """
    h, w, _ = img_bgr.shape
    page_area = float(h * w)

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # Edge detection
    edges = cv2.Canny(blurred, threshold1=50, threshold2=150)

    # Light dilation to close tiny gaps in lines
    kernel = np.ones((3, 3), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=1)

    # Find contours. RETR_LIST = all contours, no hierarchy assumptions.
    contours, _ = cv2.findContours(
        edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
    )

    boxes: List[Tuple[BoxPx, float, bool]] = []

    for cnt in contours:
        if cv2.contourArea(cnt) < 10:
            continue

        epsilon = 0.02 * cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, epsilon, True)

        x, y, w_box, h_box = cv2.boundingRect(approx)

        if w_box < min_size_px or h_box < min_size_px:
            # Too small; likely noise or tiny grid cell
            continue

        area_box = float(w_box * h_box)
        area_frac = area_box / page_area
        if area_frac < min_area_frac:
            continue

        x0, y0, x1, y1 = x, y, x + w_box, y + h_box

        # Heuristic: is this basically the full page border?
        is_page_border = (
            w_box > 0.95 * w and h_box > 0.95 * h
        )

        boxes.append(((x0, y0, x1, y1), area_frac, is_page_border))

    # Sort by area descending so larger frames get lower IDs (more stable)
    boxes.sort(key=lambda item: item[1], reverse=True)

    return boxes


def pixel_box_to_pdf_box(
    pixel_box: BoxPx,
    page_rect: fitz.Rect,
    img_shape: Tuple[int, int, int],
) -> BoxPdf:
    """
    Map a pixel-space bounding box back to PDF coordinate space.

    PDF coords:
      - origin at top-left
      - width = page_rect.width
      - height = page_rect.height

    Pixel coords:
      - origin at top-left
      - width = img_shape[1]
      - height = img_shape[0]
    """
    h_img, w_img, _ = img_shape
    x0_px, y0_px, x1_px, y1_px = pixel_box

    scale_x = page_rect.width / float(w_img)
    scale_y = page_rect.height / float(h_img)

    x0_pdf = page_rect.x0 + x0_px * scale_x
    x1_pdf = page_rect.x0 + x1_px * scale_x
    y0_pdf = page_rect.y0 + y0_px * scale_y
    y1_pdf = page_rect.y0 + y1_px * scale_y

    return (float(x0_pdf), float(y0_pdf), float(x1_pdf), float(y1_pdf))


# ---------------------------------------------------------------------
# PDF orchestration
# ---------------------------------------------------------------------


def detect_boxes_for_pdf(
    pdf_path: Path,
    pages: Optional[List[int]] = None,
    dpi: int = 200,
    min_area_frac: float = 0.0005,
    min_size_px: int = 12,
) -> Dict[str, Any]:
    """
    Detect frame boxes for selected pages of a PDF.

    Args:
        pdf_path: path to the PDF.
        pages: optional list of 1-based page numbers; if None, process all.
        dpi: rasterization DPI.
        min_area_frac: minimum area fraction per box.
        min_size_px: minimum width/height in pixels.

    Returns:
        A dict ready to be dumped as JSON (see module docstring).
    """
    result: Dict[str, Any] = {
        "pdf_path": str(pdf_path),
        "dpi": dpi,
        "pages": {},
    }

    with fitz.open(pdf_path) as doc:
        num_pages = doc.page_count

        if pages is None:
            target_indices = list(range(num_pages))
        else:
            target_indices = []
            for p in pages:
                if p < 1 or p > num_pages:
                    raise ValueError(f"Page {p} is out of range 1..{num_pages}")
                target_indices.append(p - 1)

        for page_index in target_indices:
            page_num = page_index + 1
            img_bgr, page_rect = render_page_to_bgr_array(doc, page_index, dpi=dpi)

            boxes = detect_boxes_on_image(
                img_bgr,
                min_area_frac=min_area_frac,
                min_size_px=min_size_px,
            )

            page_entry: Dict[str, Any] = {
                "image_width_px": int(img_bgr.shape[1]),
                "image_height_px": int(img_bgr.shape[0]),
                "boxes": [],
            }

            for i, (bbox_px, area_frac, is_border) in enumerate(boxes, start=1):
                bbox_pdf = pixel_box_to_pdf_box(bbox_px, page_rect, img_bgr.shape)
                page_entry["boxes"].append(
                    {
                        "id": i,
                        "bbox_px": [int(bbox_px[0]), int(bbox_px[1]),
                                    int(bbox_px[2]), int(bbox_px[3])],
                        "bbox_pdf": [bbox_pdf[0], bbox_pdf[1],
                                     bbox_pdf[2], bbox_pdf[3]],
                        "area_frac": area_frac,
                        "is_page_border_hint": bool(is_border),
                    }
                )

            result["pages"][str(page_num)] = page_entry

            print(
                f"[info] Page {page_num}: detected {len(page_entry['boxes'])} "
                f"box candidate(s)."
            )

    return result


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect rectangular frame boxes on PDF pages using OpenCV."
    )
    parser.add_argument(
        "--pdf",
        required=True,
        help="Path to input PDF (e.g. test.pdf).",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Path to output JSON (e.g. exports/page_boxes.json).",
    )
    parser.add_argument(
        "--pages",
        nargs="*",
        type=int,
        default=None,
        help="Optional list of 1-based page numbers to process; "
             "if omitted, all pages are processed.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="Rasterization DPI for detection (default: 200).",
    )
    parser.add_argument(
        "--min-area-frac",
        type=float,
        default=0.0005,
        help="Minimum area fraction per box (default: 0.0005). "
             "Increase to reduce small boxes, decrease to keep more.",
    )
    parser.add_argument(
        "--min-size-px",
        type=int,
        default=12,
        help="Minimum width/height in pixels for a box (default: 12).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    pdf_path = Path(args.pdf)
    out_path = Path(args.out)

    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    data = detect_boxes_for_pdf(
        pdf_path=pdf_path,
        pages=args.pages,
        dpi=args.dpi,
        min_area_frac=args.min_area_frac,
        min_size_px=args.min_size_px,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"Wrote box candidates to {out_path}")


if __name__ == "__main__":
    main()
