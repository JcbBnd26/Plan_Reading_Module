"""
tools/repeated_notes_report.py

Generate a Markdown report of repeated notes across a sheet-wide notes export.

This script consumes the JSON produced by tools/export_notes_json.py when
called with --all-pages and --notes-only, and looks for text that appears on
multiple pages. It is meant as an analysis/QA tool for plan sets.

Usage (from repo root):

    py tools\repeated_notes_report.py ^
        --file exports\all_pages_notes_sheetwide.json ^
        --out exports\notes_repeated_report.md ^
        --min-occurrences 2 ^
        --min-length 10

The thresholds are tweakable via CLI flags.
"""

import argparse
import json
import os
from typing import Any, Dict, List, Tuple


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_text(text: Any) -> str:
    """
    Normalize text for grouping:

    - ensure it's a string
    - replace CR with space
    - compress all whitespace (spaces, tabs, newlines) to single spaces
    - trim leading/trailing whitespace
    """
    if text is None:
        return ""
    s = str(text)
    s = s.replace("\r", " ")
    s = " ".join(s.split())
    return s.strip()


def load_json_notes(path: str) -> List[Dict[str, Any]]:
    """
    Load a JSON file that is expected to contain a list of note dictionaries.

    We keep this loose to match whatever export_notes_json.py writes.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Common case: the export is just a list of chunk/note dicts.
    if isinstance(data, list):
        return data

    # Some exports might wrap notes under a key.
    if isinstance(data, dict):
        for key in ("notes", "chunks", "items", "data", "records"):
            value = data.get(key)
            if isinstance(value, list):
                return value

    raise ValueError(
        f"Unsupported JSON structure in {path!r}. "
        "Expected a list or a dict containing a list under one of: "
        "notes, chunks, items, data, records."
    )


def collect_occurrences(
    notes: List[Dict[str, Any]],
    min_length: int,
) -> Dict[str, Dict[str, Any]]:
    """
    Group notes by normalized text.

    Returns a mapping:
        normalized_text -> {
            "preview": one example raw text,
            "occurrences": [
                {
                    "page": int,
                    "column": str | None,
                    "visual_note_id": str | None,
                    "visual_region": str | None,
                },
                ...
            ],
        }
    """
    groups: Dict[str, Dict[str, Any]] = {}

    for note in notes:
        # Try multiple possible text keys, but prefer "text".
        raw_text = (
            note.get("text")
            or note.get("content")
            or note.get("note_text")
            or ""
        )

        norm = normalize_text(raw_text)
        if not norm:
            continue
        if len(norm) < min_length:
            continue

        # Column / note / region fields – mirror view_notes_json.py behavior.
        page = note.get("page")
        column = (
            note.get("visual_column_id")
            or note.get("column")
            or None
        )
        visual_note_id = (
            note.get("visual_note_id")
            or note.get("note_id")
            or None
        )
        visual_region = (
            note.get("visual_region")
            or note.get("region")
            or None
        )

        if norm not in groups:
            groups[norm] = {
                "preview": raw_text,
                "occurrences": [],
            }

        groups[norm]["occurrences"].append(
            {
                "page": page,
                "column": column,
                "visual_note_id": visual_note_id,
                "visual_region": visual_region,
            }
        )

    return groups


def filter_and_sort_groups(
    groups: Dict[str, Dict[str, Any]],
    min_occurrences: int,
) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Filter groups that do not meet the occurrence threshold, then sort by:

    - descending occurrence count
    - then lexicographically by normalized text
    """
    filtered: List[Tuple[str, Dict[str, Any]]] = []

    for norm_text, data in groups.items():
        occ_count = len(data["occurrences"])
        if occ_count >= min_occurrences:
            filtered.append((norm_text, data))

    filtered.sort(key=lambda pair: (-len(pair[1]["occurrences"]), pair[0]))
    return filtered


def format_markdown_report(
    source_file: str,
    total_notes: int,
    groups: List[Tuple[str, Dict[str, Any]]],
    min_occurrences: int,
    min_length: int,
) -> str:
    """
    Build the Markdown report.

    We add extra blank lines between each note block so they’re easier to
    visually separate while scrolling.
    """
    lines: List[str] = []
    lines.append("# Repeated Notes Report")
    lines.append("")
    lines.append(f"- Source file: `{source_file}`")
    lines.append(f"- Total notes in export: {total_notes}")
    lines.append(f"- Minimum occurrences threshold: {min_occurrences}")
    lines.append(f"- Minimum content length: {min_length} characters")
    lines.append(f"- Repeated note groups found: {len(groups)}")
    lines.append("")

    if not groups:
        # No repeated groups – header is enough.
        return "\n".join(lines).rstrip() + "\n"

    for idx, (norm_text, data) in enumerate(groups, start=1):
        occurrences = data["occurrences"]
        pages = sorted(
            {occ["page"] for occ in occurrences if occ.get("page") is not None}
        )

        # Heading
        lines.append(
            f"## Note {idx} (occurrences: {len(occurrences)}, pages: {pages})"
        )
        lines.append("")

        # Text preview block
        preview_raw = data.get("preview", "")
        preview = normalize_text(preview_raw)
        max_preview_len = 200
        if len(preview) > max_preview_len:
            preview = preview[: max_preview_len - 3] + "..."

        lines.append("**Text preview:**")
        lines.append("")
        lines.append("> " + preview)
        lines.append("")

        # Instances table
        lines.append("**Instances:**")
        lines.append("")
        lines.append("| # | Page | Column | Visual Note ID | Visual Region |")
        lines.append("|---|------|--------|----------------|---------------|")

        for i, occ in enumerate(occurrences, start=1):
            page = occ.get("page", "")
            col = occ.get("column") or "None"
            visual_note_id = occ.get("visual_note_id") or "None"
            visual_region = occ.get("visual_region") or "None"
            lines.append(
                f"| {i} | {page} | {col} | {visual_note_id} | {visual_region} |"
            )

        # EXTRA SEPARATION: add two blank lines between note groups
        lines.append("")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a Markdown report of repeated notes across pages.",
    )
    parser.add_argument(
        "--file",
        required=True,
        help="Path to JSON export (e.g. exports\\all_pages_notes_sheetwide.json).",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Path to output Markdown report (e.g. exports\\notes_repeated_report.md).",
    )
    parser.add_argument(
        "--min-occurrences",
        type=int,
        default=2,
        help="Minimum number of occurrences required to include a note group "
             "(default: 2).",
    )
    parser.add_argument(
        "--min-length",
        type=int,
        default=10,
        help="Minimum normalized text length required to include a note "
             "(default: 10).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    source_path = args.file
    out_path = args.out
    min_occurrences = max(1, int(args.min_occurrences))
    min_length = max(1, int(args.min_length))

    if not os.path.exists(source_path):
        raise SystemExit(f"Input file not found: {source_path}")

    print(f">>> Loading notes from: {source_path}")
    notes = load_json_notes(source_path)
    print(f">>> Loaded {len(notes)} note item(s).")

    print(">>> Grouping and filtering...")
    groups_raw = collect_occurrences(notes, min_length=min_length)
    print(f">>> Unique normalized texts meeting length>= {min_length}: {len(groups_raw)}")

    groups_sorted = filter_and_sort_groups(
        groups_raw,
        min_occurrences=min_occurrences,
    )
    print(
        f">>> Groups with occurrences >= {min_occurrences}: "
        f"{len(groups_sorted)}"
    )

    print(">>> Building Markdown report...")
    report_text = format_markdown_report(
        source_file=source_path,
        total_notes=len(notes),
        groups=groups_sorted,
        min_occurrences=min_occurrences,
        min_length=min_length,
    )

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f">>> Repeated notes report written to: {out_path}")
    print(">>> DONE.")


if __name__ == "__main__":
    main()
