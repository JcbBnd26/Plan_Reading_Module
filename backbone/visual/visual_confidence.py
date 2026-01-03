"""
visual_confidence.py
---------------------

Purpose:
    Compute confidence scores for VISUAL note regions and
    fused TEXT+VISUAL note groups.

This module is called from:
    - auto_box_detector.py
    - visual_pipeline_integrator.py
    - semantic_grouper.py (after grouping)

Scoring Model:
    final_score = weighted sum of:

        1. Color match score
        2. Text presence score
        3. Bullet pattern score
        4. Indentation / alignment score
        5. Bounding box ratio score
"""

from typing import Dict, Any, Optional
import math

# ---------------------------------------------------------------------------
# Helper scoring functions
# ---------------------------------------------------------------------------

def score_color_match(hex_color: str, expected_hex: str) -> float:
    """Return 1.0 if exact match else 0.0 (simple for now)."""
    if not hex_color or not expected_hex:
        return 0.0
    return 1.0 if hex_color.lower() == expected_hex.lower() else 0.0


def score_text_presence(text: Optional[str]) -> float:
    """If text exists, return 1.0, else 0."""
    if text and text.strip():
        return 1.0
    return 0.0


def score_bullet_pattern(text: Optional[str]) -> float:
    """Return 1.0 if text starts with a bullet pattern."""
    if not text:
        return 0.0

    bullets = (
        "1.","2.","3.","4.","5.","6.","7.","8.","9.","10.",
        "(1)","(2)","(3)","(4)","(5)","(6)","(7)",
        "A.","B.","C.","D.","E.","F.","G."
    )

    t = text.strip()
    for b in bullets:
        if t.startswith(b):
            return 1.0
    return 0.0


def score_left_indent(bbox) -> float:
    """
    Crude indentation score.
    Lower x0 indicates stronger left alignment typical of bullets.
    """
    if not bbox:
        return 0.0

    x0, y0, x1, y1 = bbox

    # Lower x0 = stronger indentation=line start
    # Normalize to Example range (0–500 px)
    norm = max(0.0, min(1.0, 1 - (x0 / 500)))
    return norm


def score_bbox_ratio(bbox) -> float:
    """
    Score based on how note-like the shape is.
    Typical notes: wider than tall.
    """
    if not bbox:
        return 0.0

    x0, y0, x1, y1 = bbox
    w = x1 - x0
    h = y1 - y0

    if h <= 0 or w <= 0:
        return 0.0

    ratio = w / h

    # normal note ratio 2.0–6.0 range
    if ratio < 1:
        return 0.1
    if ratio > 8:
        return 0.3
    return max(0.0, min(1.0, (ratio - 1) / 5))


# ---------------------------------------------------------------------------
# Combined scoring API
# ---------------------------------------------------------------------------

def compute_visual_confidence(region: Dict[str, Any], rule_color_hex: str) -> float:
    """
    Compute confidence for a VISUAL bounding box region (from auto_box_detector).

    Expected region fields:
        - color_hex
        - bbox
        - extracted_text (if available)
    """
    color_score = score_color_match(region.get("color_hex"), rule_color_hex)
    text_score  = score_text_presence(region.get("extracted_text"))
    bullet      = score_bullet_pattern(region.get("extracted_text"))
    indent      = score_left_indent(region.get("bbox"))
    ratio       = score_bbox_ratio(region.get("bbox"))

    # Weighted model (initial prototype)
    final = (
        color_score * 0.40 +
        text_score  * 0.20 +
        bullet      * 0.15 +
        indent      * 0.10 +
        ratio       * 0.15
    )

    return round(final, 4)


def compute_fused_confidence(fused_note: Dict[str, Any]) -> float:
    """
    Compute confidence for the FINAL merged notes inside semantic_grouper.

    Expected fused_note fields:
        - text
        - bbox
        - visual_confidence (avg of children)
        - visual_ids list
    """

    text_score = score_text_presence(fused_note.get("text"))
    bullet     = score_bullet_pattern(fused_note.get("text"))
    indent     = score_left_indent(fused_note.get("bbox"))
    ratio      = score_bbox_ratio(fused_note.get("bbox"))
    visual_avg = fused_note.get("visual_confidence", 0.0)

    final = (
        visual_avg * 0.50 +
        text_score * 0.20 +
        bullet     * 0.10 +
        indent     * 0.10 +
        ratio      * 0.10
    )

    return round(final, 4)

