"""Quick visual <-> text alignment diagnostic harness.

Usage (from project root)::

    py run_visual_alignment_check.py

It will:

    1. Run the visual pipeline on test.pdf
    2. Run the text chunker (with visual metadata wired in)
    3. Print a preview of visually-annotated chunks for one page
"""

from __future__ import annotations

from typing import Any, Dict, List

from backbone.visual.visual_pipeline_integrator import VisualPipelineIntegrator
from backbone.visual.visual_chunker_bridge import VisualChunkerBridge
from backbone.chunking import Chunker
from backbone.chunking.chunk import Chunk


PDF_PATH = "test.pdf"
PAGE_TO_TEST = 1
PRINT_LIMIT = 30


def preview_chunk(ch: Chunk) -> Dict[str, Any]:
    """Return a compact dict showing key alignment info."""
    text = (getattr(ch, "content", "") or "").replace("\n", " ")
    if len(text) > 50:
        text = text[:50] + "..."

    metadata = getattr(ch, "metadata", {}) or {}

    return {
        "text": text,
        "page": getattr(ch, "page", None),
        "bbox": getattr(ch, "bbox", None),
        "visual_region": metadata.get("visual_region_class"),
        "visual_region_id": metadata.get("visual_region_id"),
        "visual_note_id": metadata.get("visual_note_id"),
        "visual_column_id": metadata.get("visual_column_id"),
        "visual_column_index": metadata.get("visual_column_index"),
        "visual_confidence": metadata.get("visual_confidence"),
    }


if __name__ == "__main__":
    # 1. Visual pipeline
    print(">>> STEP 1: Running visual pipeline...")
    visual_integrator = VisualPipelineIntegrator()
    visual_result = visual_integrator.run(
        pdf_path=PDF_PATH,
        annotation_path="backbone/visual/schemas/page3_annotation.json",
        schema_path="backbone/visual/schemas/visual_note_schema.json",
        score_notes=True,
        make_debug_overlays=True,
        debug_output_dir="visual_debug",
    )

    pages = visual_result.get("pages", {})
    fused_notes = visual_result.get("fused_notes", [])

    print(f"    - Pages with visual: {sorted(pages.keys())}")
    print(f"    - Total annotated notes: {len(fused_notes)}")

    # 2. Text chunker with visual bridge wired in
    print("\n>>> STEP 2: Running text chunker...")
    bridge = VisualChunkerBridge()
    chunker = Chunker(visual_pages=pages, visual_bridge=bridge)
    text_chunks: List[Chunk] = chunker.process(PDF_PATH)

    print(f"    - Total text chunks: {len(text_chunks)}")

    # 3. Inspect a single page
    print(f"\n>>> STEP 3: Attaching visual metadata for page {PAGE_TO_TEST}...")
    page_chunks = [
        ch for ch in text_chunks
        if getattr(ch, "page", None) == PAGE_TO_TEST
    ]
    print(f"    - Total page {PAGE_TO_TEST} chunks: {len(page_chunks)}")

    print("\n>>> PREVIEW (first {limit} chunks):\n".format(limit=PRINT_LIMIT))
    for ch in page_chunks[:PRINT_LIMIT]:
        info = preview_chunk(ch)
        print(info)

    print("\n>>> DONE.")
