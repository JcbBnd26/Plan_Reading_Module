"""
view_notes_json.py

Utility to inspect exported note chunks with simple filters.
Supports:
- top-level list JSON
- top-level dict JSON with a list field (e.g. "chunks" or "notes")
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


def shorten(text: str, max_len: int = 80) -> str:
    """Collapse whitespace and truncate long text for printing."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_len:
        return collapsed
    return collapsed[: max_len - 3] + "..."


def load_notes(path: Path) -> Tuple[List[Dict[str, Any]], str]:
    """
    Load notes from JSON.

    Returns:
        (notes_list, info_string)
    """
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Case 1: top-level list of note dicts
    if isinstance(data, list):
        return data, "top-level list"

    # Case 2: top-level dict with a list field (chunks/notes/items/data)
    if isinstance(data, dict):
        for key in ["chunks", "notes", "items", "data"]:
            value = data.get(key)
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value, f"dict with '{key}' list"

        # Fallback: empty list if we can't find a list field
        return [], f"dict with no usable list field (keys: {list(data.keys())})"

    # Unknown structure
    return [], f"unsupported JSON type: {type(data)}"


def matches_filters(item: Dict[str, Any], args: argparse.Namespace) -> bool:
    """Return True if this item passes all active CLI filters."""
    # Page filter
    if args.page is not None:
        if item.get("page") != args.page:
            return False

    # Column filter
    if args.column is not None:
        col = item.get("column") or item.get("col") or ""
        if str(col) != args.column:
            return False

    # Note-id / visual-note-id filter
    if args.note_id is not None:
        nid = (
            item.get("visual_note_id")
            or item.get("note_id")
            or item.get("id")
            or ""
        )
        if str(nid) != args.note_id:
            return False

    # Substring filter on text
    if args.contains is not None:
        text = (
            item.get("text")
            or item.get("raw_text")
            or item.get("content")
            or ""
        )
        if args.contains.lower() not in str(text).lower():
            return False

    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect exported note chunks with simple filters."
    )
    parser.add_argument(
        "--file",
        required=True,
        dest="file",
        help="Path to notes JSON file (e.g. exports\\all_pages_notes_sheetwide.json)",
    )
    parser.add_argument(
        "--page",
        type=int,
        default=None,
        help="Filter by page number (e.g. 3)",
    )
    parser.add_argument(
        "--column",
        type=str,
        default=None,
        help="Filter by column id (e.g. column_1, column_3)",
    )
    parser.add_argument(
        "--note-id",
        type=str,
        default=None,
        help="Filter by visual note id (e.g. note_1, sheet_info_1)",
    )
    parser.add_argument(
        "--contains",
        type=str,
        default=None,
        help="Filter notes whose text contains this substring (case-insensitive).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=40,
        help="Maximum number of notes to print (default: 40).",
    )

    args = parser.parse_args()
    json_path = Path(args.file)

    if not json_path.exists():
        print(f"ERROR: JSON file not found: {json_path}")
        return 1

    notes, info = load_notes(json_path)
    print(
        f">>> Loaded {len(notes)} note item(s) from: {json_path}\n"
        f">>> JSON structure: {info}"
    )

    matched: List[Tuple[int, Dict[str, Any]]] = []
    for idx, item in enumerate(notes):
        if not matches_filters(item, args):
            continue
        matched.append((idx, item))
        if args.limit is not None and len(matched) >= args.limit:
            break

    print(f">>> {len(matched)} note item(s) match filters.")

    for disp_idx, (orig_idx, item) in enumerate(matched, start=1):
        page = item.get("page")
        col = item.get("column") or item.get("col")
        nid = (
            item.get("visual_note_id")
            or item.get("note_id")
            or item.get("id")
        )
        text = (
            item.get("text")
            or item.get("raw_text")
            or item.get("content")
            or ""
        )

        print(
            f"[{disp_idx:03}] idx={orig_idx + 1} page={page} "
            f"col={col} note_id={nid}"
        )
        print(f"      text: {shorten(str(text))}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
