# visual_alignment.py
"""
Visual Alignment Module
-----------------------
Purpose:
    Align raw annotation bounding boxes (from JSON) to actual PDF pixel
    coordinates to ensure stable overlap checks, note pairing, and
    column-region relationships.

Method:
    - Rounds coordinates to nearest integer
    - Clamps bbox edges within PDF image boundaries
    - Removes any boxes smaller than 2–3 px (noise)
"""

from typing import Dict, List, Tuple

class VisualAlignment:
    def __init__(self, page_width: int, page_height: int):
        self.w = page_width
        self.h = page_height

    # -------------------------------------------------------------
    # PUBLIC: Align all regions for a page
    # -------------------------------------------------------------
    def align_page(self, page_regions: Dict[str, List[Dict]]) -> Dict[str, List[Dict]]:
        aligned = {}

        for class_name, items in page_regions.items():
            aligned[class_name] = []
            for region in items:
                bbox = region.get("bbox")
                if not bbox:
                    continue

                x0, y0, x1, y1 = bbox
                ax0, ay0, ax1, ay1 = self._align_bbox(x0, y0, x1, y1)

                # Filter extremely small boxes
                if (ax1 - ax0) < 2 or (ay1 - ay0) < 2:
                    continue

                new_region = dict(region)
                new_region["bbox"] = (ax0, ay0, ax1, ay1)
                aligned[class_name].append(new_region)

        return aligned

    # -------------------------------------------------------------
    # INTERNAL HELPERS
    # -------------------------------------------------------------
    def _align_bbox(self, x0, y0, x1, y1) -> Tuple[int, int, int, int]:
        # Round to nearest integer
        x0 = int(round(x0))
        y0 = int(round(y0))
        x1 = int(round(x1))
        y1 = int(round(y1))

        # Clamp to image boundaries
        x0 = max(0, min(x0, self.w - 1))
        x1 = max(0, min(x1, self.w - 1))
        y0 = max(0, min(y0, self.h - 1))
        y1 = max(0, min(y1, self.h - 1))

        # Normalize order
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0

        return x0, y0, x1, y1
