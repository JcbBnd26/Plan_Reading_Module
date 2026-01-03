#!/usr/bin/env python
"""
combine_page_box_classes_all.py

Combine per-page box classification files like:

  exports/page_box_classes_p3_refined_projectpanel.json
  exports/page_box_classes_p4_refined_projectpanel.json
  ...

into a single JSON:

  exports/page_box_classes_all_refined_projectpanel.json

The output structure is the same shape used by mask_notes_by_box_type.py:

  {
    "pages": {
      "1": { "boxes": [...] },
      "2": { "boxes": [...] },
      ...
    }
  }

Any extra top-level keys in the inputs (boxes_source, ocr_source, etc.)
are ignored; we only care about the "pages" content.
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
from typing import Dict, Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Combine per-page page_box_classes JSON files into one all-pages file."
    )
    parser.add_argument(
        "--glob",
        required=True,
        help=(
            "Glob pattern for per-page JSON files, e.g. "
            "'exports/page_box_classes_p*_refined_projectpanel.json'"
        ),
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output JSON path, e.g. exports/page_box_classes_all_refined_projectpanel.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    pattern = args.glob
    out_path = Path(args.out)

    files = sorted(glob.glob(pattern))
    if not files:
        raise SystemExit(f"No files matched glob pattern: {pattern!r}")

    combined_pages: Dict[str, Any] = {}

    print(f"[info] Combining {len(files)} file(s) matching {pattern!r}")
    for path in files:
        p = Path(path)
        print(f"[info]  - loading {p}")
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)

        pages = data.get("pages", {})
        for page_key, page_data in pages.items():
            if page_key in combined_pages:
                # Overwrite on conflict but log it so it's obvious.
                print(f"[warn] Duplicate page {page_key} encountered, overwriting previous entry.")
            combined_pages[page_key] = page_data

    out_obj = {"pages": combined_pages}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out_obj, f, indent=2)
    print(f"[info] Wrote combined box classes to {out_path}")


if __name__ == "__main__":
    main()
