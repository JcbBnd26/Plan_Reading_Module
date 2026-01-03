"""
apply_note_labels.py

Applies human-provided labels from a CSV table onto the notes JSON.

Design:
- Notes JSON: exports/all_pages_notes_sheetwide.json
  * Top-level can be:
      - a list of note dicts, OR
      - a dict with a 'chunks' list of note dicts
- Labels CSV: exports/notes_table.csv
  * Must contain:
      - global_index (1-based row index)
      - label (optional main label)
  * May contain additional tag columns; any non-empty values in those
    columns become tags on the note.
- Output JSON: exports/all_pages_notes_labeled.json
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from typing import Any, Dict, List, Tuple

DEFAULT_NOTES_JSON = os.path.join("exports", "all_pages_notes_sheetwide.json")
DEFAULT_LABELS_CSV = os.path.join("exports", "notes_table.csv")
DEFAULT_OUTPUT_JSON = os.path.join("exports", "all_pages_notes_labeled.json")


# ---------------------------------------------------------------------------
# JSON loading
# ---------------------------------------------------------------------------

def load_notes_json(path: str) -> Tuple[Any, List[Dict[str, Any]]]:
    """Load the notes JSON and return (root_object, notes_list)."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Notes JSON not found: {path}")

    print(f">>> Loading notes JSON from: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        notes = data
        print(f">>> Notes JSON is a list with {len(notes)} item(s).")
        return data, notes

    if isinstance(data, dict):
        if "chunks" in data and isinstance(data["chunks"], list):
            notes = data["chunks"]
            print(f">>> Detected top-level dict; using 'chunks' list with {len(notes)} note item(s).")
            return data, notes

        raise RuntimeError(
            f"Expected a list of notes or a dict with 'chunks' list in {path}, "
            f"but got dict with keys: {list(data.keys())}"
        )

    raise RuntimeError(
        f"Unexpected JSON structure in {path}: top-level type {type(data)}"
    )


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------

def load_labels_table(path: str) -> Dict[int, Dict[str, Any]]:
    """
    Load labels from CSV keyed by global_index (1-based).

    Returns:
        { global_index: {"label": <str>, "tags": {tag_col: value, ...}} }
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Labels CSV not found: {path}")

    print(f">>> Loading labels CSV from: {path}")
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []

        if "global_index" not in fieldnames:
            raise RuntimeError(
                f"CSV {path} is missing required 'global_index' column. "
                f"Columns found: {fieldnames}"
            )

        if "label" not in fieldnames:
            raise RuntimeError(
                f"CSV {path} is missing required 'label' column. "
                f"Columns found: {fieldnames}"
            )

        # Columns that are metadata, not tags
        meta_cols = {
            "global_index",
            "page",
            "column",
            "visual_note_id",
            "visual_region",
            "is_repeated",
            "repeated_group_id",
            "repeated_occurrences",
            "text_preview",
            "text",
            "label",
        }

        # Anything else is treated as a tag column
        tag_columns = [c for c in fieldnames if c not in meta_cols]

        label_map: Dict[int, Dict[str, Any]] = {}
        total_rows = 0
        labeled_rows = 0

        for row in reader:
            total_rows += 1

            raw_idx = (row.get("global_index") or "").strip()
            if not raw_idx:
                continue

            try:
                idx = int(raw_idx)
            except ValueError:
                # Skip malformed index
                continue

            label = (row.get("label") or "").strip()
            tags: Dict[str, Any] = {}

            # Collect non-empty tag columns
            for col in tag_columns:
                val = (row.get(col) or "").strip()
                if val:
                    tags[col] = val

            # Skip rows with neither label nor tags
            if not label and not tags:
                continue

            labeled_rows += 1
            label_map[idx] = {"label": label, "tags": tags}

        print(
            f">>> Loaded {total_rows} CSV row(s) from {path}; "
            f"{labeled_rows} row(s) have labels and/or tags."
        )

        return label_map


# ---------------------------------------------------------------------------
# Apply labels
# ---------------------------------------------------------------------------

def apply_labels_to_notes(
    root_obj: Any,
    notes_list: List[Dict[str, Any]],
    label_map: Dict[int, Dict[str, Any]],
) -> Tuple[Any, int]:
    """
    Apply labels from label_map to notes_list.

    label_map is keyed by global_index (1-based index matching CSV).
    """
    if not label_map:
        print(">>> No labels to apply (label_map is empty).")
        return root_obj, 0

    labeled_count = 0
    total = len(notes_list)

    print(f">>> Applying labels to notes (by global_index 1..{total})...")

    for idx_1_based, note in enumerate(notes_list, start=1):
        info = label_map.get(idx_1_based)
        if not info:
            continue

        label = info.get("label", "")
        tags = info.get("tags", {}) or {}

        if label:
            note["label"] = label

        if tags:
            existing_tags = note.get("tags")
            if isinstance(existing_tags, dict):
                merged = {**existing_tags, **tags}
            else:
                merged = tags
            note["tags"] = merged

        labeled_count += 1

    print(
        f">>> Labeled {labeled_count} out of {total} note(s) "
        f"({labeled_count}/{total})."
    )
    return root_obj, labeled_count


# ---------------------------------------------------------------------------
# Main CLI
# ---------------------------------------------------------------------------

def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply human labels from CSV to notes JSON using global_index."
    )
    parser.add_argument(
        "--notes-json",
        default=DEFAULT_NOTES_JSON,
        help=f"Input notes JSON path (default: {DEFAULT_NOTES_JSON})",
    )
    parser.add_argument(
        "--labels-csv",
        default=DEFAULT_LABELS_CSV,
        help=f"Labels CSV path (default: {DEFAULT_LABELS_CSV})",
    )
    parser.add_argument(
        "--out-json",
        default=DEFAULT_OUTPUT_JSON,
        help=f"Output labeled JSON path (default: {DEFAULT_OUTPUT_JSON})",
    )
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    try:
        root_obj, notes_list = load_notes_json(args.notes_json)
        label_map = load_labels_table(args.labels_csv)

        if not label_map:
            print(">>> No labels found in CSV (all label/tag cells empty?). Nothing to apply.")
            return 0

        root_obj, labeled_count = apply_labels_to_notes(root_obj, notes_list, label_map)

        # Ensure directories exist
        out_dir = os.path.dirname(args.out_json)
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)

        with open(args.out_json, "w", encoding="utf-8") as f:
            json.dump(root_obj, f, indent=2, ensure_ascii=False)

        print(f">>> Labeled notes JSON written to: {args.out_json}")
        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
