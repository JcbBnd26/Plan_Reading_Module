# split_banner_headers.py - FIXED FOR MODERN FLAT LIST JSON FORMAT
# Full file replacement - copy-paste entire contents
# Handles both old dict {"chunks": [...]} and new flat list format
# Adds better debug, atomic write, and skips if no banners

import json
import argparse
import os
from typing import List, Dict, Any, Tuple, Optional

def load_json(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Handle both formats: flat list or {"chunks": [...]}
    if isinstance(data, dict) and "chunks" in data:
        print(f"[INFO] Loaded legacy format from {path} (using 'chunks' key)")
        return data["chunks"]
    elif isinstance(data, list):
        print(f"[INFO] Loaded modern flat list format from {path}")
        return data
    else:
        raise ValueError("Unexpected JSON structure")

def save_json(chunks: List[Dict[str, Any]], path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(chunks, f, indent=2, ensure_ascii=False)
    os.replace(temp, path)
    print(f"[OK] Wrote: {path}")

def split_banner_headers(
    chunks: List[Dict[str, Any]],
    page: int,
    x_tol: float = 20.0,
    split_gap: float = 50.0,
    edge_inset: float = 30.0,
    min_banner_width: float = 400.0,
    debug: bool = False
) -> Tuple[List[Dict[str, Any]], int]:
    
    page_chunks = [c for c in chunks if c.get("page") == page]
    header_candidates = [c for c in page_chunks if c.get("type") == "header_candidate" or "header" in c.get("type", "")]
    
    if not header_candidates:
        if debug:
            print(f"[DEBUG] No header candidates on page {page} - nothing to split")
        return chunks, 0

    new_chunks = [c for c in chunks if c.get("page") != page]
    split_count = 0

    for hc in header_candidates:
        bbox = hc["bbox"]
        x0, y0, x1, y1 = bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"]
        width = x1 - x0
        center_y = (y0 + y1) / 2

        if width < min_banner_width:
            if debug:
                print(f"[DEBUG] Header too narrow ({width:.1f} < {min_banner_width}) - skipping")
            new_chunks.append(hc)
            continue

        # Find note x-centers below this header to infer column lanes
        notes_below = [c for c in page_chunks 
                       if c.get("type") in ("text_line", "note", "merged_note") 
                       and c["bbox"]["y0"] > y1 
                       and abs(c["bbox"]["y0"] - y1) < 100]  # within reasonable distance
        
        x_centers = sorted([(c["bbox"]["x0"] + c["bbox"]["x1"]) / 2 for c in notes_below])
        if len(x_centers) < 2:
            if debug:
                print(f"[DEBUG] Not enough notes below to infer columns - keeping as one")
            new_chunks.append(hc)
            continue

        # Cluster x-centers to find column centers
        from statistics import mean
        clusters = []
        current = [x_centers[0]]
        for x in x_centers[1:]:
            if x - mean(current) < x_tol:
                current.append(x)
            else:
                clusters.append(mean(current))
                current = [x]
        clusters.append(mean(current))

        if debug:
            print(f"[DEBUG] Banner header width {width:.1f}, inferred {len(clusters)} columns at x ≈ {clusters}")

        # Split the banner into one header per column
        text = hc["text"]
        words = text.split()
        per_column_text = " ".join(words[i::len(clusters)])  # naive split - better than nothing

        for i, col_x in enumerate(clusters):
            left = max(x0 + edge_inset, col_x - 150)  # rough column width guess
            right = min(x1 - edge_inset, col_x + 150)
            split_hc = hc.copy()
            split_hc["bbox"] = {
                "x0": left,
                "y0": y0,
                "x1": right,
                "y1": y1
            }
            split_hc["text"] = text  # keep full text for now - semantics later
            split_hc["metadata"] = split_hc.get("metadata", {})
            split_hc["metadata"]["split_from_banner"] = True
            split_hc["metadata"]["original_center_x"] = (x0 + x1) / 2
            new_chunks.append(split_hc)
            split_count += 1

        if debug and split_count > 0:
            print(f"[DEBUG] Split 1 banner into {len(clusters)} headers")

    new_chunks.sort(key=lambda c: (c.get("page", 0), c["bbox"]["y0"]))
    return new_chunks, split_count

def main():
    parser = argparse.ArgumentParser(description="Split wide banner headers into per-column headers")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--page", type=int, required=True)
    parser.add_argument("--x-tol", type=float, default=20.0)
    parser.add_argument("--split-gap", type=float, default=50.0)
    parser.add_argument("--edge-inset", type=float, default=30.0)
    parser.add_argument("--min-banner-width", type=float, default=400.0)
    parser.add_argument("--debug", action="store_true")
    a = parser.parse_args()

    chunks = load_json(a.input)
    new_chunks, split_n = split_banner_headers(
        chunks=chunks,
        page=a.page,
        x_tol=a.x_tol,
        split_gap=a.split_gap,
        edge_inset=a.edge_inset,
        min_banner_width=a.min_banner_width,
        debug=a.debug
    )

    print(f"[INFO] Split {split_n} banner headers on page {a.page}.")
    save_json(new_chunks, a.output)

if __name__ == "__main__":
    main()