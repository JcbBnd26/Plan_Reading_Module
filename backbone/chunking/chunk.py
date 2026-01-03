"""Core chunk data structures used by the entire pipeline.

Defines:
    - BBox: type alias for (x0, y0, x1, y1)
    - Chunk: atomic text element extracted from a PDF page
    - MergedChunk: logical group of one or more Chunk objects

All downstream code (chunker, semantic_grouper, visual bridge, etc.)
must treat both Chunk and MergedChunk in the same way:

    * .content (str)   – text
    * .bbox    (BBox)  – bounding box in page coordinates
    * .page    (int)   – 1‑based page index
    * .metadata (dict) – arbitrary key/value metadata
    * .children (list[Chunk]) – sub‑chunks (empty for plain Chunk)

This file is the *single source of truth* for these classes.
No other module should redefine Chunk or MergedChunk.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------
# Type alias for bounding boxes
# ---------------------------------------------------------------------
BBox = Tuple[float, float, float, float]


# =====================================================================
# Base Chunk
# =====================================================================
@dataclass
class Chunk:
    """Atomic text element extracted from a PDF page.

    Fields
    ------
    id:
        UUID string uniquely identifying this chunk.
    content:
        Extracted text content.
    type:
        Category label for higher‑level processing
        (e.g., "text_line", "note", "header").
    bbox:
        Bounding box in PDF coordinates: (x0, y0, x1, y1).
    page:
        1‑based page number.
    source_file:
        Optional label/path for the originating PDF.
    metadata:
        Free‑form dictionary for any extra information
        (sheet type, visual tags, embeddings, etc.).
    children:
        Optional nested chunks (used by grouping / merging).
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    type: str = "text_line"
    bbox: Optional[BBox] = None
    page: Optional[int] = None
    source_file: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)
    children: List["Chunk"] = field(default_factory=list)

    def add_child(self, chunk: "Chunk") -> None:
        """Attach a child chunk (grouping / hierarchy)."""
        self.children.append(chunk)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Chunk {self.type} {self.id[:8]} pg={self.page}>"


# =====================================================================
# Merged Chunk
# =====================================================================
class MergedChunk(Chunk):
    """Logical group of one or more Chunk objects.

    This class behaves like a normal :class:`Chunk` but represents
    a higher‑level unit such as a full note, paragraph, or heading
    + body block.

    The constructor performs the following:

        * content   – concatenation of all child.contents separated by "\n"
        * bbox      – geometric union of all child.bbox values
        * metadata  – shallow merge of child.metadata (later wins)
        * page      – taken from the first child
        * children  – the original list of Chunk objects
    """

    def __init__(
        self,
        chunks: List[Chunk],
        merge_type: str = "merged",
        id: Optional[str] = None,
    ) -> None:
        if not chunks:
            raise ValueError("MergedChunk requires at least one child Chunk")

        # Canonical values from first child
        page = chunks[0].page
        source_file = chunks[0].source_file

        # Merge text
        content = "\n".join((c.content or "") for c in chunks)

        # Merge bounding boxes
        bbox = self._union_bbox([c.bbox for c in chunks])

        # Merge metadata (later items override)
        merged_meta: Dict[str, Any] = {}
        for c in chunks:
            merged_meta.update(c.metadata)

        super().__init__(
            id=id or str(uuid.uuid4()),
            content=content,
            type=merge_type,
            bbox=bbox,
            page=page,
            source_file=source_file,
            metadata=merged_meta,
            children=list(chunks),
        )

        # Optional alias used by some legacy code
        self.chunks = self.children

    # ------------------------------------------------------------------
    @staticmethod
    def _union_bbox(bboxes: List[Optional[BBox]]) -> Optional[BBox]:
        """Return the minimal box that contains all non‑None child bboxes."""
        xs0: List[float] = []
        ys0: List[float] = []
        xs1: List[float] = []
        ys1: List[float] = []

        for b in bboxes:
            if not b:
                continue
            x0, y0, x1, y1 = b
            xs0.append(float(x0))
            ys0.append(float(y0))
            xs1.append(float(x1))
            ys1.append(float(y1))

        if not xs0:
            return None

        return (min(xs0), min(ys0), max(xs1), max(ys1))

    # ------------------------------------------------------------------
    @classmethod
    def from_chunks(
        cls,
        chunks: List[Chunk],
        merge_type: str = "merged",
        id: Optional[str] = None,
    ) -> "MergedChunk":
        """Helper constructor used by grouping / semantic code."""
        return cls(chunks=chunks, merge_type=merge_type, id=id)

    # ------------------------------------------------------------------
    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<MergedChunk {self.type} {self.id[:8]} "
            f"pg={self.page} children={len(self.children)}>"
        )


__all__ = ["Chunk", "MergedChunk", "BBox"]
