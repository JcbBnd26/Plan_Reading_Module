from typing import List
from backbone.chunking.chunk import Chunk

class ChunkTagger:
    def tag(self, chunks: List[Chunk]) -> List[Chunk]:
        for c in chunks:
            if "note" in c.content.lower():
                c.metadata["category"] = "general_notes"
        return chunks