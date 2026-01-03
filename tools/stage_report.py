#!/usr/bin/env python
"""
tools/stage_report.py

Fast sanity checker for any pipeline stage JSON.

Why this exists
---------------
Right now the workflow feels like "it outputs nothing" because PNGs don't tell you:
- Did headers get tagged?
- How many notes exist on this page?
- Did types change between stages?
- What are the actual header strings it detected?

This script prints a compact report to the console and can also write a
Markdown report for your exports folder.

Supports JSON roots:
- list[chunk]
- {"chunks": list[chunk]}

It also understands both `text` and `content`.

Typical use
-----------
py tools/stage_report.py --json exports\\MostRecent\\stage1_headers_tagged.json --page 3 --show-headers
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


# -------------------------
# Helpers: JSON + schema
# -------------------------

def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def get_chunks(root: Any) -> List[Dict[str, Any]]:
    if isinstance(root, list):
        return root
    if isinstance(root, dict) and isinstance(root.get("chunks"), list):
        return root["chunks"]
    raise ValueError("Unsupported JSON root. Expected list or {'chunks':[...]}.")

def get_text(ch: Dict[str, Any]) -> str:
    return (ch.get("text") or ch.get("content") or "").strip()

def get_type(ch: Dict[str, Any]) -> str:
    t = (ch.get("type") or "").strip()
    return t if t else "UNKNOWN"

def get_page(ch: Dict[str, Any]) -> Optional[int]:
    try:
        return int(ch.get("page"))
    except Exception:
        return None

def get_id(ch: Dict[str, Any]) -> str:
    # Best-effort: many of your chunks have either id or global_index or line_id
    for k in ("id", "global_index", "line_id", "chunk_id"):
        if k in ch and ch[k] is not None:
            return str(ch[k])
    return "?"

def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def short(s: str, n: int = 120) -> str:
    s0 = normalize_ws(s)
    return s0 if len(s0) <= n else s0[: n - 1] + "…"


# -------------------------
# Report model
# -------------------------

@dataclass
class StageStats:
    stage_name: str
    page: int
    total_chunks_on_page: int
    type_counts: Counter
    header_type_count: int
    header_candidate_count: int
    note_type_count: int
    examples_by_type: Dict[str, List[Tuple[str, str]]]  # type -> [(id, text)]


def compute_stats(
    chunks: List[Dict[str, Any]],
    page: int,
    stage_name: str,
    examples_per_type: int,
) -> StageStats:
    on_page = [c for c in chunks if get_page(c) == page]
    type_counts = Counter(get_type(c) for c in on_page)

    header_type_count = sum(1 for c in on_page if "header" in get_type(c).lower())
    note_type_count = sum(1 for c in on_page if "note" in get_type(c).lower())

    header_candidate_count = 0
    for c in on_page:
        md = c.get("metadata") or {}
        if md.get("header_candidate") is True:
            header_candidate_count += 1

    # Examples (first N texts by type, in file order)
    ex: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for c in on_page:
        t = get_type(c)
        if len(ex[t]) >= examples_per_type:
            continue
        txt = get_text(c)
        if not txt:
            continue
        ex[t].append((get_id(c), short(txt)))

    return StageStats(
        stage_name=stage_name,
        page=page,
        total_chunks_on_page=len(on_page),
        type_counts=type_counts,
        header_type_count=header_type_count,
        header_candidate_count=header_candidate_count,
        note_type_count=note_type_count,
        examples_by_type=dict(ex),
    )


# -------------------------
# Rendering
# -------------------------

def print_console_report(stats: StageStats, show_headers: bool) -> None:
    print("\n" + "=" * 72)
    print(f"STAGE REPORT: {stats.stage_name}  |  page {stats.page}")
    print("=" * 72)
    print(f"Total chunks on page: {stats.total_chunks_on_page}")
    print(f"Type=header count:    {stats.header_type_count}")
    print(f"metadata.header_candidate count: {stats.header_candidate_count}")
    print(f"Type=note count:      {stats.note_type_count}")
    print("\nType counts:")
    for t, n in stats.type_counts.most_common():
        print(f"  - {t}: {n}")

    if show_headers:
        print("\nHeader examples:")
        # Show both "header" type and header_candidate marked chunks (dedup by id)
        seen = set()
        for t in stats.examples_by_type:
            if "header" not in t.lower():
                continue
            for cid, txt in stats.examples_by_type.get(t, []):
                if cid in seen:
                    continue
                seen.add(cid)
                print(f"  [{cid}] {txt}")

        if not seen and stats.header_candidate_count > 0:
            print("  (No type='header' examples captured, but header_candidate exists.)")
        if not seen and stats.header_candidate_count == 0:
            print("  (None)")

def write_markdown_report(stats: StageStats, out_path: Path, show_headers: bool) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    lines += [f"# Stage report: {stats.stage_name}", ""]
    lines += [f"- Page: **{stats.page}**"]
    lines += [f"- Total chunks on page: **{stats.total_chunks_on_page}**"]
    lines += [f"- Type=header count: **{stats.header_type_count}**"]
    lines += [f"- metadata.header_candidate count: **{stats.header_candidate_count}**"]
    lines += [f"- Type=note count: **{stats.note_type_count}**", ""]
    lines += ["## Type counts", ""]
    for t, n in stats.type_counts.most_common():
        lines.append(f"- `{t}`: {n}")
    lines.append("")

    lines += ["## Examples by type", ""]
    for t, ex_list in sorted(stats.examples_by_type.items(), key=lambda kv: kv[0].lower()):
        lines.append(f"### {t}")
        if not ex_list:
            lines.append("- (none)")
        else:
            for cid, txt in ex_list:
                lines.append(f"- `[{cid}]` {txt}")
        lines.append("")

    if show_headers:
        lines += ["## Header examples", ""]
        headers = []
        for t, ex_list in stats.examples_by_type.items():
            if "header" in t.lower():
                headers.extend(ex_list)
        if not headers and stats.header_candidate_count == 0:
            lines.append("- (none detected)")
        else:
            for cid, txt in headers:
                lines.append(f"- `[{cid}]` {txt}")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] Wrote markdown: {out_path}")


# -------------------------
# CLI
# -------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stage sanity report for a page.")
    p.add_argument("--json", required=True, help="Stage JSON file to inspect")
    p.add_argument("--page", type=int, required=True, help="1-based page number")
    p.add_argument("--stage-name", default="", help="Optional label (defaults to filename)")
    p.add_argument("--examples-per-type", type=int, default=5, help="How many examples to show per type")
    p.add_argument("--show-headers", action="store_true", help="Also print header examples section")
    p.add_argument("--write-md", default="", help="Write markdown report to this path")
    p.add_argument("--fail-if-zero-headers", action="store_true",
                   help="Exit with code 2 if no headers detected (type=header OR header_candidate)")
    return p.parse_args()


def main() -> None:
    a = parse_args()
    json_path = Path(a.json)

    root = load_json(json_path)
    chunks = get_chunks(root)

    stage_name = a.stage_name.strip() or json_path.name
    stats = compute_stats(
        chunks=chunks,
        page=a.page,
        stage_name=stage_name,
        examples_per_type=a.examples_per_type,
    )

    print_console_report(stats, show_headers=a.show_headers)

    if a.write_md.strip():
        write_markdown_report(stats, Path(a.write_md), show_headers=a.show_headers)

    # Fail-fast sanity check (super useful in runners/CI)
    headers_detected = (stats.header_type_count > 0) or (stats.header_candidate_count > 0)
    if a.fail_if_zero_headers and not headers_detected:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
