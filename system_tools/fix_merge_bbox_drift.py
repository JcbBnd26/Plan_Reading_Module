#!/usr/bin/env python3
"""
system_tools/fix_merge_bbox_drift.py

One-shot patcher to kill bbox drift in tools/merge_note_fragments.py

Fixes:
- _bbox() supports both:
    bbox: [x0,y0,x1,y1]
    bbox: {"x0":..,"y0":..,"x1":..,"y1":..}

Safety:
- Creates a timestamped .bak copy before modifying.
- Verifies patch applied by searching for a marker string.
"""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path


ROOT = Path.cwd()
TARGET = ROOT / "tools" / "merge_note_fragments.py"


PATCH_MARKER = "BBOX_DRIFT_PATCH_V1"


def sha256_short(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def main() -> int:
    if not TARGET.exists():
        print(f"[FAIL] Missing: {TARGET}")
        return 1

    before_hash = sha256_short(TARGET)
    before_text = TARGET.read_text(encoding="utf-8", errors="replace")

    if PATCH_MARKER in before_text:
        print(f"[OK] Patch already present in {TARGET}")
        print(f"[INFO] sha={before_hash}")
        return 0

    # Find the existing def _bbox(...) block (simple, robust heuristic)
    # We replace ONLY the function body, not the whole file.
    m = re.search(
        r"(?ms)^def\s+_bbox\s*\(.*?\)\s*:\s*\n(    .*\n)+",
        before_text,
    )
    if not m:
        print("[FAIL] Could not locate def _bbox(...) block to patch.")
        print(f"[INFO] File: {TARGET}")
        return 1

    old_block = m.group(0)

    new_block = f'''def _bbox(ch: dict) -> tuple[float, float, float, float]:
    """
    {PATCH_MARKER}
    Accept bbox in either format:
      - list/tuple: [x0, y0, x1, y1]
      - dict: {{"x0":..,"y0":..,"x1":..,"y1":..}}
    Returns a 4-float tuple.
    """
    b = ch.get("bbox")
    if not b:
        return None  # caller should handle

    # Dict bbox
    if isinstance(b, dict):
        try:
            return (float(b["x0"]), float(b["y0"]), float(b["x1"]), float(b["y1"]))
        except Exception:
            return None

    # List/tuple bbox
    if isinstance(b, (list, tuple)) and len(b) >= 4:
        try:
            return (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
        except Exception:
            return None

    return None
'''

    after_text = before_text.replace(old_block, new_block, 1)

    # Backup
    stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    backup = TARGET.with_suffix(f".py.bak_{stamp}")
    backup.write_text(before_text, encoding="utf-8")
    TARGET.write_text(after_text, encoding="utf-8")

    after_hash = sha256_short(TARGET)
    print("[OK] Patched bbox drift in merge_note_fragments.py")
    print(f"[INFO] File: {TARGET}")
    print(f"[INFO] Backup: {backup}")
    print(f"[INFO] sha before: {before_hash}")
    print(f"[INFO] sha after : {after_hash}")

    # Verify marker exists now
    verify = TARGET.read_text(encoding="utf-8", errors="replace")
    if PATCH_MARKER not in verify:
        print("[FAIL] Patch marker not found after write (unexpected).")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
