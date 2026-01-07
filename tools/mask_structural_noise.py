# mask_structural_noise.py - REMOVE LEGEND/TITLEBLOCK BEFORE NOTE MERGING
# Full new file - copy-paste entire contents
# Simple bbox-based masking (legend usually right side, titleblock bottom/right)

import json
import argparse
import os

def load_json(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "chunks" in data:
        return data["chunks"]
    return data

def save_json(chunks: List[Dict[str, Any]], path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(chunks, f, indent=2, ensure_ascii=False)
    os.replace(temp, path)
    print(f"[OK] Masked JSON saved: {path} ({len(chunks)} chunks remaining)")

def mask_noise(chunks: List[Dict[str, Any]], page: int) -> List[Dict[str, Any]]:
    page_chunks = [c for c in chunks if c.get("page") == page]
    other_chunks = [c for c in chunks if c.get("page") != page]
    
    # Simple heuristic: remove chunks with x0 > 0.6 * page width (legend) or y0 > 0.8 * page height (titleblock)
    # Assume page bbox is roughly 0-612 x 0-792 (PDF points)
    kept = []
    removed = 0
    for c in page_chunks:
        b = c["bbox"]
        center_x = (b["x0"] + b["x1"]) / 2
        center_y = (b["y0"] + b["y1"]) / 2
        if center_x > 400 or center_y > 600:  # Tune these thresholds for your PDF
            removed += 1
            c["type"] = "masked_noise"  # Mark instead of delete for debugging
            c["metadata"]["masked_reason"] = "legend_or_titleblock"
        kept.append(c)
    
    print(f"[INFO] Masked {removed} noise chunks on page {page}")
    return other_chunks + kept

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--page", type=int, required=True)
    a = parser.parse_args()

    chunks = load_json(a.input)
    masked = mask_noise(chunks, a.page)
    save_json(masked, a.output)

if __name__ == "__main__":
    main()