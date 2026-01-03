#!/usr/bin/env python
"""
detect_legend_boxes.py

Detect the rectangular "LEGEND" box on plan sheets using simple
computer-vision (OpenCV) over rendered PDF pages.

Goal:
- For each page, return a bounding box [x0, y0, x1, y1] in *PDF
  coordinate space* that approximates the outer border of the legend.

Changes in this version:
- MUCH more lenient detection:
    * search bottom ~60% of the page
    * accept any reasonably large contour (>= 4 vertices) and use
      its bounding rectangle
    * softer area and aspect-ratio filters
- This is meant to "just find the big wide box" near the bottom-right.

Output JSON shape:

{
  "pdf_path": "test.pdf",
  "legend_boxes": {
    "3": [x0, y0, x1, y1],
    ...
  }
}
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF
import cv2
import numpy as np


LegendBox = Tuple[float, float, float, float]


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
# Legend detection (pixel space)
# ---------------------------------------------------------------------


def detect_legend_box_on_image(
    img_bgr: np.ndarray,
    min_area_frac: float = 0.005,
    max_area_frac: float = 0.60,
    min_aspect_ratio: float = 1.5,
) -> Optional[Tuple[int, int, int, int]]:
    """
    Detect the legend rectangle in pixel coordinates.

    Strategy:
    - Focus on the bottom ~60% of the page (legend lives low).
    - Run Canny edges and find contours.
    - For each contour:
        * approximate polygon (>=4 vertices)
        * compute bounding rectangle
        * keep rectangles that:
            - are wide (aspect >= min_aspect_ratio)
            - have area within [min_area_frac, max_area_frac] of page
            - are not absurdly tall
            - live in the lower half of the page
            - have center to the right of mid-width (legend is not far-left)
    - Pick the candidate with the largest area.

    Returns:
        (x0, y0, x1, y1) in pixel coordinates, or None if none found.
    """
    h, w, _ = img_bgr.shape
    page_area = float(h * w)

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    edges = cv2.Canny(blurred, threshold1=50, threshold2=150)

    # Focus on bottom ~60% of the page
    y_start = int(h * 0.4)
    roi_edges = edges[y_start:, :]

    contours, _ = cv2.findContours(
        roi_edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    best_box: Optional[Tuple[int, int, int, int]] = None
    best_area: float = 0.0

    for cnt in contours:
        if cv2.contourArea(cnt) < 10:
            continue

        epsilon = 0.02 * cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, epsilon, True)

        # Shift back to full-image coordinates
        approx_full = approx.copy()
        approx_full[:, 0, 1] += y_start

        x, y, w_box, h_box = cv2.boundingRect(approx_full)

        if w_box <= 0 or h_box <= 0:
            continue

        area = float(w_box * h_box)
        area_frac = area / page_area

        if area_frac < min_area_frac or area_frac > max_area_frac:
            # Too small or too big (likely entire page / huge frame)
            continue

        aspect = float(w_box) / float(h_box)

        # Legend is wider than tall, but we don't demand extreme ratio
        if aspect < min_aspect_ratio:
            continue

        # Legend isn't insanely tall
        if h_box > 0.55 * h:
            continue

        cx = x + w_box / 2.0
        cy = y + h_box / 2.0

        # We expect the legend to be in the lower half
        if cy < h * 0.55:
            continue

        # And not far left; your legend is mid/right-ish
        if cx < w * 0.35:
            continue

        # Reject nearly full-width boxes (page border)
        if w_box > 0.95 * w:
            continue

        if area > best_area:
            best_area = area
            best_box = (x, y, x + w_box, y + h_box)

    return best_box


def transform_pixel_box_to_pdf(
    pixel_box: Tuple[int, int, int, int],
    page_rect: fitz.Rect,
    img_shape: Tuple[int, int, int],
) -> LegendBox:
    """
    Map a pixel-space bounding box back to PDF coordinate space.

    PDF coordinates:
      - origin at top-left of page
      - width = page_rect.width
      - height = page_rect.height

    Pixel coordinates:
      - origin at top-left of raster
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


def detect_legend_boxes_for_pdf(
    pdf_path: Path,
    pages: Optional[List[int]] = None,
    dpi: int = 200,
) -> Dict[int, LegendBox]:
    """
    Detect legend boxes for selected pages of a PDF.

    Args:
        pdf_path: path to the PDF file.
        pages: list of 1-based page numbers to process. If None,
               process all pages.
        dpi: rasterization resolution for detection.

    Returns:
        Dict mapping page_number (1-based) -> LegendBox (x0,y0,x1,y1 in PDF coords).
    """
    result: Dict[int, LegendBox] = {}

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

            pixel_box = detect_legend_box_on_image(img_bgr)
            if pixel_box is None:
                print(f"[warn] No legend box detected on page {page_num}")
                continue

            pdf_box = transform_pixel_box_to_pdf(pixel_box, page_rect, img_bgr.shape)
            result[page_num] = pdf_box
            print(f"[info] Page {page_num}: legend box (PDF coords) = {pdf_box}")

    return result


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect legend boxes on PDF pages using OpenCV."
    )
    parser.add_argument(
        "--pdf",
        required=True,
        help="Path to input PDF (e.g. test.pdf).",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Path to output JSON (e.g. exports/legend_boxes.json).",
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    pdf_path = Path(args.pdf)
    out_path = Path(args.out)

    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    legend_boxes = detect_legend_boxes_for_pdf(pdf_path, pages=args.pages, dpi=args.dpi)

    payload = {
        "pdf_path": str(pdf_path),
        "legend_boxes": {
            str(page_num): list(box) for page_num, box in legend_boxes.items()
        },
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"Wrote legend boxes for {len(legend_boxes)} pages to {out_path}")


if __name__ == "__main__":
    main()
