# run_page3_full_pipeline.py - ONE SCRIPT TO RULE THE PIPELINE
# End drift, silent failures, and bad overlays
# Full self-contained runner for page 3
# Tunable masking, merge gap
# Validation + diagnostics at every step

import json
import os
import argparse
from backbone.chunking import Chunker  # Assume this is the core extractor

# Simple bbox utils to kill drift
def center_x(bbox):
    return (bbox["x0"] + bbox["x1"]) / 2

def union_bbox(b1, b2):
    return {
        "x0": min(b1["x0"], b2["x0"]),
        "y0": min(b1["y0"], b2["y0"]),
        "x1": max(b1["x1"], b2["x1"]),
        "y1": max(b1["y1"], b2["y1"])
    }

def run_pipeline(pdf_path = "test.pdf", page = 3, max_gap = 40, mask_legend = True):
    out_dir = "exports\\MostRecent"
    os.makedirs(out_dir, exist_ok=True)

    print("[1] Extracting raw chunks...")
    chunker = Chunker()
    all_chunks = chunker.process(pdf_path)
    raw_path = f"{out_dir}\\raw.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, indent=2)
    print(f"    Raw chunks saved: {raw_path}")

    print("[2] Masking legend/titleblock...")
    page_chunks = [c for c in all_chunks if c.page == page]
    masked = [c for c in all_chunks if c.page != page]
    masked_count = 0
    if mask_legend:
        # Smarter page-size aware masking
        x_coords = [c.bbox["x0"] for c in page_chunks] + [c.bbox["x1"] for c in page_chunks]
        y_coords = [c.bbox["y0"] for c in page_chunks] + [c.bbox["y1"] for c in page_chunks]
        page_width = max(x_coords) - min(x_coords)
        legend_x = min(x_coords) + page_width * 0.6
        title_y = min(y_coords) + (max(y_coords) - min(y_coords)) * 0.8
        for c in page_chunks:
            cx = center_x(c.bbox)
            cy = (c.bbox["y0"] + c.bbox["y1"]) / 2
            if cx > legend_x or cy > title_y:
                masked_count += 1
                c["type"] = "masked_noise"
            masked.append(c)
    else:
        masked.extend(page_chunks)
    masked_path = f"{out_dir}\\masked.json"
    with open(masked_path, "w", encoding="utf-8") as f:
        json.dump(masked, f, indent=2)
    print(f"    Masked {masked_count} noise chunks")

    # Simple header tagging (uppercase + "NOTES")
    print("[3] Tagging headers...")
    headers = 0
    for c in masked:
        if c.get("page") == page and "NOTES" in c["text"].upper() and len(c["text"]) < 200:
            c["type"] = "header_candidate"
            headers += 1
    print(f"    Tagged {headers} headers")

    # Simple merge (column binned, header banded)
    print("[4] Merging notes...")
    notes = [c for c in masked if c.get("page") == page and c.get("type") not in ("header_candidate", "masked_noise")]
    headers = [c for c in masked if c.get("page") == page and c.get("type") == "header_candidate"]
    header_y_bands = [(h.bbox["y0"], h.bbox["y1"]) for h in headers]

    # Column binning
    centers = [center_x(c.bbox) for c in notes]
    column_bins = {}
    if centers:
        centers_sorted = sorted(set(centers))
        tol = 80
        bin_id = 0
        current = [centers_sorted[0]]
        for x in centers_sorted[1:]:
            if x - mean(current) < tol:
                current.append(x)
            else:
                column_bins[bin_id] = [n for n in notes if abs(center_x(n.bbox) - mean(current)) < tol]
                bin_id += 1
                current = [x]
        column_bins[bin_id] = [n for n in notes if abs(center_x(n.bbox) - mean(current)) < tol]

    merged_notes = []
    for col_notes in column_bins.values():
        col_notes.sort(key=lambda c: c.bbox["y0"])
        current = []
        current_union = None
        for n in col_notes:
            y0 = n.bbox["y0"]
            header_between = current_union and any(current_union["y1"] < hy0 < y0 for hy0, hy1 in header_y_bands)
            gap = y0 - current_union["y1"] if current_union else 0
            if current and not header_between and Gap < max_gap:
                current.append(n)
                current_union = union_bbox(current_union, n.bbox)
            else:
                if current:
                    merged_notes.append({
                        "page": page,
                        "type": "merged_note",
                        "text": "\n".join(c["text"] for c in current),
                        "bbox": current_union
                    })
                current = [n]
                current_union = n.bbox.copy()
        if current:
            merged_notes.append({
                "page": page,
                "type": "merged_note",
                "text": "\n".join(c["text"] for c in current),
                "bbox": current_union
            })

    final_chunks = [c for c in masked if c.get("page") != page] + headers + merged_notes
    final_path = f"{out_dir}\\final_page3.json"
    with open(final_path, "w", encoding="utf-8") as f:
        json.dump(final_chunks, f, indent=2)
    print(f"[OK] Final merged: {len(merged_notes)} notes")

    print("[5] Visualizing...")
    os.system(f"py tools\\visualize_notes_from_json.py --json {final_path} --pdf {pdf_path} --page 3 --out {out_dir}\\overlay_final.png --dpi 200")

    print("[DONE] Open exports\\MostRecent\\overlay_final.png")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-mask", action="store_true")
    parser.add_argument("--gap", type=float, default=40)
    a = parser.parse_args()
    run_pipeline(mask_legend=not a.no_mask, max_gap=a.gap)