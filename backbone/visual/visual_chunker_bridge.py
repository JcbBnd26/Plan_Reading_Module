"""Bridge between visual annotation data and text chunks.

This module takes the per‑page structures produced by
:class:`VisualPipelineIntegrator` and attaches them to Chunk objects
(see :mod:`backbone.chunking.chunk`).

A chunk may receive the following metadata keys:

    - visual_region_class : "note", "legend", "sheet_info", etc.
    - visual_region_id    : ID of the matched visual region
    - visual_note_id      : ID of the note region (if class == "note")
    - visual_column_id    : ID of the column region (if applicable)
    - visual_column_index : 1‑based index of the column
    - visual_confidence   : float in [0, 1] indicating alignment confidence
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from backbone.chunking.chunk import Chunk

BBox = Tuple[float, float, float, float]

INTERSECT_PAD = 4.0


def _point_inside(px: float, py: float, box: BBox) -> bool:
    x0, y0, x1, y1 = box
    return (x0 <= px <= x1) and (y0 <= py <= y1)


def _boxes_intersect(a: BBox, b: BBox, pad: float = INTERSECT_PAD) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b

    # Expand a slightly to be tolerant of OCR noise
    ax0 -= pad
    ay0 -= pad
    ax1 += pad
    ay1 += pad

    if ax1 < bx0 or bx1 < ax0:
        return False
    if ay1 < by0 or by1 < ay0:
        return False
    return True


class VisualChunkerBridge:
    """Attach visual metadata to a page's chunks."""

    # ------------------------------------------------------------------
    def attach_visual_metadata_to_page(
        self,
        chunks: List[Chunk],
        visual_page_struct: Dict[str, Any],
    ) -> List[Chunk]:
        """Compatibility wrapper used by :class:`Chunker`.

        The chunker expects this method name. We simply forward to
        :meth:`attach_visual_metadata` and catch any unexpected errors.
        """
        try:
            self.attach_visual_metadata(chunks, visual_page_struct)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"VISUAL BRIDGE ERROR inside attach_visual_metadata_to_page: {exc}")
        return chunks

    # ------------------------------------------------------------------
    def attach_visual_metadata(
        self,
        chunks: List[Chunk],
        visual_page: Dict[str, Any],
    ) -> None:
        """Mutate chunks in place by attaching visual metadata.

        Parameters
        ----------
        chunks:
            List of Chunk (or MergedChunk) objects for the current page.
        visual_page:
            Page entry from VisualPipelineIntegrator.run(...)["pages"][page].
        """
        if not chunks or not visual_page:
            return

        notes = visual_page.get("notes") or []
        columns = visual_page.get("columns") or []
        legends = visual_page.get("legend") or []
        infos = visual_page.get("sheet_info") or []
        specials = visual_page.get("special_note") or []
        xenos = visual_page.get("xenoglyph") or []

        all_regions = {
            "note": notes,
            "column": columns,
            "legend": legends,
            "sheet_info": infos,
            "special_note": specials,
            "xenoglyph": xenos,
        }

        for ch in chunks:
            if not ch.bbox:
                continue

            cx = (ch.bbox[0] + ch.bbox[2]) / 2.0
            cy = (ch.bbox[1] + ch.bbox[3]) / 2.0

            best_match: Optional[Dict[str, Any]] = None
            best_class: Optional[str] = None

            # 1. Primary: center point inside a region
            for cls_name, region_list in all_regions.items():
                for reg in region_list:
                    bbox = reg.get("bbox")
                    if bbox and _point_inside(cx, cy, bbox):
                        best_match = reg
                        best_class = cls_name
                        break
                if best_match:
                    break

            # 2. Fallback: bbox intersection
            if not best_match:
                for cls_name, region_list in all_regions.items():
                    for reg in region_list:
                        bbox = reg.get("bbox")
                        if bbox and _boxes_intersect(ch.bbox, bbox):
                            best_match = reg
                            best_class = cls_name
                            break
                    if best_match:
                        break

            # 3. Attach metadata
            if best_match:
                meta = ch.metadata
                meta["visual_region_class"] = best_class
                meta["visual_region_id"] = best_match.get("id") or best_match.get("class_id")

                if best_class == "note":
                    meta["visual_note_id"] = best_match.get("id")
                    meta["visual_confidence"] = best_match.get("confidence", 0.5)

                    if "column_id" in best_match:
                        meta["visual_column_id"] = best_match.get("column_id")
                    if "column_index" in best_match:
                        meta["visual_column_index"] = best_match.get("column_index") or None

                elif best_class == "column":
                    meta["visual_column_id"] = best_match.get("id")
                    meta["visual_column_index"] = best_match.get("column_index") or None
            else:
                # No visual hit – normalise keys so downstream code can rely
                # on their existence.
                meta = ch.metadata
                meta.setdefault("visual_region_class", None)
                meta.setdefault("visual_region_id", None)
                meta.setdefault("visual_note_id", None)
                meta.setdefault("visual_column_id", None)
                meta.setdefault("visual_column_index", None)
                meta.setdefault("visual_confidence", 0.0)
