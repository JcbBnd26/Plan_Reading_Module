#!/usr/bin/env python
"""
debug_dump_page_chunks.py

Print a simple text dump of all chunks on a given page:
- global index
- page
- column index
- y0/y1
- bullet-guess flag
- truncated text

Use this to inspect tricky notes (e.g. 9, 10, 14) and see how the OCR
actually stored them.
"""

import argparse
import json
from typing import Any, Dict, List, Optional

from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Debug-dump chunks for a page.")
    p.add_argument("--json", required=True, help="Notes JSON file.")
    p.add_argument("--page", type=int, required=True, help="1-based page number.")
    p.add_argument(
        "--limit",
        type=int,
        default=9999,
        help="Max chunks to print (for safety; default: all).",
    )
    return p.parse_args()


def looks_like_bullet_start(text: str) -> bool:
    text = (text or "").lstrip()
    if not text:
        return False
    # Very simple bullet guess here; full pattern lives in merge script.
    first = text.split()[0]
    # e.g. "10.", "14.", "7."
    if first[:-1].isdigit() and first[-1] in (".", ")", "]"):
        return True
    return False


def get_column_index(ch: Dict[str, Any]) -> int:
    meta = ch.get("metadata") or {}
    for container in (meta, ch):
        if "visual_column_index" in container:
            try:
                return int(container["visual_column_index"])
            except Exception:
                pass
    return 0


def extract_bbox(ch: Dict[str, Any]):
    for key in ("x0", "y0", "x1", "y1"):
        if key not in ch:
            return None
    try:
        return float(ch["x0"]), float(ch["y0"]), float(ch["x1"]), float(ch["y1"])
    except Exception:
        return None


def get_text(ch: Dict[str, Any]) -> str:
    if isinstance(ch.get("content"), str):
        return ch["content"]
    if isinstance(ch.get("text"), str):
        return ch["text"]
    return ""


def load_chunks(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and isinstance(data.get("chunks"), list):
        return data["chunks"]
    if isinstance(data, list):
        return data
    raise ValueError("Unsupported JSON structure")


def main() -> None:
    args = parse_args()
    chunks = load_chunks(args.json)

    # Filter by page
    page_chunks: List[Dict[str, Any]] = []
    for idx, ch in enumerate(chunks):
        page_no = ch.get("page") or ch.get("page_number") or ch.get("page_index")
        try:
            page_no = int(page_no)
        except Exception:
            continue
        if page_no == args.page:
            ch = dict(ch)
            ch["_global_index"] = idx
            page_chunks.append(ch)

    # Sort by y0 then index
    def sort_key(ch: Dict[str, Any]):
        bbox = extract_bbox(ch)
        y0 = bbox[1] if bbox is not None else 0.0
        return (y0, ch["_global_index"])

    page_chunks.sort(key=sort_key)

    print(f"# Debug dump for page {args.page} from {args.json}")
    print(f"# Total chunks on this page: {len(page_chunks)}\n")

    for i, ch in enumerate(page_chunks[: args.limit]):
        idx = ch["_global_index"]
        col = get_column_index(ch)
        bbox = extract_bbox(ch)
        y0 = bbox[1] if bbox is not None else -1
        y1 = bbox[3] if bbox is not None else -1
        text = get_text(ch).replace("\n", " ")
        text_short = (text[:90] + "…") if len(text) > 90 else text
        bullet = "B" if looks_like_bullet_start(text) else "-"
        print(f"{i:03d}  idx={idx:4d}  col={col:2d}  y0={y0:7.1f}  y1={y1:7.1f}  {bullet}  {text_short}")


if __name__ == "__main__":
    main()
