"""
Visual pipeline integrator.

This module reads a JSON annotation file that describes color-coded bounding
boxes on a note sheet image and aligns those boxes with the coordinates of the
source PDF. The result is a per-page structure that can be used by the text
chunker to attach visual metadata (which note box / column a chunk belongs to).

Assumptions
-----------
- The annotation JSON follows the structure you provided in `page3_annotation.json`:
  {
      "metadata": {
          "image_size_px": {"width": 6800, "height": 4400},
          ...
      },
      "classes": [...],
      "pages": [
          {
              "page_index": 0,   # zero-based
              "regions": {
                  "column": [...],
                  "note":   [...],
                  ...
              }
          }
      ]
  }
- BBoxes in the JSON are given in the *image* coordinate system, with origin
  at the top-left and units in pixels.
- The PDF page we run against has the same aspect ratio as the annotated image.

This module is intentionally self-contained so the rest of the system only has
to consume a very simple structure:

result = {
    "metadata": {...},
    "pages": {
        1: {
            "columns": [ { "id": str, "bbox": (x0,y0,x1,y1), "column_index": int, ... }, ... ],
            "notes":   [ { "id": str, "bbox": (x0,y0,x1,y1), "column_index": int or None,
                           "confidence": float, ... }, ... ],
            "legend": [...],
            "sheet_info": [...],
            "whole_sheet": [...],
            "xenoglyph": [...],
            "special_note": [...],
            "plan_title": [...]
        },
        ...
    },
    "fused_notes": [list of all note dicts across pages]
}
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .visual_alignment import VisualAlignment  # NEW: alignment layer

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover - import guard
    fitz = None

try:
    from PIL import Image, ImageDraw
except Exception:  # pragma: no cover - import guard
    Image = None
    ImageDraw = None


BBox = Tuple[float, float, float, float]


@dataclass
class VisualPipelineConfig:
    """
    Configuration for the visual pipeline.

    Paths are resolved relative to this file by default; you can still
    override them explicitly when calling `run(...)`.
    """

    annotation_path: Optional[str] = None
    schema_path: Optional[str] = None
    make_debug_overlays: bool = False
    debug_output_dir: str = "visual_debug"
    enable_note_scoring: bool = True


class VisualPipelineIntegrator:
    """
    High-level entry point for the visual pipeline.

    Typical usage (for debugging) from the project root:

        py -c "from backbone.visual.visual_pipeline_integrator import VisualPipelineIntegrator; \
v = VisualPipelineIntegrator(); \
r = v.run(pdf_path='test.pdf'); \
print('Pages with visual data:', list(r['pages'].keys())); \
print('Total fused notes:', len(r['fused_notes']))"
    """

    def __init__(self, config: Optional[VisualPipelineConfig] = None) -> None:
        base_dir = os.path.dirname(__file__)
        default_annotation = os.path.join(base_dir, "schemas", "page3_annotation.json")
        default_schema = os.path.join(base_dir, "schemas", "visual_note_schema.json")

        self.config = config or VisualPipelineConfig()
        if self.config.annotation_path is None:
            self.config.annotation_path = default_annotation
        if self.config.schema_path is None:
            self.config.schema_path = default_schema

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(
        self,
        pdf_path: str,
        schema_path: Optional[str] = None,
        annotation_path: Optional[str] = None,
        score_notes: bool = True,
        make_debug_overlays: Optional[bool] = None,
        debug_output_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run the visual pipeline on the given PDF.

        Parameters
        ----------
        pdf_path:
            Path to the PDF you want to align with the annotation JSON.
        schema_path:
            Optional path to a visual schema / rules JSON. If omitted, the
            default from `VisualPipelineConfig` is used. Currently this is
            only loaded for future use; note scoring is done with simple
            built-in heuristics.
        annotation_path:
            Optional explicit path to the annotation JSON (e.g.
            backbone/visual/schemas/page3_annotation.json). If omitted, the
            default from `VisualPipelineConfig` is used.
        score_notes:
            Whether to assign a simple confidence score to each note box.
        make_debug_overlays:
            If True, render PNG overlays showing the boxes on top of the PDF
            pages. If omitted, the value from the config is used.
        debug_output_dir:
            Folder where debug PNGs are written.

        Returns
        -------
        dict with keys: "metadata", "pages", "fused_notes".
        """

        cfg = self.config

        schema_path = schema_path or cfg.schema_path
        annotation_path = annotation_path or cfg.annotation_path
        if make_debug_overlays is None:
            make_debug_overlays = cfg.make_debug_overlays
        if debug_output_dir is None:
            debug_output_dir = cfg.debug_output_dir

        result: Dict[str, Any] = {
            "metadata": {},
            "pages": {},
            "fused_notes": [],
        }

        if not os.path.exists(pdf_path):
            print(f">>> VISUAL PIPELINE: PDF not found: {os.path.abspath(pdf_path)}")
            return result

        if annotation_path is None or not os.path.exists(annotation_path):
            print(f">>> VISUAL PIPELINE: Annotation JSON not found: {annotation_path}")
            return result

        # Load JSON files ------------------------------------------------
        with open(annotation_path, "r", encoding="utf-8") as f:
            ann_data = json.load(f)

        schema_data: Optional[Dict[str, Any]] = None
        if schema_path and os.path.exists(schema_path):
            try:
                with open(schema_path, "r", encoding="utf-8") as f:
                    schema_data = json.load(f)
            except Exception as exc:  # pragma: no cover
                print(f">>> VISUAL PIPELINE: Failed to load schema: {exc}")

        result["metadata"] = ann_data.get("metadata", {})
        image_meta = result["metadata"].get("image_size_px", {})
        img_w = float(image_meta.get("width") or 0.0)
        img_h = float(image_meta.get("height") or 0.0)

        # --------------------------------------------------------------
        # ALIGN RAW ANNOTATION BOXES IN IMAGE COORDINATES
        # --------------------------------------------------------------
        if img_w > 0 and img_h > 0:
            aligner = VisualAlignment(int(img_w), int(img_h))
            pages_raw = ann_data.get("pages", []) or []
            aligned_pages = []
            for page_entry in pages_raw:
                regions = page_entry.get("regions") or {}
                aligned_regions = aligner.align_page(regions)
                new_entry = dict(page_entry)
                new_entry["regions"] = aligned_regions
                aligned_pages.append(new_entry)
            ann_data["pages"] = aligned_pages

        if fitz is None:
            print(">>> VISUAL PIPELINE: PyMuPDF (fitz) is not available; "
                  "cannot align annotation to PDF coordinates.")
            return result

        doc = fitz.open(pdf_path)

        pages_result: Dict[int, Dict[str, Any]] = {}
        fused_notes: List[Dict[str, Any]] = []

        pages = ann_data.get("pages", [])
        if not pages:
            print(">>> VISUAL PIPELINE: No 'pages' array found in annotation JSON.")
            return result

        for page_entry in pages:
            page_index = int(page_entry.get("page_index", 0))
            page_number = page_index + 1  # convert zero-based to 1-based

            if page_index < 0 or page_index >= len(doc):
                print(f">>> VISUAL PIPELINE: page_index {page_index} out of range for PDF.")
                continue

            pdf_page = doc[page_index]
            rect = pdf_page.rect
            pdf_w = float(rect.width)
            pdf_h = float(rect.height)

            # Fallback: if the JSON does not contain image size, pretend
            # it already uses PDF coordinates.
            if img_w <= 0 or img_h <= 0:
                scale_x = 1.0
                scale_y = 1.0
            else:
                scale_x = pdf_w / img_w
                scale_y = pdf_h / img_h

            regions = page_entry.get("regions", {})

            # Normalised per-page structure
            page_struct: Dict[str, List[Dict[str, Any]]] = {
                "columns": [],
                "column_headers": [],
                "notes": [],
                "legend": [],
                "sheet_info": [],
                "whole_sheet": [],
                "xenoglyph": [],
                "special_note": [],
                "plan_title": [],
            }

            def _norm_bbox(raw_bbox: List[float]) -> BBox:
                x0, y0, x1, y1 = raw_bbox
                return (
                    float(x0) * scale_x,
                    float(y0) * scale_y,
                    float(x1) * scale_x,
                    float(y1) * scale_y,
                )

            def _convert_region(cls_key: str, target_key: str) -> None:
                items = regions.get(cls_key, []) or []
                converted: List[Dict[str, Any]] = []
                for item in items:
                    raw_bbox = item.get("bbox")
                    if not raw_bbox or len(raw_bbox) != 4:
                        continue
                    bbox = _norm_bbox(raw_bbox)
                    entry: Dict[str, Any] = {
                        "id": item.get("id"),
                        "class": item.get("class") or cls_key,
                        "bbox": bbox,
                        "color_hex": item.get("color_hex"),
                        "page": page_number,
                    }
                    if "area_px" in item:
                        entry["area_px"] = item["area_px"]
                    if "border_pixels" in item:
                        entry["border_pixels"] = item["border_pixels"]
                    converted.append(entry)
                page_struct[target_key] = converted

            # Map JSON region keys to our canonical keys
            mapping = {
                "column": "columns",
                "column_header": "column_headers",
                "note": "notes",
                "legend": "legend",
                "sheet_info": "sheet_info",
                "whole_sheet": "whole_sheet",
                "xenoglyph": "xenoglyph",
                "special_note": "special_note",
                "plan_title": "plan_title",
            }

            for cls_key, target_key in mapping.items():
                _convert_region(cls_key, target_key)

            # Assign 1-based indices to columns for convenience
            for idx, col in enumerate(page_struct["columns"], start=1):
                col["column_index"] = idx

            # Attach note -> column mapping
            for note in page_struct["notes"]:
                bbox = note["bbox"]
                cx = (bbox[0] + bbox[2]) / 2.0
                cy = (bbox[1] + bbox[3]) / 2.0

                best_col: Optional[Dict[str, Any]] = None
                for col in page_struct["columns"]:
                    x0, y0, x1, y1 = col["bbox"]
                    if x0 <= cx <= x1 and y0 <= cy <= y1:
                        best_col = col
                        break

                if best_col is not None:
                    note["column_id"] = best_col.get("id")
                    note["column_index"] = best_col.get("column_index")
                else:
                    note["column_id"] = None
                    note["column_index"] = None

            # Apply simple heuristic note confidence if requested
            if score_notes and page_struct["notes"]:
                for note in page_struct["notes"]:
                    note["confidence"] = self._simple_note_confidence(
                        note,
                        page_struct["columns"],
                        schema_data=schema_data,
                    )
            else:
                for note in page_struct["notes"]:
                    note.setdefault("confidence", 1.0)

            pages_result[page_number] = page_struct
            fused_notes.extend(page_struct["notes"])

        result["pages"] = pages_result
        result["fused_notes"] = fused_notes

        if make_debug_overlays:
            self._render_debug_overlays(
                pdf_path=pdf_path,
                pages_result=pages_result,
                output_dir=debug_output_dir,
            )

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _simple_note_confidence(
        self,
        note: Dict[str, Any],
        columns: List[Dict[str, Any]],
        schema_data: Optional[Dict[str, Any]] = None,
    ) -> float:
        """
        Very lightweight heuristic for note confidence.

        Factors considered:
        - Whether the note is assigned to a column.
        - How tall the note is relative to the column.
        - Whether a color is present (matching the configured "note" color
          in the schema, if provided).

        Returns a float in [0.0, 1.0].
        """
        base = 0.5

        if note.get("column_id") is not None:
            base += 0.2

        bbox = note.get("bbox")
        height = (bbox[3] - bbox[1]) if bbox else 0.0

        col_height = 0.0
        for col in columns:
            if col.get("id") == note.get("column_id"):
                cb = col.get("bbox")
                if cb:
                    col_height = max(col_height, cb[3] - cb[1])
        if col_height > 0:
            ratio = max(0.0, min(1.0, height / col_height))
            base += 0.2 * ratio

        # Optional color check
        if schema_data:
            try:
                classes = schema_data.get("classes") or schema_data.get("color_classes") or []
                expected_note_hex = None
                if isinstance(classes, list):
                    for cls in classes:
                        if str(cls.get("name")).lower() == "note":
                            expected_note_hex = str(cls.get("color_hex") or cls.get("hex"))
                            break
                elif isinstance(classes, dict):
                    note_cfg = classes.get("note") or {}
                    expected_note_hex = note_cfg.get("hex") or note_cfg.get("color_hex")

                if expected_note_hex:
                    expected_hex = expected_note_hex.strip().lower()
                    actual_hex = str(note.get("color_hex") or "").strip().lower()
                    if actual_hex == expected_hex:
                        base += 0.1
            except Exception:
                # Stay robust even if schema doesn't match expectations
                pass

        return float(max(0.0, min(1.0, base)))

    def _render_debug_overlays(
        self,
        pdf_path: str,
        pages_result: Dict[int, Dict[str, Any]],
        output_dir: str,
    ) -> None:
        """
        Render simple PNG overlays showing the detected boxes.

        Colors are chosen for clarity only and do not attempt to match the
        original annotation colors.
        """
        if fitz is None or Image is None or ImageDraw is None:
            print(">>> VISUAL PIPELINE: Debug overlays disabled "
                  "(required libraries not available).")
            return

        os.makedirs(output_dir, exist_ok=True)
        doc = fitz.open(pdf_path)

        for page_number, page_struct in pages_result.items():
            if page_number - 1 >= len(doc):
                continue

            pdf_page = doc[page_number - 1]
            pix = pdf_page.get_pixmap()
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            draw = ImageDraw.Draw(img)

            print(f">>> VIS-DEBUG: Rendering page {page_number}")

            # Columns: thin rectangles
            for col in page_struct.get("columns", []):
                bbox = col.get("bbox")
                if not bbox:
                    continue
                draw.rectangle(bbox, outline="cyan", width=3)

            # Notes: slightly thicker rectangles
            for note in page_struct.get("notes", []):
                bbox = note.get("bbox")
                if not bbox:
                    continue
                draw.rectangle(bbox, outline="lime", width=2)

            # Legend / sheet info / xenoglyphs
            for legend in page_struct.get("legend", []):
                bbox = legend.get("bbox")
                if not bbox:
                    continue
                draw.rectangle(bbox, outline="orange", width=3)

            for info in page_struct.get("sheet_info", []):
                bbox = info.get("bbox")
                if not bbox:
                    continue
                draw.rectangle(bbox, outline="blue", width=3)

            for xen in page_struct.get("xenoglyph", []):
                bbox = xen.get("bbox")
                if not bbox:
                    continue
                draw.rectangle(bbox, outline="magenta", width=3)

            out_name = os.path.join(output_dir, f"visual_page_{page_number}.png")
            img.save(out_name)
            print(f">>> VIS-DEBUG: Saved {out_name}")
