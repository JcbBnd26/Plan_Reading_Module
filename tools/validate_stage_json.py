#!/usr/bin/env python3
"""
tools/validate_stage_json.py

Fast, strict-ish JSON validation for pipeline stage outputs.

This is NOT "business logic" validation (no geometry heuristics here).
It exists to enforce the contract:

  "If a stage claims success, its output file must exist and be minimally sane."

Validated invariants
--------------------
- File exists and parses as JSON.
- Root is either:
    - {"chunks":[...]} (preferred), or
    - [...] (legacy list root; allowed but warned unless --require-dict-root)
- Each chunk on the target page (or all pages if --page not provided):
    - is a dict
    - has an id (string-ish)
    - has a type (string-ish)
    - has a parseable bbox
    - bbox schema is dict (optional: --require-bbox-dict)
    - bbox has positive width/height

Exit code
---------
- 0 on success
- 2 on validation failure (non-exceptional)
- 1 for unexpected crashes
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import bbox_utils


@dataclass
class ValidationStats:
    total_chunks: int = 0
    validated_chunks: int = 0
    bad_chunks: int = 0
    missing_bbox: int = 0
    bad_bbox: int = 0
    non_dict_bbox: int = 0


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _get_chunks(root: Any) -> List[Dict[str, Any]]:
    if isinstance(root, dict) and isinstance(root.get("chunks"), list):
        return root["chunks"]
    if isinstance(root, list):
        # legacy shape: list of chunks
        return [c for c in root if isinstance(c, dict)]
    raise ValueError("Unsupported JSON root. Expected {'chunks':[...]} or a list root.")


def validate_stage(
    path: Path,
    *,
    page: Optional[int] = None,
    require_bbox_dict: bool = True,
    require_dict_root: bool = False,
) -> ValidationStats:
    """
    Validate a stage file. Raises ValueError on failure.
    Returns stats on success.
    """
    if not path.exists():
        raise ValueError(f"Missing output JSON: {path}")

    root = _load_json(path)

    if require_dict_root and not isinstance(root, dict):
        raise ValueError(f"Stage JSON root must be a dict with 'chunks', got: {type(root).__name__}")

    chunks = _get_chunks(root)
    st = ValidationStats(total_chunks=len(chunks))

    page_str = str(page) if page is not None else None

    for ch in chunks:
        if page_str is not None and str(ch.get("page")) != page_str:
            continue

        st.validated_chunks += 1

        # Basic keys
        if "id" not in ch:
            st.bad_chunks += 1
            raise ValueError(f"Chunk missing 'id' in {path}")

        if "type" not in ch:
            st.bad_chunks += 1
            raise ValueError(f"Chunk missing 'type' (id={ch.get('id')}) in {path}")

        # BBox presence + shape
        box = bbox_utils.extract_bbox(ch)
        if box is None:
            st.missing_bbox += 1
            raise ValueError(f"Chunk missing/invalid bbox (id={ch.get('id')}, type={ch.get('type')}) in {path}")

        if require_bbox_dict:
            b = ch.get("bbox")
            if not isinstance(b, dict):
                st.non_dict_bbox += 1
                raise ValueError(
                    f"Non-dict bbox schema found (id={ch.get('id')}, type={ch.get('type')}): {type(b).__name__}. "
                    f"Expected dict bbox in {path}"
                )

        # Geometry sanity
        if box.w <= 0.0 or box.h <= 0.0:
            st.bad_bbox += 1
            raise ValueError(
                f"Degenerate bbox (id={ch.get('id')}, type={ch.get('type')}): {box.as_tuple()} in {path}"
            )

    return st


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Validate pipeline stage JSON output.")
    ap.add_argument("--input", required=True, help="Stage JSON path")
    ap.add_argument("--page", type=int, default=None, help="Validate only this page (1-based)")
    ap.add_argument("--require-bbox-dict", action="store_true", default=False,
                    help="Fail if any validated chunk uses list bbox")
    ap.add_argument("--require-dict-root", action="store_true", default=False,
                    help="Fail if JSON root is not a dict with 'chunks'")
    return ap.parse_args()


def main() -> int:
    a = parse_args()
    try:
        stats = validate_stage(
            Path(a.input),
            page=a.page,
            require_bbox_dict=bool(a.require_bbox_dict),
            require_dict_root=bool(a.require_dict_root),
        )
        print(
            "[OK] Valid stage JSON:",
            a.input,
            f"(validated_chunks={stats.validated_chunks}, total_chunks={stats.total_chunks})",
        )
        return 0
    except ValueError as e:
        print("[FAIL]", str(e))
        return 2
    except Exception as e:
        print("[CRASH]", repr(e))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
