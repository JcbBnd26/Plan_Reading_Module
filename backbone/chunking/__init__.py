"""Chunking package: core data structures + PDF text pipeline.

This package exposes the primary public API for the text chunking layer:

    - Chunk / MergedChunk / BBox
    - merge_chunks() helper
    - Chunker / ChunkerConfig for running the pipeline

Everything outside the package should import from here rather than
reaching into individual modules.
"""

from __future__ import annotations

from backbone.chunking.chunk import Chunk, MergedChunk, BBox
from backbone.chunking.chunk_utils import merge_chunks
from .chunker import Chunker, ChunkerConfig

__all__ = [
    "Chunk",
    "MergedChunk",
    "BBox",
    "merge_chunks",
    "Chunker",
    "ChunkerConfig",
]
