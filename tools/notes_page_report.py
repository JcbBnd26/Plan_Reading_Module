# notes_page_report.py
# Tool to generate a per-page notes summary from an exported notes JSON file.
#
# Example usage (from project root):
#
#   py tools\\notes_page_report.py --file exports\\all_pages_notes_sheetwide.json --out exports\\notes_page_report.md
#
# This will:
#   1. Load the exported JSON
#   2. Group notes by page (and optionally by column)
#   3. Write a Markdown report with a section per page

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate per-page notes summary from exported notes JSON."
    )

    parser.add_argument(
        "--file",
        type=str,
        required=True,
        help="Path to exported notes JSON (e.g. exports\\all_pages_notes_sheetwide.json).",
    )

    parser.add_argument(
        "--out",
        type=str,
        default="exports\\notes_page_report.md",
        help="Output Markdown report path (default: exports\\notes_page_report.md).",
    )

    parser.add_argument(
        "--max-notes-per-page",
        type=int,
        default=200,
        help="Maximum notes to list per page (default: 200).",
    )

    return parser.parse_args(argv)


def load_export(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Export file not found: {path}")
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


def make_preview(text: str, max_len: int = 140) -> str:
    text = text.replace("\\n", " ")
    text = " ".join(text.split())
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def build_page_report(
    source_path: Path,
    data: Dict[str, Any],
    max_notes_per_page: int,
) -> str:
    chunks: List[Dict[str, Any]] = data.get("chunks", [])
    total_chunks = len(chunks)

    # Group by page, then by column
    by_page: Dict[int, Dict[str, List[Dict[str, Any]]]] = {}

    for ch in chunks:
        page = ch.get("page")
        if not isinstance(page, int):
            continue
        col = ch.get("visual_column_id") or "unassigned"
        by_page.setdefault(page, {}).setdefault(col, []).append(ch)

    page_ids = sorted(by_page.keys())

    lines: List[str] = []
    lines.append("# Notes Per-Page Report")
    lines.append("")
    lines.append(f"- Source file: `{source_path}`")
    lines.append(f"- Total notes in export: {total_chunks}")
    lines.append(f"- Pages with notes: {page_ids}")
    lines.append("")

    for page in page_ids:
        col_map = by_page[page]
        total_for_page = sum(len(v) for v in col_map.values())

        lines.append(f"## Page {page}")
        lines.append("")
        lines.append(f"- Total notes on this page: {total_for_page}")
        lines.append(f"- Columns on this page: {sorted(col_map.keys())}")
        lines.append("")

        listed_count = 0

        for col_name in sorted(col_map.keys()):
            notes = col_map[col_name]

            lines.append(f"### Column `{col_name}`")
            lines.append("")

            for ch in notes:
                if listed_count >= max_notes_per_page:
                    break

                content = (ch.get("content") or "").strip()
                preview = make_preview(content)
                vid = ch.get("visual_note_id")

                lines.append(f"- **Note ID:** `{vid}`  \\")
                lines.append(f"  **Text:** {preview}")
                lines.append("")

                listed_count += 1

            if listed_count >= max_notes_per_page:
                remaining = total_for_page - listed_count
                if remaining > 0:
                    lines.append(
                        f"... (truncated, showing first {listed_count} of {total_for_page} notes on this page)"
                    )
                    lines.append("")
                break

        lines.append("")

    return "\\n".join(lines)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)

    export_path = Path(args.file)
    out_path = Path(args.out)

    data = load_export(export_path)

    report_md = build_page_report(
        source_path=export_path,
        data=data,
        max_notes_per_page=args.max_notes_per_page,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report_md, encoding="utf-8")

    print(f">>> Notes per-page report written to: {out_path}")


if __name__ == "__main__":
    main()
