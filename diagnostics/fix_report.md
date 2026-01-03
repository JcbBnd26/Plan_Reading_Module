# AutoFix Report

## C:\Projects\backbone_skeleton\backbone\chunking\__init__.py

- REWRITE: `from .chunk import Chunk, MergedChunk, BBox` -> `from backbone.chunking.chunk import Chunk, MergedChunk, BBox`
- REWRITE: `from .chunk_utils import merge_chunks` -> `from backbone.chunking.chunk_utils import merge_chunks`

### Diff:
```diff
--- C:\Projects\backbone_skeleton\backbone\chunking\__init__.py
+++ C:\Projects\backbone_skeleton\backbone\chunking\__init__.py
@@ -12,8 +12,8 @@
 
 from __future__ import annotations
 
-from .chunk import Chunk, MergedChunk, BBox
-from .chunk_utils import merge_chunks
+from backbone.chunking.chunk import Chunk, MergedChunk, BBox
+from backbone.chunking.chunk_utils import merge_chunks
 from .chunker import Chunker, ChunkerConfig
 
 __all__ = [
```