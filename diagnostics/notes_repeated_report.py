#!/usr/bin/env python
"""
Generate a repeated-notes markdown report from the sheetwide notes export.

- Groups identical note text across pages
- Only keeps notes with:
    * occurrences >= MIN_OCCURRENCES
    * text length >= MIN_CONTENT_LENGTH
- Writes a markdown report to exports/notes_repeated_report.md

Table formatting:
- All columns (#, Page, Column, Visual Note ID, Visual Region) are padded
  so each cell width matches the widest of its header text or any cell in
  that column. This keeps everything aligned in plain text.
- A blank line is inserted after every note group.
"""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple


# ----------------- Configuration ----------------- #

MIN_OCCURRENCES = 2          # minimum number of times a note must appear
MIN_CONTENT_LENGTH = 10      # minimum text length (after trimming) to consider

EXPORT_REL_PATH = Path("exports") / "all_pages_notes_sheetwide.json"
OUTPUT_REL_PATH = Path("exports") / "notes_repeated_report.md"


# ----------------- Helpers ----------------- #

def project_root() -> Path:
    """Assume this script lives in `diagnostics/` and root is its parent."""
    return Path(__file__).resolve().parent.parent


def load_notes(path: Path) -> List[Dict[str, Any]]:
    """Load notes list from JSON; handle a few possible JSON layouts."""
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        # Common pattern: {"notes": [...]}
        if "notes" in data and isinstance(data["notes"], list):
            return data["notes"]

        # Fallback: flatten first list-like value we find
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v

    raise ValueError(f"Unsupported JSON structure in {path}")


def first(d: Dict[str, Any], keys: List[str], default: Any = None) -> Any:
    """Return the first existing key in `d` from `keys`, or `default`."""
    for k in keys:
        if k in d:
            return d[k]
    return default


def normalize_text(text: str) -> str:
    """Normalize note text for grouping."""
    return " ".join(text.strip().split())


def group_notes(raw_notes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Group notes by normalized text and filter by thresholds.

    Returns a list of groups:
    {
        "text": original_text_preview,
        "instances": [
            {"page": int|None, "column": Any, "visual_note_id": Any, "visual_region": Any},
            ...
        ]
    }
    """
    groups: defaultdict[str, List[Dict[str, Any]]] = defaultdict(list)

    for note in raw_notes:
        text = first(note, ["text", "content", "note_text", "value"])
        if not text:
            continue

        norm = normalize_text(str(text))
        if not norm:
            continue

        page = first(note, ["page", "page_number", "page_index", "page_num"])
        column = first(note, ["column", "column_index", "column_id", "col"])
        visual_note_id = first(
            note, ["visual_note_id", "note_id", "visual_id", "id"]
        )
        visual_region = first(
            note, ["visual_region", "region", "bbox_id", "box_id"]
        )

        groups[norm].append(
            {
                "page": page,
                "column": column,
                "visual_note_id": visual_note_id,
                "visual_region": visual_region,
                "original_text": str(text),
            }
        )

    filtered_groups: List[Dict[str, Any]] = []

    for norm_text, instances in groups.items():
        original_text = instances[0]["original_text"]

        if len(instances) < MIN_OCCURRENCES:
            continue
        if len(norm_text) < MIN_CONTENT_LENGTH:
            continue

        # Sort instances by page, then by visual_note_id/region for stability
        def sort_key(inst: Dict[str, Any]) -> Tuple:
            page_val = inst["page"]
            try:
                page_int = int(page_val)
            except (TypeError, ValueError):
                page_int = 0
            return (
                page_int,
                str(inst["visual_note_id"]),
                str(inst["visual_region"]),
            )

        instances_sorted = sorted(instances, key=sort_key)

        filtered_groups.append(
            {
                "text": original_text,
                "norm_text": norm_text,
                "instances": instances_sorted,
            }
        )

    # Sort by number of occurrences (desc), then by text
    filtered_groups.sort(
        key=lambda g: (-len(g["instances"]), g["norm_text"])
    )

    return filtered_groups


def format_text_preview(text: str, max_len: int = 200) -> str:
    """Truncate very long text for the preview block."""
    stripped = text.strip().replace("\n", " ")
    if len(stripped) <= max_len:
        return stripped
    return stripped[: max_len - 3] + "..."


# ----------------- Markdown writer ----------------- #

def write_instances_table(lines: List[str], instances: List[Dict[str, Any]]) -> None:
    """
    Append a markdown table of instances to `lines`, with all columns
    padded so each column width matches the widest of its header or data.
    """
    # Prepare raw cell strings for each column
    idx_cells: List[str] = []
    page_cells: List[str] = []
    col_cells: List[str] = []
    vid_cells: List[str] = []
    vreg_cells: List[str] = []

    for row_idx, inst in enumerate(instances, start=1):
        idx_cells.append(str(row_idx))

        page = inst["page"] if inst["page"] is not None else "None"
        page_cells.append(str(page))

        column = inst["column"] if inst["column"] not in (None, "") else "None"
        col_cells.append(str(column))

        v_id = (
            inst["visual_note_id"]
            if inst["visual_note_id"] not in (None, "")
            else "None"
        )
        vid_cells.append(str(v_id))

        v_region = (
            inst["visual_region"]
            if inst["visual_region"] not in (None, "")
            else "None"
        )
        vreg_cells.append(str(v_region))

    headers = ["#", "Page", "Column", "Visual Note ID", "Visual Region"]
    columns = [idx_cells, page_cells, col_cells, vid_cells, vreg_cells]

    # Compute width for each column: max(len(header), len(any cell))
    widths: List[int] = []
    for header, col in zip(headers, columns):
        max_cell_len = max((len(c) for c in col), default=0)
        widths.append(max(len(header), max_cell_len))

    # Header row
    header_row = "| " + " | ".join(
        header.ljust(width) for header, width in zip(headers, widths)
    ) + " |"
    # Separator row
    sep_row = "| " + " | ".join(
        "-" * width for width in widths
    ) + " |"

    lines.append("**Instances:**")
    lines.append("")
    lines.append(header_row)
    lines.append(sep_row)

    # Data rows
    for row_vals in zip(idx_cells, page_cells, col_cells, vid_cells, vreg_cells):
        row = "| " + " | ".join(
            val.ljust(width) for val, width in zip(row_vals, widths)
        ) + " |"
        lines.append(row)


def write_report(
    output_path: Path,
    source_rel_str: str,
    total_notes: int,
    groups: List[Dict[str, Any]],
) -> None:
    """Write the markdown report file."""
    repeated_count = len(groups)

    lines: List[str] = []
    lines.append("# Repeated Notes Report\n")
    lines.append(f"- Source file: `{source_rel_str}`")
    lines.append(f"- Total notes in export: {total_notes}")
    lines.append(f"- Minimum occurrences threshold: {MIN_OCCURRENCES}")
    lines.append(
        f"- Minimum content length: {MIN_CONTENT_LENGTH} characters"
    )
    lines.append(f"- Repeated note groups found: {repeated_count}\n")

    if repeated_count == 0:
        output_path.write_text("\n".join(lines), encoding="utf-8")
        return

    for idx, group in enumerate(groups, start=1):
        instances = group["instances"]
        occ = len(instances)
        pages = sorted(
            {
                inst["page"]
                for inst in instances
                if inst["page"] is not None
            }
        )
        pages_str = ", ".join(str(p) for p in pages)

        lines.append(
            f"## Note {idx} (occurrences: {occ}, pages: [{pages_str}])\n"
        )
        lines.append("**Text preview:**\n")
        lines.append("> " + format_text_preview(group["text"]) + "\n")

        # instances table with full column-width alignment
        write_instances_table(lines, instances)

        lines.append("")  # blank line between notes

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    root = project_root()
    export_path = root / EXPORT_REL_PATH
    output_path = root / OUTPUT_REL_PATH

    if not export_path.exists():
        raise FileNotFoundError(
            f"Notes export not found at: {export_path}"
        )

    notes = load_notes(export_path)
    groups = group_notes(notes)

    source_rel_str = str(EXPORT_REL_PATH).replace("/", "\\")
    write_report(
        output_path=output_path,
        source_rel_str=source_rel_str,
        total_notes=len(notes),
        groups=groups,
    )

    print(f"Repeated notes report written to: {output_path}")
    print(f"Repeated note groups found: {len(groups)}")


if __name__ == "__main__":
    main()
