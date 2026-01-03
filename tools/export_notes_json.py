# export_notes_json.py
# Export chunked + visual-aligned notes to JSON for downstream apps.
#
# Usage example (from project root):
#
#   py tools\export_notes_json.py --page 1 --out exports\notes_page_1_notes.json --notes-only
#
#   py tools\export_notes_json.py --all-pages --out exports\all_pages_notes_sheetwide.json --notes-only
#
# This will:
#   1. Run the visual pipeline on test.pdf
#   2. Run the text Chunker with visual bridge wired in
#   3. Filter chunks according to CLI filters
#   4. Write a JSON file with all matching chunks

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# ---------------------------------------------------------------------
# Project root / imports
# ---------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]

# Ensure project root is on sys.path so imports work when running from tools/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backbone.visual.visual_pipeline_integrator import VisualPipelineIntegrator
from backbone.visual.visual_chunker_bridge import VisualChunkerBridge
from backbone.chunking import Chunker
from backbone.chunking.chunk import Chunk
from backbone.chunking.sheet_type_detector import detect_sheet_type


# ---------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------


def run_visual_pipeline(pdf_path: str) -> Dict[str, Any]:
    """
    Run the visual pipeline and return its result dict.
    """
    print(">>> STEP 1: Running visual pipeline...")
    integrator = VisualPipelineIntegrator()
    result = integrator.run(
        pdf_path=pdf_path,
        annotation_path="backbone/visual/schemas/page3_annotation.json",
        schema_path="backbone/visual/schemas/visual_note_schema.json",
        score_notes=True,
        make_debug_overlays=False,
        debug_output_dir="visual_debug",
    )

    pages = result.get("pages", {})
    fused_notes = result.get("fused_notes", [])
    print(f"    - Pages with visual: {sorted(pages.keys())}")
    print(f"    - Total annotated notes: {len(fused_notes)}")

    return result


def run_text_chunker(pdf_path: str, visual_pages: Dict[str, Any]) -> List[Chunk]:
    """
    Run the text Chunker with the visual bridge wired in and return all chunks.
    """
    print("\n>>> STEP 2: Running text chunker...")
    bridge = VisualChunkerBridge()
    chunker = Chunker(visual_pages=visual_pages, visual_bridge=bridge)
    chunks: List[Chunk] = chunker.process(pdf_path)
    print(f"    - Total chunks from Chunker: {len(chunks)}")
    return chunks


def find_notes_sheet_pages(chunks: List[Chunk]) -> Set[int]:
    """
    Use detect_sheet_type(page_number, chunks) to find which pages are notes sheets.

    This mirrors the chunker behavior so we stay in sync with core logic.
    """
    by_page: Dict[int, List[Chunk]] = {}
    for ch in chunks:
        page = getattr(ch, "page", None)
        if page is None:
            continue
        by_page.setdefault(page, []).append(ch)

    notes_pages: Set[int] = set()
    for page, page_chunks in by_page.items():
        # detect_sheet_type signature is detect_sheet_type(page_number, chunks)
        sheet_type = detect_sheet_type(page, page_chunks)
        if sheet_type == "notes_sheet":
            notes_pages.add(page)

    return notes_pages


def is_note_like(chunk: Chunk) -> bool:
    """
    Decide if this chunk should be treated as "note-like"
    based on chunk-level tags alone.

    We consider:
      - chunk.type in {"note", "merged_note", "merged"}
      - OR visual_region_class in {"note", "special_note"}
      - OR sheet_type == "notes_sheet" in metadata (if present)
    """
    ch_type = getattr(chunk, "type", None)
    metadata = getattr(chunk, "metadata", {}) or {}

    visual_region = metadata.get("visual_region_class")
    sheet_type = metadata.get("sheet_type")

    if ch_type in {"note", "merged_note", "merged"}:
        return True

    if visual_region in {"note", "special_note"}:
        return True

    if sheet_type == "notes_sheet":
        return True

    return False


def chunk_matches_filters(
    chunk: Chunk,
    page: Optional[int],
    notes_only: bool,
    sheet_type_filter: Optional[str],
    min_confidence: Optional[float],
    notes_sheet_pages: Optional[Set[int]],
) -> bool:
    """
    Apply all CLI filters to a chunk.

    Filters:
        - page: if provided, chunk.page must equal this value.
        - notes_only: if True, chunk must be note-like or on a notes_sheet page.
        - sheet_type_filter: if provided, metadata.sheet_type must match.
        - min_confidence: if provided, metadata.visual_confidence must be >= this value.
    """
    # Page filter
    if page is not None:
        if getattr(chunk, "page", None) != page:
            return False

    metadata = getattr(chunk, "metadata", {}) or {}

    # Notes-only filter
    if notes_only:
        base_note_like = is_note_like(chunk)
        page_num = getattr(chunk, "page", None)
        on_notes_page = (
            notes_sheet_pages is not None
            and isinstance(page_num, int)
            and page_num in notes_sheet_pages
        )
        if not (base_note_like or on_notes_page):
            return False

    # Sheet type filter (direct metadata check)
    if sheet_type_filter is not None:
        sheet_type = metadata.get("sheet_type") or "unknown"
        if sheet_type != sheet_type_filter:
            return False

    # Minimum visual confidence filter
    if min_confidence is not None:
        vis_conf = metadata.get("visual_confidence")
        if vis_conf is None:
            vis_conf_val = 0.0
        else:
            try:
                vis_conf_val = float(vis_conf)
            except (TypeError, ValueError):
                vis_conf_val = 0.0

        if vis_conf_val < min_confidence:
            return False

    return True


def serialize_chunk(chunk: Chunk) -> Dict[str, Any]:
    """
    Convert a Chunk / MergedChunk into a JSON-friendly dict.
    """
    metadata = getattr(chunk, "metadata", {}) or {}

    bbox = getattr(chunk, "bbox", None)
    if bbox is not None and len(bbox) == 4:
        bbox_dict: Optional[Dict[str, float]] = {
            "x0": float(bbox[0]),
            "y0": float(bbox[1]),
            "x1": float(bbox[2]),
            "y1": float(bbox[3]),
        }
    else:
        bbox_dict = None

    return {
        "id": getattr(chunk, "id", None),
        "content": (getattr(chunk, "content", "") or "").strip(),
        "type": getattr(chunk, "type", None),
        "page": getattr(chunk, "page", None),
        "source_file": getattr(chunk, "source_file", None),
        "bbox": bbox_dict,
        "visual_region_class": metadata.get("visual_region_class"),
        "visual_region_id": metadata.get("visual_region_id"),
        "visual_note_id": metadata.get("visual_note_id"),
        "visual_column_id": metadata.get("visual_column_id"),
        "visual_column_index": metadata.get("visual_column_index"),
        "visual_confidence": metadata.get("visual_confidence"),
        "sheet_type": metadata.get("sheet_type"),
        "metadata": metadata,
    }


def build_export_structure(
    pdf_path: str,
    chunks: List[Chunk],
    page: Optional[int],
    notes_only: bool,
    sheet_type_filter: Optional[str],
    min_confidence: Optional[float],
) -> Dict[str, Any]:
    """
    Filter chunks according to CLI options and build the export JSON structure.
    """
    print("\n>>> STEP 3: Filtering chunks for export...")

    # Determine which pages are notes sheets using detect_sheet_type
    notes_sheet_pages: Optional[Set[int]] = None
    if notes_only:
        notes_sheet_pages = find_notes_sheet_pages(chunks)
        print(f"    - Detected notes_sheet pages: {sorted(notes_sheet_pages)}")

    filtered: List[Dict[str, Any]] = []
    per_page_counts: Dict[int, int] = {}

    for ch in chunks:
        if not chunk_matches_filters(
            chunk=ch,
            page=page,
            notes_only=notes_only,
            sheet_type_filter=sheet_type_filter,
            min_confidence=min_confidence,
            notes_sheet_pages=notes_sheet_pages,
        ):
            continue

        serialized = serialize_chunk(ch)
        filtered.append(serialized)

        p = serialized.get("page")
        if isinstance(p, int):
            per_page_counts[p] = per_page_counts.get(p, 0) + 1

    print(f"    - Exporting {len(filtered)} chunk(s) matching filters.")
    if per_page_counts:
        print("    - Counts per page:")
        for p in sorted(per_page_counts.keys()):
            print(f"        Page {p}: {per_page_counts[p]} chunks")

    export_obj: Dict[str, Any] = {
        "pdf_path": pdf_path,
        "filter": {
            "page": page,
            "notes_only": notes_only,
            "sheet_type": sheet_type_filter,
            "min_confidence": min_confidence,
        },
        "summary": {
            "total_exported_chunks": len(filtered),
            "per_page_counts": per_page_counts,
        },
        "chunks": filtered,
    }

    return export_obj


def write_json(output_path: Path, data: Dict[str, Any]) -> None:
    """
    Write JSON to disk, ensuring parent folders exist.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"\n>>> JSON written to: {output_path}")


# ---------------------------------------------------------------------
# CLI parsing and entry point
# ---------------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export backbone chunked notes to JSON."
    )

    parser.add_argument(
        "--pdf",
        type=str,
        default="test.pdf",
        help="Path to the PDF to process (default: test.pdf)",
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--page",
        type=int,
        help="Single page number to export.",
    )
    group.add_argument(
        "--all-pages",
        action="store_true",
        help="Export chunks from all pages.",
    )

    parser.add_argument(
        "--out",
        type=str,
        required=True,
        help="Output JSON file path (e.g. exports\\notes_page_1_notes.json).",
    )

    parser.add_argument(
        "--notes-only",
        action="store_true",
        help="If set, only export note-like chunks.",
    )

    parser.add_argument(
        "--sheet-type",
        type=str,
        choices=["notes_sheet", "general"],
        help="Optional: limit to a specific sheet type.",
    )

    parser.add_argument(
        "--min-confidence",
        type=float,
        default=None,
        help="Optional: minimum visual_confidence required (e.g. 0.7).",
    )

    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)

    pdf_path = args.pdf
    out_path = Path(args.out)

    if not Path(pdf_path).exists():
        print(f"ERROR: PDF not found: {pdf_path}")
        sys.exit(1)

    if args.all_pages:
        page_filter: Optional[int] = None
    else:
        page_filter = args.page

    visual_result = run_visual_pipeline(pdf_path)
    visual_pages = visual_result.get("pages", {})

    chunks = run_text_chunker(pdf_path, visual_pages)

    export_data = build_export_structure(
        pdf_path=pdf_path,
        chunks=chunks,
        page=page_filter,
        notes_only=args.notes_only,
        sheet_type_filter=args.sheet_type,
        min_confidence=args.min_confidence,
    )

    write_json(out_path, export_data)

    print("\n>>> DONE.")


if __name__ == "__main__":
    main()
