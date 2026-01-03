# backbone/visual/visual_debug.py
"""
Visual debug overlays for Visual Note Learning.

Draws color-coded bounding boxes from the visual schema onto rendered PDF
pages, saving PNGs for manual inspection.
"""

from typing import Dict, List, Tuple
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageDraw


def _hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def draw_visual_debug_images(
    pdf_path: str,
    schema: Dict,
    output_dir: str,
    dpi: int = 150,
) -> None:
    """Generate debug PNGs with all labeled boxes drawn.

    Expects schema with keys:
        - color_classes
        - page_structure: {
            "columns":       [ { "bbox": [...], "page_number": ... }, ... ]
            "column_headers":[ { "bbox": [...], "page_number": ... }, ... ]
            "notes":         [ { "bbox": [...], "page_number": ... }, ... ]
            "legend_boxes":  [ ... ]
            "sheet_info_bbox": { "bbox": [...], "page_number": ... } or None
            "xenoglyph_boxes": [ ... ]
          }
    """
    pdf_p = Path(pdf_path)
    if not pdf_p.exists():
        raise FileNotFoundError(pdf_path)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    color_classes = schema.get("color_classes", {})
    class_colors = {
        "column":        _hex_to_rgb(color_classes.get("column", {}).get("hex", "#00FDFF")),
        "column_header": _hex_to_rgb(color_classes.get("column_header", {}).get("hex", "#FF2600")),
        "note":          _hex_to_rgb(color_classes.get("note", {}).get("hex", "#00F900")),
        "legend":        _hex_to_rgb(color_classes.get("legend", {}).get("hex", "#AA7942")),
        "sheet_info":    _hex_to_rgb(color_classes.get("sheet_info", {}).get("hex", "#0433FF")),
        "whole_sheet":   _hex_to_rgb(color_classes.get("whole_sheet", {}).get("hex", "#FF9300")),
        "xenoglyph":     _hex_to_rgb(color_classes.get("xenoglyph", {}).get("hex", "#FF40FF")),
    }

    page_struct = schema.get("page_structure", {})
    columns       = page_struct.get("columns", [])
    headers       = page_struct.get("column_headers", [])
    notes         = page_struct.get("notes", [])
    legend_boxes  = page_struct.get("legend_boxes", [])
    xenoglyphs    = page_struct.get("xenoglyph_boxes", [])
    sheet_info    = page_struct.get("sheet_info_bbox")
    whole_sheet   = page_struct.get("whole_sheet_bbox")

    # group by page for faster overlay
    def group_by_page(entries):
        pages = {}
        for e in entries:
            page = e.get("page_number", 1)
            pages.setdefault(page, []).append(e)
        return pages

    col_by_page    = group_by_page(columns)
    hdr_by_page    = group_by_page(headers)
    note_by_page   = group_by_page(notes)
    legend_by_page = group_by_page(legend_boxes)
    xeno_by_page   = group_by_page(xenoglyphs)

    doc = fitz.open(str(pdf_p))
    zoom = dpi / 72.0

    for page_index, page in enumerate(doc, start=1):
        print(f">>> VIS-DEBUG: Rendering page {page_index}")
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        draw = ImageDraw.Draw(img)

        def draw_boxes(entries, rgb, label: str):
            for e in entries:
                bbox = e.get("bbox")
                if not bbox or len(bbox) != 4:
                    continue
                x0, y0, x1, y1 = bbox
                # PDF coords -> image coords
                x0 *= zoom
                y0 *= zoom
                x1 *= zoom
                y1 *= zoom
                draw.rectangle([x0, y0, x1, y1], outline=rgb, width=3)
                draw.text((x0 + 3, y0 + 3), label, fill=rgb)

        # whole sheet & sheet info are optional single boxes
        if whole_sheet and whole_sheet.get("page_number", 1) == page_index:
            draw_boxes([whole_sheet], class_colors["whole_sheet"], "WHOLE")

        if sheet_info and sheet_info.get("page_number", 1) == page_index:
            draw_boxes([sheet_info], class_colors["sheet_info"], "SHEET_INFO")

        draw_boxes(col_by_page.get(page_index, []),    class_colors["column"],        "COL")
        draw_boxes(hdr_by_page.get(page_index, []),    class_colors["column_header"], "HDR")
        draw_boxes(note_by_page.get(page_index, []),   class_colors["note"],          "NOTE")
        draw_boxes(legend_by_page.get(page_index, []), class_colors["legend"],        "LEGEND")
        draw_boxes(xeno_by_page.get(page_index, []),   class_colors["xenoglyph"],     "XENO")

        out_path = out_dir / f"visual_page_{page_index}.png"
        img.save(str(out_path))
        print(f">>> VIS-DEBUG: Saved {out_path}")
