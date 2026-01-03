# structural_extractor.py
import fitz
from typing import List
import re
from .chunk import Chunk

BULLET_RE = re.compile(
    r"""^(
        \d+\.\s* |
        \d+\)\s* |
        [A-Z]\.\s* |
        [A-Z]\)\s* |
        \(\d+\)\s* |
        \([A-Za-z]\)\s*
    )""",
    re.VERBOSE
)

class StructuralExtractor:
    def extract(self, pdf_path: str) -> List[Chunk]:
        print(">>> USING LINE-LEVEL EXTRACTOR <<<")

        doc = fitz.open(pdf_path)
        out = []

        for pnum, page in enumerate(doc, start=1):
            raw = page.get_text("rawdict")
            if "blocks" not in raw:
                continue

            for block in raw["blocks"]:
                if block.get("type", None) != 0:
                    continue

                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    txt_parts = []

                    for s in spans:
                        if "text" in s:
                            txt_parts.append(s["text"])
                        elif "chars" in s:
                            txt_parts.append("".join(c["c"] for c in s["chars"]))

                    text = "".join(txt_parts).strip()
                    if not text:
                        continue

                    # --- CRITICAL FIX: keep bullets intact ---
                    # DO NOT SPLIT ANYTHING HERE.
                    # Semantic grouper will split/merge later.

                    x0, y0, x1, y1 = line["bbox"]

                    out.append(
                        Chunk(
                            type="text_line",
                            content=text,
                            page=pnum,
                            bbox=(x0, y0, x1, y1),
                        )
                    )

        return out
