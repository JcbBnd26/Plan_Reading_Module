#!/usr/bin/env python3
"""
tools/visualize_notes_from_json.py

Overlay visualizer for pipeline sanity checks.

Stability fixes:
- Reads bbox in dict OR list OR top-level x0/y0/x1/y1 (via bbox_utils).
- Does not crash on schema drift.
- Optional --label to stamp run_id onto the PNG.

Notes:
- Coordinates are assumed to be in the same PDF space as PyMuPDF's rendered pixmap.
  (This is true when you render with a Matrix scale from 72 dpi.)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont

import bbox_utils


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--pdf", required=True)
    p.add_argument("--json", required=True)
    p.add_argument("--page", type=int, required=True, help="1-based page number")
    p.add_argument("--out", required=True)
    p.add_argument("--dpi", type=int, default=200)
    p.add_argument("--stroke-width", type=int, default=2)
    p.add_argument("--header-stroke-width", type=int, default=6)
    p.add_argument("--scheme", choices=["notes", "type"], default="notes")
    p.add_argument("--include-types", default="")
    p.add_argument("--exclude-types", default="")
    p.add_argument("--label", default="", help="Optional label stamped onto the PNG (e.g. run_id)")
    return p.parse_args()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _get_chunks(root: Any) -> List[Dict[str, Any]]:
    if isinstance(root, dict) and isinstance(root.get("chunks"), list):
        return [c for c in root["chunks"] if isinstance(c, dict)]
    if isinstance(root, list):
        return [c for c in root if isinstance(c, dict)]
    return []


def _type(ch: Dict[str, Any]) -> str:
    return str(ch.get("type", "")).lower()


def _parse_type_list(s: str) -> List[str]:
    s = (s or "").strip()
    if not s:
        return []
    return [x.strip().lower() for x in s.split(",") if x.strip()]


def _render_page(pdf_path: Path, page_1_based: int, dpi: int) -> Image.Image:
    doc = fitz.open(str(pdf_path))
    page = doc.load_page(page_1_based - 1)
    mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    return img


def _draw_label(draw: ImageDraw.ImageDraw, label: str) -> None:
    if not label:
        return
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    x, y = 10, 10
    pad = 4

    # textbbox returns (left, top, right, bottom)
    l, t, r, b = draw.textbbox((x, y), label, font=font)
    w = r - l
    h = b - t

    draw.rectangle([x - pad, y - pad, x + w + pad, y + h + pad], outline=None, fill=(255, 255, 255))
    draw.text((x, y), label, fill=(0, 0, 0), font=font)


def main() -> int:
    a = parse_args()
    include = set(_parse_type_list(a.include_types))
    exclude = set(_parse_type_list(a.exclude_types))

    pdf_path = Path(a.pdf)
    json_path = Path(a.json)
    out_path = Path(a.out)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if not json_path.exists():
        raise FileNotFoundError(f"JSON not found: {json_path}")

    root = _load_json(json_path)
    chunks = _get_chunks(root)

    page_str = str(a.page)
    page_chunks = [c for c in chunks if str(c.get("page", "")) == page_str]

    img = _render_page(pdf_path, a.page, a.dpi)
    draw = ImageDraw.Draw(img)

    headers: List[Dict[str, Any]] = []
    others: List[Dict[str, Any]] = []

    for c in page_chunks:
        t = _type(c)
        if include and t not in include:
            continue
        if exclude and t in exclude:
            continue

        box = bbox_utils.extract_bbox(c)
        if box is None:
            continue

        if t == "header":
            headers.append(c)
        else:
            others.append(c)

    # Draw others first, headers last
    for c in others:
        box = bbox_utils.extract_bbox(c)
        if box is None:
            continue
        x0, y0, x1, y1 = box.as_tuple()

        t = _type(c)
        if a.scheme == "type" and ("note" in t):
            color = (255, 0, 0)
        elif a.scheme == "type":
            color = (160, 160, 160)
        else:
            color = (255, 0, 0)

        draw.rectangle([x0, y0, x1, y1], outline=color, width=a.stroke_width)

    for c in headers:
        box = bbox_utils.extract_bbox(c)
        if box is None:
            continue
        x0, y0, x1, y1 = box.as_tuple()
        color = (0, 200, 0) if a.scheme == "type" else (255, 0, 0)
        draw.rectangle([x0, y0, x1, y1], outline=color, width=a.header_stroke_width)

    _draw_label(draw, a.label)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    print(f"[OK] Wrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
