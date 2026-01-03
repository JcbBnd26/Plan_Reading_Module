"""Small utilities for working with chunks.

Only one public helper is provided:

    merge_chunks(chunks, merge_type="merged") -> MergedChunk

This is a thin convenience wrapper around :class:`MergedChunk`.
"""

from __future__ import annotations

from typing import List

from backbone.chunking.chunk import MergedChunk


def merge_chunks(chunks: List[Chunk], merge_type: str = "merged") -> MergedChunk:
    """Merge a list of Chunk objects into a single MergedChunk.

    Parameters
    ----------
    chunks:
        One or more Chunk objects. If the list is empty, a ValueError
        is raised (to avoid creating meaningless empty groups).
    merge_type:
        Label stored in the resulting MergedChunk.type field.

    Returns
    -------
    MergedChunk
        New grouped chunk representing the combined content/geometry.
    """
    if not chunks:
        raise ValueError("merge_chunks() requires at least one Chunk")

    return MergedChunk.from_chunks(chunks=chunks, merge_type=merge_type)