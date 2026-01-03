# tools/build_final_json.py
"""
Build final.json by merging:
- stitched notes chunks (usually only the target page)
- header chunks from the headers stage (stage2 or stage2b)

This prevents "missing header" cases where headers don't survive note merging.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(p: Path, obj: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headers", required=True, help="stage2_headers_split.json or stage2b_headers_split_tight.json")
    ap.add_argument("--notes", required=True, help="stage4_notes_stitched.json (notes output)")
    ap.add_argument("--output", required=True, help="final.json path")
    ap.add_argument("--page", type=int, required=True)
    args = ap.parse_args()

    headers_path = Path(args.headers)
    notes_path = Path(args.notes)
    out_path = Path(args.output)
    page = args.page

    headers = load_json(headers_path)
    notes = load_json(notes_path)

    # notes file is usually already page-filtered (your current stage4 is)
    note_chunks = notes.get("chunks", [])
    note_ids = {c.get("id") for c in note_chunks if c.get("id")}

    header_chunks = []
    for c in headers.get("chunks", []):
        if c.get("page") != page:
            continue
        if c.get("type") != "header":
            continue
        cid = c.get("id")
        if cid and cid in note_ids:
            continue
        header_chunks.append(c)

    # final prefers notes meta (stage4 tends to be minimal + page scoped)
    final_obj = dict(notes)
    final_obj["chunks"] = header_chunks + note_chunks

    write_json(out_path, final_obj)
    print(f"[OK] final.json built: {out_path} (headers added: {len(header_chunks)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
