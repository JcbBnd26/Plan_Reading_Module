# ------------------------------------------------------------
# notes_extractor.py  (FULL WORKING FILE)
# ------------------------------------------------------------
import json
import csv
from backbone.chunking import Chunker

OUTPUT_JSON = "notes.json"
OUTPUT_CSV = "notes.csv"
PDF_NAME = "test.pdf"


def extract_notes():
    print(">>> Extracting notes from:", PDF_NAME)

    chunker = Chunker()
    chunks = chunker.process(PDF_NAME)

    print(f">>> Total merged chunks: {len(chunks)}")

    notes = []

    for ch in chunks:
        # Only export merged notes or text_lines (fallback)
        if ch.type not in ("merged_note", "text_line"):
            continue

        record = {
            "page": ch.page_number,
            "column": ch.metadata.get("column", None),
            "type": ch.type,
            "text": ch.content.strip() if ch.content else "",
            "bbox": {
                "x1": ch.bbox[0],
                "y1": ch.bbox[1],
                "x2": ch.bbox[2],
                "y2": ch.bbox[3],
            },
            # fingerprint for traceability
            "fingerprint": f"{ch.page_number}-{abs(hash(ch.content)) % (10**12)}",
        }

        notes.append(record)

    # --------------------------------------------------------
    # Write JSON
    # --------------------------------------------------------
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(notes, f, indent=2, ensure_ascii=False)

    print(f">>> Saved JSON: {OUTPUT_JSON}")

    # --------------------------------------------------------
    # Write CSV
    # --------------------------------------------------------
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["page", "column", "type", "text", "bbox", "fingerprint"])

        for n in notes:
            writer.writerow([
                n["page"],
                n["column"],
                n["type"],
                n["text"],
                json.dumps(n["bbox"]),
                n["fingerprint"],
            ])

    print(f">>> Saved CSV: {OUTPUT_CSV}")
    print(">>> DONE")


# ------------------------------------------------------------
# Run script
# ------------------------------------------------------------
if __name__ == "__main__":
    extract_notes()
