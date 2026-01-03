#!/usr/bin/env python
"""
visualize_note_columns.py

Overlays:
- Purple: section/column boxes (header + its notes), using NOTE-derived X bounds
- Red: note boxes (non-headers)
- Blue: header boxes (so your column selector can target them)
- Optional continuance markers and debug labels

This tool is VISUAL ONLY. It does not change JSON.

Usage:
py tools\\visualize_note_columns.py --pdf test.pdf --json exports\\MostRecent\\page3_notes_merged_v11.json --page 3 --out exports\\MostRecent\\notes_page_3_columns_overlay_debug.png --dpi 200 --x-tol 140 --use-column-bounds --debug-labels --continuance
"""

import argparse
import json
import re
from typing import Any, Dict, List, Tuple, Optional

import fitz  # PyMuPDF
from PIL import Image, ImageDraw

BBox = Tuple[float, float, float, float]


# -----------------------------
# Text helpers
# -----------------------------

HEADER_RE = re.compile(r"^[A-Z0-9&/\-\s]{4,90}NOTES(?:\s*\([^)]*\))?:?$")


def get_text(ch: Dict[str, Any]) -> str:
    if isinstance(ch.get("text"), str):
        return ch["text"]
    if isinstance(ch.get("content"), str):
        return ch["content"]
    return ""


def is_header(text: str) -> bool:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if "NOTES" not in t:
        return False

    letters = [c for c in t if c.isalpha()]
    if not letters:
        return False

    upper_ratio = sum(1 for c in letters if c.isupper()) / max(len(letters), 1)
    return upper_ratio >= 0.85 and bool(HEADER_RE.match(t))


def norm_header(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    t = re.sub(r"\s*\([^)]*\)", "", t)  # drop "(CONT'D)" etc
    return t.rstrip(":").strip()


# -----------------------------
# Geometry helpers
# -----------------------------

def get_bbox(ch: Dict[str, Any]) -> Optional[BBox]:
    b = ch.get("bbox")
    if isinstance(b, (list, tuple)) and len(b) == 4:
        return float(b[0]), float(b[1]), float(b[2]), float(b[3])
    if isinstance(b, dict):
        return (
            float(b.get("x0", 0.0)),
            float(b.get("y0", 0.0)),
            float(b.get("x1", 0.0)),
            float(b.get("y1", 0.0)),
        )
    if all(k in ch for k in ("x0", "y0", "x1", "y1")):
        return float(ch["x0"]), float(ch["y0"]), float(ch["x1"]), float(ch["y1"])
    return None


def union_boxes(boxes: List[BBox]) -> BBox:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def x_center(b: BBox) -> float:
    return (b[0] + b[2]) / 2.0


# -----------------------------
# Column clustering (x-center)
# -----------------------------

def cluster_by_xcenter(items: List[Tuple[int, Dict[str, Any]]], tol: float) -> Dict[int, int]:
    centers: List[Tuple[int, float]] = []
    for idx, ch in items:
        b = get_bbox(ch)
        if not b:
            continue
        centers.append((idx, x_center(b)))

    if not centers:
        return {idx: 0 for idx, _ in items}

    centers.sort(key=lambda t: t[1])

    clusters: List[Dict[str, Any]] = []
    for idx, xc in centers:
        if not clusters:
            clusters.append({"center": xc, "members": [idx]})
            continue

        best_i = min(range(len(clusters)), key=lambda ci: abs(xc - clusters[ci]["center"]))
        best_dist = abs(xc - clusters[best_i]["center"])

        if best_dist <= tol:
            c = clusters[best_i]
            c["members"].append(idx)
            c["center"] = (c["center"] * (len(c["members"]) - 1) + xc) / len(c["members"])
        else:
            clusters.append({"center": xc, "members": [idx]})

    clusters.sort(key=lambda c: c["center"])

    out: Dict[int, int] = {}
    for col_i, c in enumerate(clusters):
        for idx in c["members"]:
            out[idx] = col_i
    return out


# -----------------------------
# Main
# -----------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--json", required=True)
    ap.add_argument("--page", type=int, required=True, help="1-based page number")
    ap.add_argument("--out", required=True)
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--x-tol", type=float, default=140.0)
    ap.add_argument("--continuance", action="store_true")
    ap.add_argument("--debug-labels", action="store_true")
    ap.add_argument("--use-column-bounds", action="store_true",
                    help="Purple section boxes span full column NOTE bounds (recommended).")
    ap.add_argument("--draw-headers", action="store_true",
                    help="Draw header boxes (blue).")
    args = ap.parse_args()

    data = json.load(open(args.json, "r", encoding="utf-8"))
    chunks = data["chunks"] if isinstance(data, dict) and "chunks" in data else data

    page_num = args.page

    page_chunks: List[Tuple[int, Dict[str, Any]]] = []
    for i, ch in enumerate(chunks):
        p = ch.get("page") or ch.get("page_number") or ch.get("page_index")
        try:
            p = int(p)
        except Exception:
            continue
        if p == page_num:
            page_chunks.append((i, ch))

    doc = fitz.open(args.pdf)
    page = doc[page_num - 1]

    scale = args.dpi / 72.0
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    draw = ImageDraw.Draw(img)

    # Column clustering for visualization
    col_map = cluster_by_xcenter(page_chunks, tol=args.x_tol)

    # Group by column and y-sort
    cols: Dict[int, List[Tuple[int, Dict[str, Any]]]] = {}
    for idx, ch in page_chunks:
        cols.setdefault(col_map.get(idx, 0), []).append((idx, ch))

    for col_i in cols:
        cols[col_i].sort(key=lambda t: (get_bbox(t[1])[1] if get_bbox(t[1]) else 0.0, t[0]))

    # Compute per-column NOTE bounds (headers excluded)
    col_note_bounds: Dict[int, Optional[BBox]] = {}
    col_centers: Dict[int, float] = {}

    for col_i, items in cols.items():
        note_boxes: List[BBox] = []
        centers: List[float] = []

        for _, ch in items:
            b = get_bbox(ch)
            if not b:
                continue
            centers.append(x_center(b))
            if is_header(get_text(ch)):
                continue
            note_boxes.append(b)

        col_centers[col_i] = (sum(centers) / max(len(centers), 1)) if centers else 0.0
        col_note_bounds[col_i] = union_boxes(note_boxes) if note_boxes else None

    # Build sections per column: header + following notes until next header
    sections: List[Dict[str, Any]] = []
    for col_i in sorted(cols.keys()):
        items = cols[col_i]

        cur_header = None
        cur_header_box = None
        cur_notes: List[BBox] = []

        def flush_section():
            nonlocal cur_header, cur_header_box, cur_notes
            if cur_header and cur_header_box and cur_notes:
                notes_union = union_boxes(cur_notes)

                # X-range should NOT be influenced by wide/centered header bboxes
                if args.use_column_bounds and col_note_bounds.get(col_i):
                    cx0, cy0, cx1, cy1 = col_note_bounds[col_i]
                    sec_x0, sec_x1 = cx0, cx1
                else:
                    sec_x0, sec_x1 = notes_union[0], notes_union[2]

                sec_y0 = min(cur_header_box[1], notes_union[1])
                sec_y1 = max(cur_header_box[3], notes_union[3])

                sections.append({
                    "col": col_i,
                    "header": cur_header,
                    "header_norm": norm_header(cur_header),
                    "box": (sec_x0, sec_y0, sec_x1, sec_y1),
                    "header_box": cur_header_box,
                    "notes": cur_notes[:],
                })

            cur_header = None
            cur_header_box = None
            cur_notes = []

        for _, ch in items:
            b = get_bbox(ch)
            if not b:
                continue
            t = get_text(ch)

            if is_header(t):
                flush_section()
                cur_header = t
                cur_header_box = b
                continue

            if cur_header is not None:
                cur_notes.append(b)

        flush_section()

    # Colors
    PURPLE = (128, 0, 128)  # section boxes
    RED = (255, 0, 0)       # notes
    BLUE = (0, 80, 255)     # headers

    # Debug: draw column NOTE bounds + center lines
    if args.debug_labels:
        for col_i in sorted(cols.keys()):
            b = col_note_bounds.get(col_i)
            if b:
                x0, y0, x1, y1 = b
                draw.rectangle([x0*scale, y0*scale, x1*scale, y1*scale], outline=PURPLE, width=1)
            cx = col_centers.get(col_i, None)
            if cx is not None:
                draw.line([cx*scale, 0, cx*scale, img.height], fill=PURPLE, width=1)
                draw.text((cx*scale + 4, 4), f"COL {col_i}", fill=PURPLE)

    # Draw purple section boxes
    for si, s in enumerate(sections):
        x0, y0, x1, y1 = s["box"]
        draw.rectangle([x0*scale, y0*scale, x1*scale, y1*scale], outline=PURPLE, width=3)
        if args.debug_labels:
            label = f"C{s['col']} {s['header_norm']}"
            if len(label) > 55:
                label = label[:52] + "..."
            draw.text((x0*scale + 6, y0*scale + 6), label, fill=PURPLE)

    # Draw blue header boxes (THIS is what you’re missing)
    if args.draw_headers:
        for _, ch in page_chunks:
            b = get_bbox(ch)
            if not b:
                continue
            t = get_text(ch)
            if not is_header(t):
                continue
            x0, y0, x1, y1 = b
            draw.rectangle([x0*scale, y0*scale, x1*scale, y1*scale], outline=BLUE, width=3)

    # Draw red note boxes (notes only)
    for _, ch in page_chunks:
        b = get_bbox(ch)
        if not b:
            continue
        t = get_text(ch)
        if is_header(t):
            continue
        x0, y0, x1, y1 = b
        draw.rectangle([x0*scale, y0*scale, x1*scale, y1*scale], outline=RED, width=2)

    # Continuance markers
    if args.continuance:
        page_h = float(page.rect.height)
        by_header: Dict[str, List[Dict[str, Any]]] = {}
        for s in sections:
            by_header.setdefault(s["header_norm"], []).append(s)

        for h, segs in by_header.items():
            if len(segs) < 2:
                continue
            segs.sort(key=lambda s: (s["col"], s["box"][1]))

            for a, b in zip(segs, segs[1:]):
                ay1 = a["box"][3]
                by0 = b["box"][1]
                if ay1 > 0.85 * page_h and by0 < 0.20 * page_h and b["col"] == a["col"] + 1:
                    ax = (a["box"][0] + a["box"][2]) / 2.0
                    bx = (b["box"][0] + b["box"][2]) / 2.0
                    draw.line([ax*scale, ay1*scale, bx*scale, by0*scale], fill=PURPLE, width=3)
                    draw.text((ax*scale + 6, ay1*scale - 18), "CONT →", fill=PURPLE)

    img.save(args.out)
    print(f"[OK] Wrote overlay: {args.out}")


if __name__ == "__main__":
    main()
