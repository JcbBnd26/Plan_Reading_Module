# column_detector.py
#
# Responsible for assigning a simple column index to each Chunk on a page.
# This version is tolerant to both `chunk.page` and `chunk.page_number`
# so we don't explode if older/newer code is mixed.

from typing import List, Optional
from .chunk import Chunk

# How close two left edges (x0) can be and still be considered the same column (in PDF units)
LEFT_TOLERANCE = 20.0

# Ignore tiny "clusters" of chunks that look like noise
MIN_CLUSTER_SIZE = 5

DEBUG = False


def _get_page(c: Chunk) -> Optional[int]:
    """
    Helper to read page number from a Chunk, tolerating both
    `page` and `page_number` attributes.
    """
    if hasattr(c, "page") and getattr(c, "page") is not None:
        return getattr(c, "page")
    if hasattr(c, "page_number") and getattr(c, "page_number") is not None:
        return getattr(c, "page_number")
    return None


class ColumnDetector:
    """
    Very simple column detector:

        1. Take all chunk left edges (bbox[0]).
        2. Cluster them left-to-right if they are within LEFT_TOLERANCE.
        3. Discard tiny clusters (if possible).
        4. Assign a 1-based column index for each cluster.

    This does *not* know anything about visual boxes; it just works from
    the text bounding boxes. Visual metadata is handled elsewhere
    (visual_chunker_bridge).
    """

    def assign_columns(self, chunks: List[Chunk], sheet_type: Optional[str] = None) -> List[Chunk]:
        """
        Assigns `chunk.column = 1,2,3,...` based on x-position.

        Parameters
        ----------
        chunks:
            All chunks for a single page.
        sheet_type:
            Currently unused, but kept for interface compatibility.

        Returns
        -------
        The same list of Chunk objects (mutated in-place).
        """
        if not chunks:
            return []

        # Collect (x0, index) for all chunks that have a bbox
        left_edges = []
        for idx, c in enumerate(chunks):
            bbox = getattr(c, "bbox", None)
            if not bbox or len(bbox) != 4:
                continue
            x0 = float(bbox[0])
            left_edges.append((x0, idx))

        if not left_edges:
            # Nothing to do
            if DEBUG:
                page = _get_page(chunks[0])
                print(f"    [ColumnDetector] page={page} - no bboxes, skipping.")
            return chunks

        # Sort by x0 so we can cluster left-to-right
        left_edges.sort(key=lambda t: t[0])

        clusters: List[List[int]] = []
        current_cluster: List[int] = []
        last_x: Optional[float] = None

        for x0, idx in left_edges:
            if last_x is None or abs(x0 - last_x) <= LEFT_TOLERANCE:
                current_cluster.append(idx)
            else:
                # Start a new cluster
                if current_cluster:
                    clusters.append(current_cluster)
                current_cluster = [idx]
            last_x = x0

        if current_cluster:
            clusters.append(current_cluster)

        # Prefer "big" clusters (real columns) but fall back if all are tiny
        big_clusters = [cl for cl in clusters if len(cl) >= MIN_CLUSTER_SIZE]
        if big_clusters:
            use_clusters = big_clusters
        else:
            use_clusters = clusters

        # Map each chunk index to a column index (1-based, left to right)
        index_to_column = {}
        for col_idx, cluster in enumerate(use_clusters, start=1):
            for idx in cluster:
                index_to_column[idx] = col_idx

        # Assign column number onto the chunk objects
        for idx, c in enumerate(chunks):
            col_idx = index_to_column.get(idx)
            if col_idx is not None:
                # Create/overwrite `column` attribute on the chunk
                setattr(c, "column", col_idx)

        if DEBUG:
            page = _get_page(chunks[0])
            print(
                f"    [ColumnDetector] page={page} "
                f"raw_clusters={len(clusters)} used_clusters={len(use_clusters)}"
            )

        return chunks
