# ------------------------------------------------------------
# note_viewer.py  (FULL FILE)
#
# Shows merged notes on the PDF page with clean red boxes.
# This allows you to visually verify correct grouping.
# ------------------------------------------------------------

import os
import fitz  # PyMuPDF
from PIL import Image, ImageDraw
from backbone.chunking import Chunker

PDF_NAME = "test.pdf"
OUTPUT_DIR = "note_visuals"
DPI = 150


def draw_note_boxes():
    print(">>> Starting note viewer...")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f">>> Output folder ready: {OUTPUT_DIR}")

    # Run chunker → this gives you GROUPED NOTES now
    chunker = Chunker()
    notes = chunker.process(PDF_NAME)

    print(f">>> Total merged notes: {len(notes)}")

    # Organize by page
    pages = {}
    for note in notes:
        pages.setdefault(note.page_number, []).append(note)

    doc = fitz.open(PDF_NAME)

    zoom = DPI / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    for page_number, page in enumerate(doc, start=1):
        print(f">>> Rendering page {page_number}")

        # Render PDF page
        pix = page.get_pixmap(matrix=matrix)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        draw = ImageDraw.Draw(img)

        # Get notes for this page
        page_notes = pages.get(page_number, [])

        for note in page_notes:
            x1, y1, x2, y2 = note.bbox

            # Scale to rendered DPI
            x1 *= zoom
            y1 *= zoom
            x2 *= zoom
            y2 *= zoom

            # Draw red box around whole note
            draw.rectangle([x1, y1, x2, y2], outline="red", width=3)

            # Label with first few words so you know which note it is
            label = note.content[:40].replace("\n", " ")

            try:
                draw.text((x1 + 4, y1 + 4), label, fill="red")
            except:
                pass

        out = os.path.join(OUTPUT_DIR, f"page_{page_number}.png")
        img.save(out)
        print(f">>> Saved: {out}")

    print(">>> DONE. Note viewer complete.")


if __name__ == "__main__":
    draw_note_boxes()
