#!/usr/bin/env python
"""
tools/run_page_pipeline.py

One-command runner that produces *real* outputs, not just debug PNG spam.

Outputs (exports/MostRecent by default)
--------------------------------------
- stage0_base.json
- stage1_headers_tagged.json
- stage2_headers_split.json
- stage3_notes_merged.json
- stage4_notes_stitched.json
- overlay_stage0.png ... overlay_stage4.png
- overlay_final.png              (alias of last stage overlay)
- montage.png                    (all stages in one image)
- summary.md                     (counts by type for the target page per stage)
- manifest.json                  (paths + parameters used)

This runner also rotates exports by calling tools/prepare_exports_run.py (unless disabled).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ----------------------------
# Process helpers
# ----------------------------

def run_cmd(args: List[str], cwd: Path) -> None:
    """Run a command; raise on failure."""
    print(f"[cmd] {' '.join(args)}")
    r = subprocess.run(args, cwd=str(cwd))
    if r.returncode != 0:
        raise SystemExit(f"[ERROR] Command failed ({r.returncode}): {' '.join(args)}")


# ----------------------------
# JSON helpers
# ----------------------------

def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def get_chunks(root):
    if isinstance(root, list):
        return root
    if isinstance(root, dict) and isinstance(root.get("chunks"), list):
        return root["chunks"]
    return []

def count_types_for_page(json_path: Path, page: int) -> Dict[str, int]:
    root = load_json(json_path)
    chunks = get_chunks(root)
    out: Dict[str, int] = {}
    for ch in chunks:
        try:
            if int(ch.get("page", 0)) != page:
                continue
        except Exception:
            continue
        t = (ch.get("type") or "UNKNOWN").strip() or "UNKNOWN"
        out[t] = out.get(t, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


# ----------------------------
# Overlay + montage helpers
# ----------------------------

def make_overlay(repo_root: Path, pdf_path: Path, json_path: Path, page: int, out_png: Path, dpi: int) -> None:
    viz = repo_root / "tools" / "visualize_notes_from_json.py"
    if not viz.exists():
        print(f"[WARN] Missing visualizer, overlay skipped: {viz}")
        return

    run_cmd(
        [
            sys.executable, str(viz),
            "--pdf", str(pdf_path),
            "--json", str(json_path),
            "--page", str(page),
            "--out", str(out_png),
            "--dpi", str(dpi),
            "--scheme", "type",
        ],
        cwd=repo_root,
    )

def try_make_montage(png_paths: List[Path], out_path: Path) -> bool:
    """
    Make a simple vertical montage: stage0..stage4 stacked.
    Returns True if montage produced, False otherwise.
    """
    try:
        from PIL import Image  # type: ignore
    except Exception:
        print("[WARN] Pillow not installed; montage skipped.")
        return False

    imgs = []
    for p in png_paths:
        if p.exists():
            imgs.append(Image.open(p).convert("RGBA"))

    if not imgs:
        return False

    # Normalize widths to max width
    max_w = max(im.size[0] for im in imgs)
    resized = []
    for im in imgs:
        w, h = im.size
        if w == max_w:
            resized.append(im)
        else:
            new_h = int(h * (max_w / w))
            resized.append(im.resize((max_w, new_h)))

    total_h = sum(im.size[1] for im in resized)
    canvas = Image.new("RGBA", (max_w, total_h), (255, 255, 255, 255))

    y = 0
    for im in resized:
        canvas.paste(im, (0, y))
        y += im.size[1]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path)
    return True


# ----------------------------
# CLI
# ----------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run header tag/split/merge pipeline for one page + emit canonical outputs.")
    p.add_argument("--pdf", default="test.pdf", help="Input PDF (default: test.pdf)")
    p.add_argument("--base-json", default="data/structural_masks/all_pages_notes_sheetwide_no_legend.json",
                   help="Base notes JSON (default: structurally masked no-legend JSON)")
    p.add_argument("--page", type=int, default=3, help="1-based page number (default: 3)")

    p.add_argument("--out-dir", default="exports/MostRecent", help="Output directory (default: exports/MostRecent)")
    p.add_argument("--dpi", type=int, default=200, help="Overlay DPI (default: 200)")

    p.add_argument("--no-rotate-exports", action="store_true",
                   help="Do not call tools/prepare_exports_run.py before writing outputs")
    p.add_argument("--no-overlays", action="store_true", help="Skip overlay PNG generation")

    # Stage toggles
    p.add_argument("--skip-headers", action="store_true")
    p.add_argument("--skip-split", action="store_true")
    p.add_argument("--skip-merge", action="store_true")
    p.add_argument("--skip-stitch", action="store_true")

    # Tool params (match existing tool CLIs)
    p.add_argument("--split-x-tol", type=float, default=140.0)
    p.add_argument("--merge-max-gap", type=float, default=34.0)
    p.add_argument("--merge-min-overlap", type=float, default=0.28)
    p.add_argument("--merge-x-bin-tol", type=float, default=140.0)
    p.add_argument("--merge-x-shift-hard", type=float, default=150.0)

    # stitch tool uses --only-page, not --page
    p.add_argument("--stitch-max-gap", type=float, default=28.0)
    p.add_argument("--stitch-min-overlap", type=float, default=0.60)
    p.add_argument("--stitch-x0-tol", type=float, default=100.0)
    return p.parse_args()


# ----------------------------
# Main
# ----------------------------

def main() -> None:
    a = parse_args()
    repo_root = Path(__file__).resolve().parents[1]

    pdf_path = (repo_root / a.pdf).resolve()
    base_json = (repo_root / a.base_json).resolve()
    out_dir = (repo_root / a.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not pdf_path.exists():
        raise SystemExit(f"[ERROR] PDF not found: {pdf_path}")
    if not base_json.exists():
        raise SystemExit(f"[ERROR] Base JSON not found: {base_json}")

    # Rotate exports so MostRecent is always "this run"
    if not a.no_rotate_exports:
        rotator = repo_root / "tools" / "prepare_exports_run.py"
        if rotator.exists():
            run_cmd([sys.executable, str(rotator)], cwd=repo_root)
        else:
            print(f"[WARN] Missing rotator, skipping: {rotator}")

    # Canonical stage paths (stable names)
    s0 = out_dir / "stage0_base.json"
    s1 = out_dir / "stage1_headers_tagged.json"
    s2 = out_dir / "stage2_headers_split.json"
    s3 = out_dir / "stage3_notes_merged.json"
    s4 = out_dir / "stage4_notes_stitched.json"

    # Write stage0 as a frozen copy
    s0.write_bytes(base_json.read_bytes())
    print(f"[OK] stage0 written: {s0}")

    cur = s0

    # stage1: tag headers
    if not a.skip_headers:
        tool = repo_root / "tools" / "tag_header_candidates.py"
        run_cmd([sys.executable, str(tool), "--input", str(cur), "--output", str(s1), "--page", str(a.page)], cwd=repo_root)
        cur = s1
    else:
        print("[SKIP] headers tagger")

    # stage2: split banners
    if not a.skip_split:
        tool = repo_root / "tools" / "split_banner_headers.py"
        run_cmd([sys.executable, str(tool), "--input", str(cur), "--output", str(s2), "--page", str(a.page), "--x-tol", str(a.split_x_tol)], cwd=repo_root)
        cur = s2
    else:
        print("[SKIP] header splitter")

    # stage3: merge fragments
    if not a.skip_merge:
        tool = repo_root / "tools" / "merge_note_fragments.py"
        run_cmd(
            [
                sys.executable, str(tool),
                "--input", str(cur),
                "--output", str(s3),
                "--page", str(a.page),
                "--max-gap", str(a.merge_max_gap),
                "--min-overlap", str(a.merge_min_overlap),
                "--x-bin-tol", str(a.merge_x_bin_tol),
                "--x-shift-hard", str(a.merge_x_shift_hard),
            ],
            cwd=repo_root,
        )
        cur = s3
    else:
        print("[SKIP] note merger")

    # stage4: stitch safety net
    if not a.skip_stitch:
        tool = repo_root / "tools" / "fix_split_notes_postmerge.py"
        run_cmd(
            [
                sys.executable, str(tool),
                "--input", str(cur),
                "--output", str(s4),
                "--only-page", str(a.page),
                "--max-gap", str(a.stitch_max_gap),
                "--min-overlap", str(a.stitch_min_overlap),
                "--x0-tolerance", str(a.stitch_x0_tol),
            ],
            cwd=repo_root,
        )
        cur = s4
    else:
        print("[SKIP] stitcher")

    # Overlays (stage0..stage4 + final alias)
    overlays: List[Tuple[Path, Path]] = [
        (s0, out_dir / "overlay_stage0.png"),
        (s1, out_dir / "overlay_stage1.png"),
        (s2, out_dir / "overlay_stage2.png"),
        (s3, out_dir / "overlay_stage3.png"),
        (s4, out_dir / "overlay_stage4.png"),
    ]

    if not a.no_overlays:
        for js, png in overlays:
            if js.exists():
                make_overlay(repo_root, pdf_path, js, a.page, png, a.dpi)

        # Copy/alias final overlay
        final_overlay = out_dir / "overlay_final.png"
        last_png = overlays[-1][1]
        if last_png.exists():
            final_overlay.write_bytes(last_png.read_bytes())

        # Montage (single “at-a-glance” image)
        montage_out = out_dir / "montage.png"
        try_make_montage([p for _, p in overlays if p.exists()], montage_out)

    # Summary + manifest (this is the “real output” you were missing)
    stage_counts = {
        "stage0": count_types_for_page(s0, a.page) if s0.exists() else {},
        "stage1": count_types_for_page(s1, a.page) if s1.exists() else {},
        "stage2": count_types_for_page(s2, a.page) if s2.exists() else {},
        "stage3": count_types_for_page(s3, a.page) if s3.exists() else {},
        "stage4": count_types_for_page(s4, a.page) if s4.exists() else {},
    }

    summary_md = out_dir / "summary.md"
    lines = [
        f"# Page {a.page} pipeline summary",
        "",
        f"- PDF: `{pdf_path.name}`",
        f"- Base JSON: `{base_json}`",
        f"- Output dir: `{out_dir}`",
        "",
        "## Counts by type (this page only)",
        "",
    ]
    for k in ["stage0", "stage1", "stage2", "stage3", "stage4"]:
        lines.append(f"### {k}")
        counts = stage_counts.get(k, {})
        if not counts:
            lines.append("- (no data)")
        else:
            for t, n in counts.items():
                lines.append(f"- `{t}`: {n}")
        lines.append("")
    summary_md.write_text("\n".join(lines), encoding="utf-8")

    manifest = {
        "page": a.page,
        "pdf": str(pdf_path),
        "base_json": str(base_json),
        "out_dir": str(out_dir),
        "params": {
            "split_x_tol": a.split_x_tol,
            "merge_max_gap": a.merge_max_gap,
            "merge_min_overlap": a.merge_min_overlap,
            "merge_x_bin_tol": a.merge_x_bin_tol,
            "merge_x_shift_hard": a.merge_x_shift_hard,
            "stitch_max_gap": a.stitch_max_gap,
            "stitch_min_overlap": a.stitch_min_overlap,
            "stitch_x0_tol": a.stitch_x0_tol,
        },
        "outputs": {
            "stage0": str(s0),
            "stage1": str(s1),
            "stage2": str(s2),
            "stage3": str(s3),
            "stage4": str(s4),
            "summary_md": str(summary_md),
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Stable final JSON (alias)
    final_json = out_dir / "final.json"
    if cur.exists():
        final_json.write_bytes(cur.read_bytes())

    print("\n[done] Outputs written:")
    print(f"  - final.json:   {final_json}")
    print(f"  - summary.md:   {summary_md}")
    if not a.no_overlays:
        print(f"  - overlay_final.png: {out_dir / 'overlay_final.png'}")
        print(f"  - montage.png:       {out_dir / 'montage.png'}")


if __name__ == "__main__":
    main()
