# visual_to_text_fusion.py
from typing import Dict, List
import fitz  # PyMuPDF

def extract_text_for_bbox(pdf_path: str, bbox, page_number: int) -> str:
    doc = fitz.open(pdf_path)
    page = doc.load_page(page_number-1)
    rect = fitz.Rect(*bbox)
    return page.get_textbox(rect)

def fuse_visual_and_text(schema: Dict, pdf_path: str) -> List[Dict]:
    result = []
    for note in schema.get("page_structure", {}).get("notes", []):
        bbox = note.get("bbox")
        page = note.get("page_number", 1)
        text = extract_text_for_bbox(pdf_path, bbox, page) if bbox else ""
        merged = {"bbox": bbox, "page": page, "text": text}
        result.append(merged)
    return result
