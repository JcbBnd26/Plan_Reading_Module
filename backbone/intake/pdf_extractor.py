"""
PDF text + geometry extraction (PyMuPDF native).
Provides clean, consistent chunk coordinates in PDF space.

This is the authoritative low-level extractor for the entire chunker.
All downstream systems — semantic grouping, column detection, and the
visual bridge — depend on these coordinates being in *PDF coordinate space*.

Output:
    [
        {
            "text": str,
            "bbox": (x0, y0, x1, y1),     # PDF coordinates
            "page": int                   # 1-based page number
        },
        ...
    ]
"""

from __future__ import annotations
import fitz  # PyMuPDF
from typing import List, Dict, Tuple


BBox = Tuple[float, float, float, float]


def extract_pdf_blocks(pdf_path: str) -> List[Dict]:
    """
    Extracts text blocks and bounding boxes for ALL pages.
    Uses PyMuPDF's native PDF coordinate system.

    Returns:
        List[dict] of:
        {
            "text": str,
            "bbox": (x0, y0, x1, y1),
            "page": int
        }
    """

    doc = fitz.open(pdf_path)
    results: List[Dict] = []

    for page_index, page in enumerate(doc):
        page_num = page_index + 1

        try:
            blocks = page.get_text("blocks")
        except Exception as exc:
            print(f">>> PDF_EXTRACTOR ERROR on page {page_num}: {exc}")
            continue

        for block in blocks:
            # block format:
            # (x0, y0, x1, y1, text, block_no, ...)
            if len(block) < 5:
                continue

            x0, y0, x1, y1, text = block[:5]

            if not text or not text.strip():
                continue

            bbox: BBox = (float(x0), float(y0), float(x1), float(y1))

            results.append(
                {
                    "text": text.strip(),
                    "bbox": bbox,
                    "page": page_num,
                }
            )

    return results
