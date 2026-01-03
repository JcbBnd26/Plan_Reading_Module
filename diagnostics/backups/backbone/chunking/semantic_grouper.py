"""Semantic grouping of low‑level text chunks into higher‑level blocks.

The input is a flat list of :class:`Chunk` objects for a single page,
typically representing individual text lines. The output is a list
of either:

    * the original Chunk objects (if no grouping is required), or
    * :class:`MergedChunk` objects representing full notes/paragraphs.

Heuristics are intentionally simple and debuggable. The grouping logic
is aware of:

    * note‑style numbering ("1.", "2.", etc.)
    * bullet characters ("•", "-" at start of line)
    * vertical spacing between lines
    * left‑edge alignment to keep paragraphs together
    * optional visual metadata (visual_note_id) when present
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .chunk import Chunk, MergedChunk


@dataclass
class SemanticGrouperConfig:
    max_line_gap: float = 18.0
    max_indent_delta: float = 25.0
    debug: bool = False


class SemanticGrouper:
    """Group low‑level chunks into semantic blocks (notes)."""

    def __init__(self, config: Optional[SemanticGrouperConfig] = None) -> None:
        self.config = config or SemanticGrouperConfig()

    # ------------------------------------------------------------------
    def group_page_chunks(self, chunks: List[Chunk], sheet_type: str) -> List[Chunk]:
        """Return grouped chunks for a single page.

        For non‑note sheets, the input is passed through unchanged.
        For note sheets, lines are grouped into :class:`MergedChunk`
        objects using simple layout + text heuristics.
        """
        if not chunks:
            return []

        if sheet_type.lower() != "notes_sheet":
            # No grouping for general sheets.
            return list(chunks)

        # If visual note IDs are present, use them as primary grouping signal.
        if any("visual_note_id" in ch.metadata for ch in chunks):
            return self._group_by_visual_note(chunks)

        # Otherwise use layout + numbering heuristics.
        return self._group_by_layout(chunks)

    # ------------------------------------------------------------------
    # Strategy A: group by visual note IDs when available
    # ------------------------------------------------------------------
    def _group_by_visual_note(self, chunks: List[Chunk]) -> List[Chunk]:
        by_note = {}
        leftovers: List[Chunk] = []

        for ch in chunks:
            vid = ch.metadata.get("visual_note_id") or ch.metadata.get("visual_region_id")
            if vid:
                by_note.setdefault(vid, []).append(ch)
            else:
                leftovers.append(ch)

        grouped: List[Chunk] = []
        for note_id, note_chunks in by_note.items():
            # sort by vertical position
            note_chunks_sorted = sorted(
                note_chunks,
                key=lambda c: (c.page or 0, (c.bbox or (0, 0, 0, 0))[1])
            )
            mc = MergedChunk.from_chunks(note_chunks_sorted, merge_type="note_group")
            mc.metadata["visual_note_id"] = note_id
            grouped.append(mc)

        # Add leftovers as‑is (title blocks, legend items, etc.).
        grouped.extend(leftovers)
        return grouped

    # ------------------------------------------------------------------
    # Strategy B: purely layout + text heuristics
    # ------------------------------------------------------------------
    def _group_by_layout(self, chunks: List[Chunk]) -> List[Chunk]:
        cfg = self.config

        # Sort by vertical position (top of bbox), then by x.
        sorted_chunks = sorted(
            chunks,
            key=lambda c: ((c.page or 0),
                           (c.bbox or (0, 0, 0, 0))[1],
                           (c.bbox or (0, 0, 0, 0))[0]),
        )

        groups: List[List[Chunk]] = []
        current: List[Chunk] = []

        prev: Optional[Chunk] = None

        for ch in sorted_chunks:
            if not ch.content:
                continue

            starts_new = self._starts_new_block(ch, prev)

            if starts_new and current:
                groups.append(current)
                current = []

            current.append(ch)
            prev = ch

        if current:
            groups.append(current)

        # Convert groups into MergedChunk objects
        merged: List[Chunk] = []
        for grp in groups:
            if len(grp) == 1:
                merged.append(grp[0])
            else:
                mc = MergedChunk.from_chunks(grp, merge_type="note_group")
                merged.append(mc)
        return merged

    # ------------------------------------------------------------------
    def _starts_new_block(self, ch: Chunk, prev: Optional[Chunk]) -> bool:
        """Return True if *ch* should start a new semantic block."""
        if prev is None:
            return True

        text = (ch.content or "").strip()
        prev_text = (prev.content or "").strip()

        # Strong signals: numbered notes or bullets
        if self._looks_like_numbered_note(text) or self._looks_like_bullet(text):
            return True

        # If previous line ended with a period and this one is capitalized,
        # treat as a new sentence/paragraph.
        if prev_text.endswith(".") and text[:1].isupper():
            return True

        # Layout‑based check: vertical gap too large
        if ch.bbox and prev.bbox:
            gap = ch.bbox[1] - prev.bbox[3]
            if gap > self.config.max_line_gap:
                return True

            # If left‑edge jumps significantly, likely a new block
            dx = abs(ch.bbox[0] - prev.bbox[0])
            if dx > self.config.max_indent_delta:
                return True

        return False

    # ------------------------------------------------------------------
    @staticmethod
    def _looks_like_numbered_note(text: str) -> bool:
        text = text.lstrip()
        # e.g. "1.", "12.", "3)"
        if len(text) >= 2 and text[0].isdigit() and text[1] in ".)":
            return True
        # e.g. "1 " at start of line
        if len(text) >= 2 and text[0].isdigit() and text[1] == " ":
            return True
        return False

    # ------------------------------------------------------------------
    @staticmethod
    def _looks_like_bullet(text: str) -> bool:
        text = text.lstrip()
        if not text:
            return False
        return text[0] in {"•", "-", "*"}


__all__ = ["SemanticGrouper", "SemanticGrouperConfig"]
