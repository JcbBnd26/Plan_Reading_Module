"""High‑level text chunker with optional visual integration.

Responsibilities:

    * open a PDF
    * extract low‑level line chunks (one Chunk per text line)
    * detect sheet type (notes_sheet vs general)
    * optionally attach visual metadata via VisualChunkerBridge
    * group note‑sheet lines into semantic notes via SemanticGrouper
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import fitz  # PyMuPDF

from backbone.chunking.chunk import Chunk
from backbone.chunking.semantic_grouper import SemanticGrouper, SemanticGrouperConfig
from backbone.chunking.sheet_type_detector import detect_sheet_type


@dataclass
class ChunkerConfig:
    debug: bool = True
    use_line_level_extractor: bool = True


class Chunker:
    """PDF → Chunks (with optional visual metadata + grouping)."""

    def __init__(
        self,
        config: Optional[ChunkerConfig] = None,
        visual_pages: Optional[Dict[int, Dict[str, Any]]] = None,
        visual_bridge: Optional[Any] = None,
    ) -> None:
        self.config = config or ChunkerConfig()
        self.grouper = SemanticGrouper(SemanticGrouperConfig())

        # Visual metadata (optional)
        self.visual_pages: Optional[Dict[int, Dict[str, Any]]] = visual_pages
        self.visual_bridge = visual_bridge

        if self.visual_pages and self.visual_bridge and self.config.debug:
            print(">>> VISUAL BRIDGE: visual metadata loaded.")
        elif self.config.debug:
            print(">>> VISUAL BRIDGE: disabled or not available.")

    # ------------------------------------------------------------------
    def process(self, pdf_path: str) -> List[Chunk]:
        """Process an entire PDF into a flat list of chunks."""
        if self.config.debug:
            print(">>> STARTING PER-PAGE CHUNKER")
            print(f">>> Source PDF: {pdf_path}")
            if self.config.use_line_level_extractor:
                print(">>> USING LINE-LEVEL EXTRACTOR <<<")

        doc = fitz.open(pdf_path)
        all_chunks: List[Chunk] = []

        for page_index in range(len(doc)):
            page_number = page_index + 1
            pdf_page = doc[page_index]

            raw_page_chunks = self._extract_page_lines(pdf_page, page_number)

            if not raw_page_chunks:
                if self.config.debug:
                    print(f"\n>>> PROCESSING PAGE {page_number}")
                    print("    Raw chunks on page: 0")
                continue

            if self.config.debug:
                print(f"\n>>> PROCESSING PAGE {page_number}")
                print(f"    Raw chunks on page: {len(raw_page_chunks)}")

            sheet_type = detect_sheet_type(page_number, raw_page_chunks)
            if self.config.debug:
                print(f"    Sheet type: {sheet_type}")

            # Optional: attach visual metadata for this page
            if self.visual_pages and self.visual_bridge:
                vp = self.visual_pages.get(page_number)
                if vp:
                    try:
                        self.visual_bridge.attach_visual_metadata_to_page(raw_page_chunks, vp)
                    except Exception as exc:  # pragma: no cover - defensive
                        print(f"    VISUAL BRIDGE ERROR (Page {page_number}): {exc}")

            # Group into semantic units for notes sheets
            if sheet_type.lower() == "notes_sheet":
                grouped = self.grouper.group_page_chunks(raw_page_chunks, sheet_type)
            else:
                grouped = raw_page_chunks

            if self.config.debug:
                print(f"    Chunks after grouping: {len(grouped)}")

            all_chunks.extend(grouped)

        if self.config.debug:
            print(f"\n>>> TOTAL CHUNKS AFTER GROUPING: {len(all_chunks)}")

        return all_chunks

    # ------------------------------------------------------------------
    def _extract_page_lines(self, pdf_page: "fitz.Page", page_number: int) -> List[Chunk]:
        """Return one Chunk per text line on the page."""
        chunks: List[Chunk] = []

        # Use PyMuPDF's plain text extraction with bbox info
        blocks = pdf_page.get_text("blocks")  # (x0, y0, x1, y1, text, block_no, block_type, ...)
        for block in blocks:
            if len(block) < 5:
                continue
            x0, y0, x1, y1, text, *_ = block
            if not text or not text.strip():
                continue

            # Split into lines but keep the same bbox – good enough for now.
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue

                ch = Chunk(
                    content=line,
                    type="text_line",
                    bbox=(float(x0), float(y0), float(x1), float(y1)),
                    page=page_number,
                    source_file=None,
                )
                chunks.append(ch)

        return chunks
