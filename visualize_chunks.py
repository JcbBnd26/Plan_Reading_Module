import os
import fitz  # PyMuPDF
from PIL import Image, ImageDraw
from backbone.chunking import Chunker

PDF_NAME = "test.pdf"
OUTPUT_DIR = "chunk_visuals"
DPI = 150


def visualize_pdf_chunks():
    print(">>> Starting visualizer...")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f">>> Output folder ready: {OUTPUT_DIR}")

    # Run chunker (now should produce merged notes!)
    chunker = Chunker()
    chunks = chunker.process(PDF_NAME)
    print(f">>> Total chunks returned: {len(chunks)}")

    # Debug dump of first few
    print("\n>>> DEBUG: FIRST 20 CHUNKS VISUALIZER IS USING:")
    for c in chunks[:20]:
        print(
            f"   TYPE={c.type:<12} PAGE={c.page_number:<3} "
            f"COL={c.metadata.get('column','?')} | "
            f"{c.content[:80].replace(chr(10),' ')}"
        )
    print(">>> END DEBUG\n")

    # Group chunks by page
    pages = {}
    for chunk in chunks:
        pages.setdefault(chunk.page_number, []).append(chunk)

    doc = fitz.open(PDF_NAME)
    zoom = DPI / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    for page_number, page in enumerate(doc, start=1):
        print(f">>> Rendering page {page_number}")

        pix = page.get_pixmap(matrix=matrix)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        draw = ImageDraw.Draw(img)

        for chunk in pages.get(page_number, []):
            x1, y1, x2, y2 = chunk.bbox

            # scale to rendered DPI
            x1 *= zoom
            y1 *= zoom
            x2 *= zoom
            y2 *= zoom

            # draw bounding box
            draw.rectangle([x1, y1, x2, y2], outline="red", width=3)

            # label
            label = chunk.content[:20].replace("\n", " ")
            try:
                draw.text((x1 + 4, y1 + 4), label, fill="red")
            except:
                pass

        out = os.path.join(OUTPUT_DIR, f"page_{page_number}.png")
        img.save(out)
        print(f">>> Saved: {out}")

    print("\n>>> DONE. Visuals created.\n")


if __name__ == "__main__":
    visualize_pdf_chunks()
