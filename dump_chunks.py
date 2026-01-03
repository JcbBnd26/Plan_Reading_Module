import os
from backbone.chunking import Chunker

# Name of the PDF you want to process.
# Make sure this file is in the SAME folder as this script.
PDF_NAME = "test.pdf"  # <-- change this if your file has a different name

# Folder where all the chunk text files will be saved
OUTPUT_DIR = "chunk_output"

def main():
    # Make sure the output folder exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Initialize the chunker
    c = Chunker()

    print(f"Processing PDF: {PDF_NAME}")
    results = c.process(PDF_NAME)
    print(f"Total chunks: {len(results)}")

    for chunk in results:
        # Build a readable file name for each chunk
        filename = f"page_{chunk.page_number}_chunk_{chunk.id[:8]}.txt"
        path = os.path.join(OUTPUT_DIR, filename)

        # Write chunk data to a text file
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"ID: {chunk.id}\n")
            f.write(f"Page: {chunk.page_number}\n")
            f.write(f"BBox: {chunk.bbox}\n")
            f.write(f"Type: {chunk.type}\n")
            f.write("\n")
            f.write(chunk.content)

    print(f"Done. Chunks written to folder: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
