"""
view_labeled_notes.py

Utility to inspect only the labeled notes from the labeled notes JSON.

Defaults:
- Input JSON: exports/all_pages_notes_labeled.json
- Shows notes that have:
    - a non-empty "label" field, OR
    - a non-empty "tags" dict
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Tuple

DEFAULT_LABELED_JSON = os.path.join("exports", "all_pages_notes_labeled.json")


# ---------------------------------------------------------------------------
# JSON loading
# ---------------------------------------------------------------------------

def load_notes_json(path: str) -> Tuple[Any, List[Dict[str, Any]]]:
    """Load the labeled notes JSON and return (root_object, notes_list)."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Notes JSON not found: {path}")

    print(f">>> Loading labeled notes JSON from: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        notes = data
        print(f">>> JSON is a list with {len(notes)} note item(s).")
        return data, notes

    if isinstance(data, dict):
        if "chunks" in data and isinstance(data["chunks"], list):
            notes = data["chunks"]
            print(f">>> JSON is a dict with 'chunks' list of {len(notes)} note item(s).")
            return data, notes

        # fallback: try a single obvious list
        for key, value in data.items():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                print(f">>> JSON dict: using list at key '{key}' with {len(value)} item(s).")
                return data, value

        raise RuntimeError(
            f"Could not find a list of notes in {path}. Keys: {list(data.keys())}"
        )

    raise RuntimeError(
        f"Unexpected JSON structure in {path}: top-level type {type(data)}"
    )


# ---------------------------------------------------------------------------
# Filtering and printing
# ---------------------------------------------------------------------------

def collect_labeled_notes(
    notes_list: List[Dict[str, Any]],
    min_label_length: int,
) -> List[Tuple[int, Dict[str, Any]]]:
    """
    Collect notes that have a label or tags.

    Returns:
        List of (index_1_based, note_dict)
    """
    labeled: List[Tuple[int, Dict[str, Any]]] = []

    for idx_1_based, note in enumerate(notes_list, start=1):
        label = (note.get("label") or "").strip()
        tags = note.get("tags") or {}

        has_label = len(label) >= min_label_length
        has_tags = isinstance(tags, dict) and len(tags) > 0

        if has_label or has_tags:
            labeled.append((idx_1_based, note))

    return labeled


def preview_text(note: Dict[str, Any], max_len: int = 120) -> str:
    """
    Build a short preview from the note text fields.
    """
    text = (
        note.get("text_preview")
        or note.get("text")
        or ""
    )
    text = str(text).replace("\n", " ").strip()
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def pretty_print_labeled_notes(
    labeled_notes: List[Tuple[int, Dict[str, Any]]],
    limit: int,
) -> None:
    """
    Print labeled notes in a compact readable format.
    """
    total_with_labels = len(labeled_notes)
    print(f">>> Labeled notes found: {total_with_labels}")

    if total_with_labels == 0:
        return

    if limit > 0:
        labeled_notes = labeled_notes[:limit]

    print(f">>> Showing first {len(labeled_notes)} labeled note(s):\n")

    for idx_display, (idx_1_based, note) in enumerate(labeled_notes, start=1):
        page = note.get("page")
        column = note.get("column") or note.get("col")
        visual_note_id = note.get("visual_note_id") or note.get("note_id")
        label = (note.get("label") or "").strip()
        tags = note.get("tags") or {}

        header_parts = [f"[{idx_display:03d}] idx={idx_1_based}"]
        if page is not None:
            header_parts.append(f"page={page}")
        if column:
            header_parts.append(f"col={column}")
        if visual_note_id:
            header_parts.append(f"vnote={visual_note_id}")

        header_line = " ".join(header_parts)
        print(header_line)

        if label:
            print(f"    label: {label}")

        if isinstance(tags, dict) and tags:
            tag_str = ", ".join(f"{k}={v}" for k, v in tags.items())
            print(f"    tags : {tag_str}")

        text_prev = preview_text(note)
        if text_prev:
            print(f"    text : {text_prev}")

        print()  # blank line between entries


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="View notes that have labels/tags in the labeled notes JSON."
    )
    parser.add_argument(
        "--json",
        default=DEFAULT_LABELED_JSON,
        help=f"Path to labeled notes JSON (default: {DEFAULT_LABELED_JSON})",
    )
    parser.add_argument(
        "--min-label-length",
        type=int,
        default=1,
        help="Minimum label length to count as labeled (default: 1).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum labeled notes to display (0 = no limit, default: 50).",
    )
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    try:
        root_obj, notes_list = load_notes_json(args.json)
        labeled = collect_labeled_notes(notes_list, args.min_label_length)
        pretty_print_labeled_notes(labeled, args.limit)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
