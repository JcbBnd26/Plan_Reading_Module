#!/usr/bin/env python
"""
tools/tag_header_candidates.py

Tags OCR chunks that look like section headers (e.g., "SITE UTILITY NOTES:")
by setting:

  chunk["type"] = "header"          (for immediate visibility + downstream logic)
  chunk["metadata"]["header_candidate"] = True
  chunk["metadata"]["header_norm"] = normalized header string
  chunk["metadata"]["is_continuation"] = True/False

Why this exists
---------------
Your pipeline needs a reliable way to separate:
- headers (section titles)
- notes (paragraph content)

Bug fixed in this version
-------------------------
The previous regex rejected headers that end with ":" because ":" was not
allowed in the header character whitelist.

Your drawings use colons heavily ("... NOTES:"), so the tagger was tagging
*zero* headers, making overlays look "not working".
"""

from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any, Dict


# Core signals
NOTES_RE = re.compile(r"\bNOTES\b", re.IGNORECASE)
BAD_CONTEXT_RE = re.compile(r"\b(SEE|REFER TO)\b", re.IGNORECASE)
CONT_RE = re.compile(r"\bCONT(?:'D|INUED|\.|’D)?\b", re.IGNORECASE)

# Allow common header characters (FIX: include ":" and unicode apostrophe ’)
# Also allow periods/commas/parentheses/dashes which appear in your headers.
HEADER_SHAPE_RE = re.compile(r"^[A-Z0-9\s/&'’\-(),.:]+$")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--page", type=int, required=True)
    p.add_argument("--debug", action="store_true")
    return p.parse_args()


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[OK] Wrote: {path}")


def get_chunks(root: Any):
    if isinstance(root, dict) and isinstance(root.get("chunks"), list):
        return root["chunks"]
    if isinstance(root, list):
        return root
    raise ValueError("Unsupported JSON format. Expected list or {chunks:[...]}.")


def get_text(ch: Dict[str, Any]) -> str:
    return (ch.get("text") or ch.get("content") or "").strip()


def normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def uppercase_ratio(s: str) -> float:
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def header_norm(s: str) -> str:
    """
    Normalize header text for matching:
    - collapse whitespace
    - strip trailing ":" and spaces
    - strip common continuation markers
    """
    s0 = normalize_spaces(s)
    s0 = s0.rstrip(" :")
    s0 = re.sub(r"\s*\(\s*CONT(?:'D|INUED|\.|’D)?\s*\)\s*$", "", s0, flags=re.IGNORECASE)
    s0 = normalize_spaces(s0)
    return s0.upper()


def is_header_candidate(text: str) -> bool:
    s0 = normalize_spaces(text)
    if not s0:
        return False

    # Must contain NOTES
    if not NOTES_RE.search(s0):
        return False

    # Avoid "SEE / REFER TO" lines (these are usually not headers)
    if BAD_CONTEXT_RE.search(s0) and not CONT_RE.search(s0):
        return False

    # Reject obvious sentence-like "(SEE ... NOTES)." patterns
    if s0.endswith(".") and "(" in s0 and not CONT_RE.search(s0):
        return False

    # Headers are almost always mostly uppercase on your sheets
    if uppercase_ratio(s0) < 0.80:
        return False

    # Word count sanity (prevents grabbing paragraphs)
    wc = len(s0.split())
    if wc < 2 or wc > 14:
        return False

    # Character whitelist sanity:
    # allow trailing ":" by checking after stripping it
    shape_check = s0.rstrip(" :")
    if not HEADER_SHAPE_RE.match(shape_check.upper()):
        return False

    return True


def main() -> None:
    a = parse_args()

    root = load_json(a.input)
    chunks = get_chunks(root)

    tagged = 0
    for ch in chunks:
        try:
            if int(ch.get("page", 0)) != a.page:
                continue
        except Exception:
            continue

        txt = get_text(ch)
        if not is_header_candidate(txt):
            continue

        # Preserve prior type for debugging
        meta = dict(ch.get("metadata") or {})
        if "prev_type" not in meta:
            meta["prev_type"] = ch.get("type")

        meta["header_candidate"] = True
        meta["header_norm"] = header_norm(txt)
        meta["is_continuation"] = bool(CONT_RE.search(txt))

        ch["metadata"] = meta

        # Make it visible + consistent downstream
        ch["type"] = "header"

        tagged += 1
        if a.debug:
            print("[HDR]", meta["header_norm"])

    print(f"[INFO] Tagged {tagged} header candidates on page {a.page}.")
    save_json(a.output, root)


if __name__ == "__main__":
    main()
