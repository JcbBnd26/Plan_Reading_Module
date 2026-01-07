# notes_extractor.py - FIXED & IMPROVED VERSION
# Full replacement - copy-paste entire file
# Handles Chunk.page_number drift, proper --out, atomic write, CSV bonus

import json
import csv
import argparse
import os
from backbone.chunking import Chunker

DEFAULT_PDF = "test.pdf"
DEFAULT_OUT_JSON = "exports/MostRecent/raw_notes_all_pages.json"
DEFAULT_OUT_CSV = "exports/MostRecent/raw_notes.csv"

def extract_notes(pdf_path, out_json, out_csv):
    print(">>> Extracting notes from:", pdf_path)
    print(">>> VISUAL BRIDGE: disabled or not available.")
    print(">>> STARTING PER-PAGE CHUNKER")
    print(">>> Source PDF:", pdf_path)
    print(">>> USING LINE-LEVEL EXTRACTOR <<<")

    chunker = Chunker()
    chunks = chunker.process(pdf_path)

    notes = []
    total_merged = len(chunks)
    print(f">>> TOTAL CHUNKS AFTER GROUPING: {total_merged}")

    for ch in chunks:
        if ch.type not in ("merged_note", "text_line", "note"):
            continue

        # Handle code drift: old versions used page_number, new use page
        page_num = getattr(ch, "page_number", None)
        if page_num is None:
            page_num = getattr(ch, "page", 0)

        record = {
            "page": int(page_num),
            "column": ch.metadata.get("column", None),
            "type": ch.type,
            "text": (ch.content or "").strip(),
            "bbox": {
                "x0": float(ch.bbox[0]),
                "y0": float(ch.bbox[1]),
                "x1": float(ch.bbox[2]),
                "y1": float(ch.bbox[3])
            }
        }
        notes.append(record)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(out_json), exist_ok=True)

    # Atomic JSON write
    temp_json = out_json + ".tmp"
    with open(temp_json, "w", encoding="utf-8") as f:
        json.dump(notes, f, indent=2, ensure_ascii=False)
    os.replace(temp_json, out_json)
    print(f">>> Saved JSON: {out_json} ({len(notes)} records)")

    # CSV bonus
    csv_dir = os.path.dirname(out_csv)
    os.makedirs(csv_dir, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["page", "column", "type", "text", "x0", "y0", "x1", "y1"])
        for n in notes:
            b = n["bbox"]
            writer.writerow([n["page"], n["column"], n["type"], n["text"],
                             b["x0"], b["y0"], b["x1"], b["y1"]])
    print(f">>> Saved CSV: {out_csv}")

    print(">>> EXTRACTION COMPLETE")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract raw notes from PDF")
    parser.add_argument("--pdf", default=DEFAULT_PDF, help="Input PDF path")
    parser.add_argument("--out", default=DEFAULT_OUT_JSON, help="Output JSON path")
    parser.add_argument("--csv", default=DEFAULT_OUT_CSV, help="Output CSV path")
    args = parser.parse_args()

    extract_notes(args.pdf, args.out, args.csv)