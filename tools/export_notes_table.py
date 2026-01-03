#!/usr/bin/env python
"""
Export all sheetwide notes into a CSV table for inspection/tagging.

Input:
    exports/all_pages_notes_sheetwide.json

Output:
    exports/notes_table.csv

Each row is a single note instance with:
- global_index       : 1-based index of the row
- page               : page number (if available)
- column             : column / column_id (if available)
- visual_note_id     : visual note id (if available)
- visual_region      : visual region (if available)
- is_repeated        : "yes" if this text appears >= MIN_OCCURRENCES times
- repeated_group_id  : group id for repeated text (e.g. RN1, RN2, ...)
- repeated_occurrences : how many times that text occurs in the whole set
- text_preview       : truncated preview of the note text
- text               : full note text

This is meant to be opened in Excel / a viewer so you can sort/filter/tag.
"""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List


# ----------------- Configuration defaults ----------------- #

DEFAULT_MIN_OCCURRENCES = 2
DEFAULT_MIN_CONTENT_LENGTH = 10

DEFAULT_EXPORT_JSON = Path("exports") / "all_pages_notes_sheetwide.json"
DEFAULT_OUTPUT_CSV = Path("exports") / "notes_table.csv"


# ----------------- Helpers ----------------- #

def project_root() -> Path:
    r"""
    Assume this script lives in `tools/` and the project root is its parent.
    Example:
        C:\\Projects\\backbone_skeleton\\tools\\export_notes_table.py
    """
    return Path(__file__).resolve().parent.parent


def first(d: Dict[str, Any], keys: List[str], default: Any = None) -> Any:
    """
    Return the first existing key in `d` from `keys`, or `default` if none exist.
    This makes the script tolerant to slightly different JSON field names.
    """
    for k in keys:
        if k in d:
            return d[k]
    return default


def load_notes(path: Path) -> List[Dict[str, Any]]:
    """
    Load notes from JSON, handling common layout patterns.

    Expected patterns:
        - A top-level list: [ {...}, {...}, ... ]
        - A dict with "notes": {"notes": [ {...}, ... ]}
        - A dict with exactly one list-of-dicts value
    """
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        if "notes" in data and isinstance(data["notes"], list):
            return data["notes"]

        # Fallback: first list-like value that looks like notes
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v

    raise ValueError(f"Unsupported JSON structure in {path}")


def normalize_text(text: str) -> str:
    """
    Normalize note text for grouping:
    - strip leading/trailing whitespace
    - collapse internal whitespace to single spaces
    """
    return " ".join(text.strip().split())


def text_preview(text: str, max_len: int = 120) -> str:
    """
    Short preview for the CSV column so you can skim notes in Excel
    without scrolling huge text columns.
    """
    t = text.replace("\n", " ").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 3] + "..."


# ----------------- Core logic ----------------- #

def build_repeat_info(
    notes: List[Dict[str, Any]],
    min_occurrences: int,
    min_content_length: int,
) -> Dict[str, Dict[str, Any]]:
    """
    Compute repeated-text info.

    Returns a dict keyed by normalized text, with values:
        {
            "occurrences": int,
            "group_id": str | None,   # e.g. "RN1" for repeated notes, else None
        }
    Only texts that meet both thresholds (occurrences and content length)
    get a non-None group_id.
    """
    norm_texts: List[str] = []

    for note in notes:
        text = first(note, ["text", "content", "note_text", "value"])
        if not text:
            norm_texts.append("")  # still keep index alignment
            continue
        norm = normalize_text(str(text))
        norm_texts.append(norm)

    counts = Counter(norm_texts)

    # Build group IDs for repeated notes
    # Sort by count desc, then alphabetically for stability
    repeated_norms = [
        nt for nt, cnt in counts.items()
        if cnt >= min_occurrences and len(nt) >= min_content_length and nt != ""
    ]
    repeated_norms.sort(key=lambda nt: (-counts[nt], nt))

    repeat_info: Dict[str, Dict[str, Any]] = {}

    # Assign group IDs only for repeated texts
    for idx, norm in enumerate(repeated_norms, start=1):
        repeat_info[norm] = {
            "occurrences": counts[norm],
            "group_id": f"RN{idx}",
        }

    # For all other texts, record occurrences but no group_id
    for norm, cnt in counts.items():
        if norm in repeat_info:
            continue
        repeat_info[norm] = {
            "occurrences": cnt,
            "group_id": None,
        }

    return repeat_info


def write_notes_csv(
    notes: List[Dict[str, Any]],
    repeat_info: Dict[str, Dict[str, Any]],
    output_path: Path,
) -> None:
    """
    Write the notes table CSV.

    Columns are chosen to be Excel-friendly and human-readable.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
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
    ]

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for idx, note in enumerate(notes, start=1):
            text = first(note, ["text", "content", "note_text", "value"])
            if text is None:
                text = ""

            text_str = str(text)
            norm = normalize_text(text_str)

            info = repeat_info.get(norm, {"occurrences": 0, "group_id": None})
            occurrences = info.get("occurrences", 0)
            group_id = info.get("group_id")

            row = {
                "global_index": idx,
                "page": first(note, ["page", "page_number", "page_index", "page_num"]),
                "column": first(note, ["column", "column_index", "column_id", "col"]),
                "visual_note_id": first(
                    note, ["visual_note_id", "note_id", "visual_id", "id"]
                ),
                "visual_region": first(
                    note, ["visual_region", "region", "bbox_id", "box_id"]
                ),
                "is_repeated": "yes" if group_id is not None else "no",
                "repeated_group_id": group_id or "",
                "repeated_occurrences": occurrences,
                "text_preview": text_preview(text_str),
                "text": text_str,
            }

            writer.writerow(row)


# ----------------- CLI entrypoint ----------------- #

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export sheetwide notes to CSV for tagging/analysis."
    )
    parser.add_argument(
        "--export-json",
        type=str,
        default=str(DEFAULT_EXPORT_JSON),
        help="Path to all_pages_notes_sheetwide.json "
             "(default: exports/all_pages_notes_sheetwide.json)",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=str(DEFAULT_OUTPUT_CSV),
        help="Output CSV path (default: exports/notes_table.csv)",
    )
    parser.add_argument(
        "--min-occurrences",
        type=int,
        default=DEFAULT_MIN_OCCURRENCES,
        help=f"Minimum occurrences for a note text to be considered repeated "
             f"(default: {DEFAULT_MIN_OCCURRENCES})",
    )
    parser.add_argument(
        "--min-length",
        type=int,
        default=DEFAULT_MIN_CONTENT_LENGTH,
        help=f"Minimum content length for repeat detection "
             f"(default: {DEFAULT_MIN_CONTENT_LENGTH})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = project_root()

    export_path = (root / args.export_json).resolve()
    output_path = (root / args.out).resolve()

    if not export_path.exists():
        raise FileNotFoundError(
            f"Notes export not found at: {export_path}"
        )

    notes = load_notes(export_path)
    repeat_info = build_repeat_info(
        notes=notes,
        min_occurrences=args.min_occurrences,
        min_content_length=args.min_length,
    )

    write_notes_csv(
        notes=notes,
        repeat_info=repeat_info,
        output_path=output_path,
    )

    repeated_count = sum(
        1
        for info in repeat_info.values()
        if info.get("group_id") is not None
    )

    print(f"Loaded notes from: {export_path}")
    print(f"Total notes: {len(notes)}")
    print(f"Repeated text groups (>= {args.min_occurrences} occurrences, "
          f"len >= {args.min_length}): {repeated_count}")
    print(f"CSV written to: {output_path}")


if __name__ == "__main__":
    main()
