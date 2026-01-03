#!/usr/bin/env python3
"""
system_tools/realign_repo.py

One-shot repo realignment tool (SYSTEM MAINTENANCE).
This does NOT belong in tools/ (chunker tools). It belongs in system_tools/.

What it does:
- Optional archive of current exports/ into exports/_Archive_Reset/<stamp>/
- Normalize exports directory layout:
    exports/
      Runs/
      MostRecent/   (cleared)
      _Archive_Reset/
- Optionally relocate legacy/redundant folders if present:
    exports/Archive/*            -> exports/Runs/<same>
    exports/PreviousExports      -> exports/Runs/legacy_previousexports_<stamp>
    exports/structural/*         -> data/structural_masks/*
- Verify toolchain scripts exist and compile (py_compile), to detect drift
- Prints a clear summary of actions

Safety:
- Default is DRY-RUN (no changes)
- Use --force to apply changes
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import py_compile


# -----------------------------
# Paths / Config
# -----------------------------

@dataclass(frozen=True)
class RepoPaths:
    root: Path
    exports: Path
    runs: Path
    most_recent: Path
    archive_root: Path
    data_structural: Path
    tools_dir: Path
    system_tools_dir: Path


REQUIRED_TOOL_SCRIPTS = [
    "prepare_exports_run.py",
    "run_notes_page_pipeline.py",
    "tag_header_candidates.py",
    "tighten_group_bboxes.py",
    "split_banner_headers.py",
    "merge_note_fragments.py",
    "fix_split_notes_postmerge.py",
    "visualize_notes_from_json.py",
    "assert_pipeline_invariants.py",
]

LEGACY_EXPORT_DIRS = [
    "Archive",
    "PreviousExports",
    "structural",
    "Exports",   # sometimes shows up from earlier versions
    "Runs",      # should exist but may be malformed
]


# -----------------------------
# Helpers
# -----------------------------

def repo_root_from_this_file() -> Path:
    # system_tools/realign_repo.py -> root is parent of system_tools
    return Path(__file__).resolve().parents[1]


def stamp_utc() -> str:
    # simple sortable stamp
    return time.strftime("%Y%m%d_%H%M%S", time.gmtime())


def info(msg: str) -> None:
    print(msg)


def ensure_dir(p: Path, dry_run: bool) -> None:
    if p.exists():
        return
    if dry_run:
        info(f"[DRY] mkdir {p}")
        return
    p.mkdir(parents=True, exist_ok=True)
    info(f"[OK]  mkdir {p}")


def safe_move(src: Path, dst: Path, dry_run: bool) -> None:
    if not src.exists():
        return
    if dry_run:
        info(f"[DRY] move {src} -> {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    info(f"[OK]  move {src} -> {dst}")


def safe_copy(src: Path, dst: Path, dry_run: bool) -> None:
    if not src.exists():
        return
    if dry_run:
        info(f"[DRY] copy {src} -> {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    info(f"[OK]  copy {src} -> {dst}")


def safe_rm_tree(p: Path, dry_run: bool) -> None:
    if not p.exists():
        return
    if dry_run:
        info(f"[DRY] rmtree {p}")
        return
    shutil.rmtree(p)
    info(f"[OK]  rmtree {p}")


def safe_rm_file(p: Path, dry_run: bool) -> None:
    if not p.exists():
        return
    if dry_run:
        info(f"[DRY] rm {p}")
        return
    p.unlink(missing_ok=True)
    info(f"[OK]  rm {p}")


def clear_dir_contents(dir_path: Path, dry_run: bool) -> None:
    if not dir_path.exists():
        return
    for item in dir_path.iterdir():
        if item.is_dir():
            safe_rm_tree(item, dry_run)
        else:
            safe_rm_file(item, dry_run)


def compile_check(script_path: Path) -> Tuple[bool, str]:
    try:
        py_compile.compile(str(script_path), doraise=True)
        return True, ""
    except Exception as e:
        return False, str(e)


def write_json(path: Path, obj: dict, dry_run: bool) -> None:
    if dry_run:
        info(f"[DRY] write {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    info(f"[OK]  write {path}")


def list_dir(dir_path: Path, limit: int = 50) -> List[str]:
    if not dir_path.exists():
        return []
    items = sorted(dir_path.iterdir(), key=lambda p: p.name)
    out = []
    for p in items[:limit]:
        out.append(p.name + ("/" if p.is_dir() else ""))
    if len(items) > limit:
        out.append(f"... ({len(items)-limit} more)")
    return out


# -----------------------------
# Core Realignment Actions
# -----------------------------

def build_paths() -> RepoPaths:
    root = repo_root_from_this_file()
    exports = root / "exports"
    runs = exports / "Runs"
    most_recent = exports / "MostRecent"
    archive_root = exports / "_Archive_Reset"
    data_structural = root / "data" / "structural_masks"
    tools_dir = root / "tools"
    system_tools_dir = root / "system_tools"
    return RepoPaths(
        root=root,
        exports=exports,
        runs=runs,
        most_recent=most_recent,
        archive_root=archive_root,
        data_structural=data_structural,
        tools_dir=tools_dir,
        system_tools_dir=system_tools_dir,
    )


def archive_exports(paths: RepoPaths, dry_run: bool, keep_archive: bool) -> Path | None:
    """
    Move everything inside exports/ (except _Archive_Reset) into archive stamp folder.
    """
    if not paths.exports.exists():
        return None

    if not keep_archive:
        return None

    ensure_dir(paths.archive_root, dry_run)
    dest = paths.archive_root / f"pre_realign_{stamp_utc()}"
    ensure_dir(dest, dry_run)

    for item in paths.exports.iterdir():
        if item.name == "_Archive_Reset":
            continue
        safe_move(item, dest / item.name, dry_run)

    return dest


def normalize_exports_layout(paths: RepoPaths, dry_run: bool) -> None:
    """
    Recreate canonical exports layout and ensure MostRecent is empty.
    """
    ensure_dir(paths.exports, dry_run)
    ensure_dir(paths.runs, dry_run)
    ensure_dir(paths.most_recent, dry_run)

    # MostRecent must be clean slate (no ghost files)
    info("[INFO] Clearing exports/MostRecent contents")
    clear_dir_contents(paths.most_recent, dry_run)

    # Leave a marker so user can tell realign ran
    write_json(
        paths.most_recent / "REALIGNED.json",
        {"realigned_utc": stamp_utc(), "note": "MostRecent cleared by system_tools/realign_repo.py"},
        dry_run,
    )


def relocate_legacy_exports(paths: RepoPaths, dry_run: bool) -> None:
    """
    If legacy directories exist (common drift):
      exports/Archive/* -> exports/Runs/<same>
      exports/PreviousExports -> exports/Runs/legacy_previousexports_<stamp>
      exports/structural/* -> data/structural_masks/*
    """
    exports = paths.exports
    archive_dir = exports / "Archive"
    prev_exports = exports / "PreviousExports"
    structural = exports / "structural"

    # Archive -> Runs
    if archive_dir.exists() and archive_dir.is_dir():
        for child in archive_dir.iterdir():
            if child.is_dir():
                safe_move(child, paths.runs / child.name, dry_run)
            else:
                safe_move(child, paths.runs / child.name, dry_run)
        # remove empty Archive folder
        safe_rm_tree(archive_dir, dry_run)

    # PreviousExports -> Runs/legacy_...
    if prev_exports.exists():
        dest = paths.runs / f"legacy_previousexports_{stamp_utc()}"
        safe_move(prev_exports, dest, dry_run)

    # exports/structural -> data/structural_masks
    if structural.exists() and structural.is_dir():
        ensure_dir(paths.data_structural, dry_run)
        for f in structural.iterdir():
            if f.is_file():
                safe_move(f, paths.data_structural / f.name, dry_run)
        safe_rm_tree(structural, dry_run)


def verify_toolchain(paths: RepoPaths) -> List[str]:
    """
    Compile-check required scripts to detect drift/syntax errors.
    """
    problems: List[str] = []
    for name in REQUIRED_TOOL_SCRIPTS:
        p = paths.tools_dir / name
        if not p.exists():
            problems.append(f"Missing required tool script: tools/{name}")
            continue
        ok, err = compile_check(p)
        if not ok:
            problems.append(f"Compile failed tools/{name}: {err}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="Apply changes (default is dry-run).")
    ap.add_argument("--no-archive", action="store_true", help="Do not archive exports/ before realigning.")
    ap.add_argument("--skip-legacy-relocate", action="store_true", help="Skip moving legacy exports folders.")
    ap.add_argument("--verify-only", action="store_true", help="Only verify toolchain; do not modify filesystem.")
    args = ap.parse_args()

    dry_run = not args.force
    paths = build_paths()

    info("=== REALIGN REPO (SYSTEM TOOL) ===")
    info(f"[INFO] Repo root: {paths.root}")
    info(f"[INFO] Mode: {'DRY-RUN' if dry_run else 'FORCE (APPLY)'}")
    info("")

    # Always verify toolchain first (fast fail)
    info("[STEP] Toolchain compile check")
    problems = verify_toolchain(paths)
    if problems:
        info("❌ Toolchain problems detected:")
        for p in problems:
            info(f"  - {p}")
        info("\nFix these before continuing.")
        return 1
    info("[OK] Toolchain compiles")

    if args.verify_only:
        info("[DONE] verify-only")
        return 0

    # Optional archive step (recommended)
    if not args.no_archive:
        info("[STEP] Archive existing exports/")
        archive_dest = archive_exports(paths, dry_run=dry_run, keep_archive=True)
        if archive_dest:
            info(f"[OK] Archive dest: {archive_dest}")
        else:
            info("[OK] Nothing to archive (exports missing or empty)")
    else:
        info("[SKIP] Archive step disabled (--no-archive)")

    # Recreate layout + clear MostRecent
    info("[STEP] Normalize exports layout + clear MostRecent")
    normalize_exports_layout(paths, dry_run=dry_run)

    # Relocate legacy exports folders (optional)
    if not args.skip_legacy_relocate:
        info("[STEP] Relocate legacy exports folders (Archive/PreviousExports/structural)")
        relocate_legacy_exports(paths, dry_run=dry_run)
    else:
        info("[SKIP] Legacy relocation disabled (--skip-legacy-relocate)")

    # Final summary
    info("\n=== SUMMARY ===")
    info(f"exports/: {paths.exports}")
    info(f"Runs/:   {paths.runs}")
    info(f"MostRecent/: {paths.most_recent}")
    info(f"Archive root: {paths.archive_root}")
    info(f"data/structural_masks/: {paths.data_structural}")

    info("\nMostRecent contents (preview):")
    for n in list_dir(paths.most_recent, limit=50):
        info(f"  - {n}")

    info("\nNext: run the pipeline once:")
    info(r'  py tools\run_notes_page_pipeline.py --pdf test.pdf --base-json data\structural_masks\all_pages_notes_sheetwide_no_legend.json --page 3')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
