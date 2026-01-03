#!/usr/bin/env python
"""
structural_pipeline.py

High-level "generalized panel detector" for plan sets.

Given:
  - a PDF (plan set)
  - a sheetwide OCR notes JSON

Run for a page range:
  1) detect_page_boxes.py        -> per-page raw boxes
  2) classify_page_boxes.py      -> per-page typed boxes (legend, project_info_panel, ...)
  3) refine_legend_boxes.py      -> per-page merged legend + unified project_info_panel
  4) combine_page_box_classes_all.py -> single all-pages structural map
  5) mask_notes_by_box_type.py   -> global structurally-masked notes JSON

This turns:
  all_pages_notes_sheetwide.json
into:
  all_pages_notes_sheetwide_no_legend_structural.json

…for ANY plan set, just by passing PDF, notes JSON, and page range.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run_cmd(args: list[str]) -> None:
    """
    Run a subprocess, streaming output. Raise if it fails.

    This always uses the current Python interpreter (sys.executable)
    for .py scripts, so it respects the active venv.
    """
    print(f"[cmd] {' '.join(args)}")
    result = subprocess.run(args)
    if result.returncode != 0:
        raise SystemExit(f"Command failed with exit code {result.returncode}: {' '.join(args)}")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def run_structural_pipeline(
    pdf_path: Path,
    notes_json: Path,
    out_dir: Path,
    first_page: int,
    last_page: int,
) -> None:
    """
    Run the full structural pipeline on pages [first_page, last_page].

    All intermediate JSONs live in out_dir. Final outputs:

      - out_dir / "page_box_classes_all_refined_projectpanel.json"
      - out_dir / "all_pages_notes_sheetwide_no_legend_structural.json"
    """
    py = sys.executable

    out_dir.mkdir(parents=True, exist_ok=True)

    # Normalize to absolute paths so everything is stable
    pdf_path = pdf_path.resolve()
    notes_json = notes_json.resolve()
    out_dir = out_dir.resolve()

    print(f"[info] PDF          : {pdf_path}")
    print(f"[info] Notes JSON   : {notes_json}")
    print(f"[info] Out dir      : {out_dir}")
    print(f"[info] Page range   : {first_page}..{last_page}")

    # 1–3: Per-page detection, classification, refinement
    for page in range(first_page, last_page + 1):
        print(f"\n=== Page {page} ===")

        boxes_json = out_dir / f"page_boxes_p{page}.json"
        classes_json = out_dir / f"page_box_classes_p{page}_titleblockfix.json"
        refined_json = out_dir / f"page_box_classes_p{page}_refined_projectpanel.json"

        # 1) detect_page_boxes.py
        run_cmd(
            [
                py,
                "tools/detect_page_boxes.py",
                "--pdf",
                str(pdf_path),
                "--out",
                str(boxes_json),
                "--pages",
                str(page),
            ]
        )

        # 2) classify_page_boxes.py
        run_cmd(
            [
                py,
                "tools/classify_page_boxes.py",
                "--boxes-json",
                str(boxes_json),
                "--ocr-json",
                str(notes_json),
                "--out",
                str(classes_json),
                "--pages",
                str(page),
            ]
        )

        # 3) refine_legend_boxes.py
        run_cmd(
            [
                py,
                "tools/refine_legend_boxes.py",
                "--input",
                str(classes_json),
                "--output",
                str(refined_json),
                "--pages",
                str(page),
                "--max-area-frac",
                "0.2",
            ]
        )

    # 4) combine_page_box_classes_all.py
    combined_boxes = out_dir / "page_box_classes_all_refined_projectpanel.json"
    run_cmd(
        [
            py,
            "tools/combine_page_box_classes_all.py",
            "--glob",
            str(out_dir / "page_box_classes_p*_refined_projectpanel.json"),
            "--out",
            str(combined_boxes),
        ]
    )

    # 5) mask_notes_by_box_type.py
    masked_notes = out_dir / "all_pages_notes_sheetwide_no_legend_structural.json"
    run_cmd(
        [
            py,
            "tools/mask_notes_by_box_type.py",
            "--notes-json",
            str(notes_json),
            "--box-classes-json",
            str(combined_boxes),
            "--out",
            str(masked_notes),
            "--exclude-types",
            "legend",
            "title_block",
        ]
    )

    print("\n[done] Structural pipeline complete.")
    print(f"[done] Combined box classes : {combined_boxes}")
    print(f"[done] Masked notes JSON    : {masked_notes}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Run the full structural panel detector pipeline "
            "(detection + classification + refinement + masking) "
            "on a PDF and sheetwide notes JSON."
        )
    )
    p.add_argument(
        "--pdf",
        required=True,
        help="Input PDF path (plan set).",
    )
    p.add_argument(
        "--notes-json",
        required=True,
        help="Original sheetwide notes JSON (e.g. exports/all_pages_notes_sheetwide.json).",
    )
    p.add_argument(
        "--out-dir",
        default="exports/structural",
        help="Output directory for structural artifacts (default: exports/structural).",
    )
    p.add_argument(
        "--first-page",
        type=int,
        default=1,
        help="First 1-based page to process (default: 1).",
    )
    p.add_argument(
        "--last-page",
        type=int,
        required=True,
        help="Last 1-based page to process (inclusive).",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    run_structural_pipeline(
        pdf_path=Path(args.pdf),
        notes_json=Path(args.notes_json),
        out_dir=Path(args.out_dir),
        first_page=int(args.first_page),
        last_page=int(args.last_page),
    )


if __name__ == "__main__":
    main()
