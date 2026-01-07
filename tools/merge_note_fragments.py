# merge_note_fragments.py - REAL V6 FIX (ChatGPT-Inspired + Engineered)
# Column-isolated merging: no interleaving
# Headers as hard horizontal bands
# Preserves ALL chunks on page
# Rich persisted merge diagnostics in metadata
# Full file replacement - copy-paste entire contents

import json
import argparse
import os
from typing import List, Dict, Any, Tuple
from statistics import mean, stdev

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
    print(f"[OK] Merged notes saved: {path} ({len(chunks)} total chunks)")

def get_center_x(bbox: Dict) -> float:
    return (bbox["x0"] + bbox["x1"]) / 2

def union_bbox(bboxes: List[Dict]) -> Dict:
    if not bboxes:
        return {"x0": 0, "y0": 0, "x1": 0, "y1": 0}
    return {
        "x0": min(b["x0"] for b in bboxes),
        "y0": min(b["y0"] for b in bboxes),
        "x1": max(b["x1"] for b in bboxes),
        "y1": max(b["y1"] for b in bboxes)
    }

def assign_column_bins(notes: List[Dict[str, Any]], tolerance: float = 80.0) -> Dict[int, List[Dict[str, Any]]]:
    if not notes:
        return {}
    centers = sorted(get_center_x(c["bbox"]) for c in notes)
    bins = {}
    bin_id = 0
    current = [centers[0]]
    for x in centers[1:]:
        if x - mean(current) < tolerance:
            current.append(x)
        else:
            bins[bin_id] = [n for n in notes if abs(get_center_x(n["bbox"]) - mean(current)) < tolerance + stdev(current or [0]) * 2]
            bin_id += 1
            current = [x]
    bins[bin_id] = [n for n in notes if abs(get_center_x(n["bbox"]) - mean(current)) < tolerance + stdev(current or [0]) * 2]
    return bins

def merge_in_column(column_notes: List[Dict[str, Any]], headers: List[Dict[str, Any]], page: int, max_gap: float, debug: bool) -> List[Dict[str, Any]]:
    # Sort column notes top-to-bottom
    column_notes.sort(key=lambda c: c["bbox"]["y0"])
    
    header_bands = sorted([(h["bbox"]["y0"], h["bbox"]["y1"]) for h in headers], key=lambda b: b[0])
    
    merged = []
    current_group = []
    current_union = None
    
    def end_group(reason: str):
        nonlocal current_group, current_union
        if current_group:
            merged_note = {
                "page": page,
                "type": "merged_note",
                "text": "\n".join(c["text"] for c in current_group),
                "bbox": current_union,
                "metadata": {
                    "source_lines": len(current_group),
                    "merge_diagnostics": {
                        "reason_ended": reason,
                        "line_count": len(current_group),
                        "vertical_span": current_union["y1"] - current_union["y0"]
                    }
                }
            }
            merged.append(merged_note)
            if debug:
                print(f"[DEBUG] Ended group ({reason}): {len(current_group)} lines -> '{merged_note['text'][:60].replace('\n', ' ')}...'")
            current_group = []
            current_union = None

    for note in column_notes:
        bbox = note["bbox"]
        y0, y1 = bbox["y0"], bbox["y1"]
        
        # Check if a header band is between current group and this note
        header_between = False
        if current_union:
            group_bottom = current_union["y1"]
            for h_y0, h_y1 in header_bands:
                if group_bottom < h_y0 < y0 or (group_bottom < h_y1 and h_y1 < y0):
                    header_between = True
                    break
        
        gap = y0 - (current_union["y1"] if current_union else 0) if current_group else 0
        
        if current_group and not header_between and gap < max_gap:
            # Continue group
            current_group.append(note)
            current_union = union_bbox(current_union, bbox)
            if debug:
                print(f"[DEBUG] Continued group (gap {gap:.1f})")
        else:
            # End current, start new
            end_group("header_between" if header_between else f"gap_too_large_{gap:.1f}" if current_group else "first_line")
            current_group = [note]
            current_union = bbox.copy()

    end_group("end_of_column")
    return merged

def merge_note_fragments(chunks: List[Dict[str, Any]], page: int, max_gap: float = 28, debug: bool = False) -> List[Dict[str, Any]]:
    page_chunks = [c for c in chunks if c.get("page") == page]
    other_chunks = [c for c in chunks if c.get("page") != page]
    
    headers = [c for c in page_chunks if "header" in c.get("type", "")]
    notes = [c for c in page_chunks if "header" not in c.get("type", "") and c.get("type") in ("text_line", "note")]
    non_notes = [c for c in page_chunks if c not in headers and c not in notes]
    
    if debug:
        print(f"[DEBUG] Page {page}: {len(headers)} headers, {len(notes)} note lines, {len(non_notes)} others")
    
    column_bins = assign_column_bins(notes)
    if debug:
        print(f"[DEBUG] Detected {len(column_bins)} columns")
    
    all_merged = list(headers) + list(non_notes)  # Preserve headers and others unchanged
    
    for bin_id, col_notes in column_bins.items():
        if debug:
            print(f"[DEBUG] Processing column {bin_id} with {len(col_notes)} lines")
        merged_in_col = merge_in_column(col_notes, headers, page, max_gap, debug)
        all_merged.extend(merged_in_col)
    
    # Sort final page chunks top-to-bottom, then left-to-right
    all_merged.sort(key=lambda c: (c["bbox"]["y0"], get_center_x(c["bbox"])))
    
    result = other_chunks + all_merged
    print(f"[INFO] Page {page}: Produced {len([c for c in all_merged if c.get('type') == 'merged_note'])} merged notes")
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--page", type=int, required=True)
    parser.add_argument("--max-gap", type=float, default=28)
    parser.add_argument("--debug", action="store_true")
    a = parser.parse_args()

    chunks = load_json(a.input)
    merged_chunks = merge_note_fragments(chunks, a.page, a.max_gap, a.debug)
    save_json(merged_chunks, a.output)

if __name__ == "__main__":
    main()