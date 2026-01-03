"""
tools/clean_generated_artifacts.py

Delete generated artifacts so the repo contains only necessary project files
(code + docs + optional sample inputs), suitable for a clean GitHub upload.

Defaults to DRY RUN (no deletion). Use --yes to actually delete.

What it targets (safe defaults):
- exports/Runs/**                (entire run history)
- exports/MostRecent/**          (regenerated view)
- any overlay_*.png / stage*.json in exports
- common Python caches           (__pycache__, .pytest_cache, *.pyc)
- misc temp/log artifacts        (*.log, *.tmp) in exports/tools (configurable)

It preserves:
- source code, docs, configs
- folder structure (optional: keeps .gitkeep files if present)
"""

from __future__ import annotations

import argparse
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple


# ----------------------------
# Configuration
# ----------------------------

@dataclass(frozen=True)
class DeleteSpec:
    """A deletion rule. Either a direct path or a glob pattern under root."""
    description: str
    rel_path: str | None = None          # direct path under root
    rel_glob: str | None = None          # glob under root
    is_dir: bool = False                 # if rel_path points to dir, delete dir
    under: str | None = None             # restrict glob to subtree under root


DEFAULT_SPECS: List[DeleteSpec] = [
    DeleteSpec("Run history", rel_path="exports/Runs", is_dir=True),
    DeleteSpec("MostRecent view", rel_path="exports/MostRecent", is_dir=True),

    # If anything leaked outside those folders (or you moved outputs), clean these too:
    DeleteSpec("Overlay PNGs in exports", rel_glob="overlay_*.png", under="exports"),
    DeleteSpec("Stage JSONs in exports", rel_glob="stage*.json", under="exports"),
    DeleteSpec("Final JSON in exports", rel_glob="final*.json", under="exports"),
    DeleteSpec("Run manifests in exports", rel_glob="run_manifest*.json", under="exports"),

    # Python caches
    DeleteSpec("__pycache__ folders", rel_glob="__pycache__", under="."),
    DeleteSpec(".pytest_cache folders", rel_glob=".pytest_cache", under="."),
    DeleteSpec("*.pyc files", rel_glob="*.pyc", under="."),
]


# ----------------------------
# Helpers
# ----------------------------

def repo_root_from_this_file() -> Path:
    """Assume this file is at <repo>/tools/clean_generated_artifacts.py"""
    return Path(__file__).resolve().parents[1]


def iter_glob(root: Path, pattern: str, under: str | None) -> Iterable[Path]:
    base = root / under if under else root
    yield from base.rglob(pattern)


def is_gitkeep(p: Path) -> bool:
    return p.is_file() and p.name == ".gitkeep"


def safe_rel(p: Path, root: Path) -> str:
    try:
        return str(p.relative_to(root))
    except Exception:
        return str(p)


def plan_deletions(root: Path, specs: List[DeleteSpec]) -> Tuple[List[Path], List[Path]]:
    """
    Returns (paths_to_delete, paths_missing)
    paths_to_delete includes both files and directories.
    """
    targets: List[Path] = []
    missing: List[Path] = []

    for spec in specs:
        if spec.rel_path:
            p = (root / spec.rel_path).resolve()
            if p.exists():
                targets.append(p)
            else:
                missing.append(p)
            continue

        if spec.rel_glob:
            for m in iter_glob(root, spec.rel_glob, spec.under):
                # When rglob finds __pycache__ or .pytest_cache we want the dir itself
                # When it finds files, delete files.
                targets.append(m)
            continue

    # Deduplicate and sort (delete children before parents)
    uniq = sorted(set(targets), key=lambda x: (len(str(x)), str(x)), reverse=True)
    return uniq, missing


def delete_path(p: Path, root: Path, keep_gitkeep: bool) -> None:
    """
    Delete file/dir safely. If keep_gitkeep=True, leave .gitkeep files in place.
    """
    if not p.exists():
        return

    # If directory: delete contents, optionally preserving .gitkeep files.
    if p.is_dir():
        if keep_gitkeep:
            for child in p.rglob("*"):
                if child.is_dir():
                    continue
                if is_gitkeep(child):
                    continue
                try:
                    child.unlink()
                except Exception:
                    # fallback for odd permissions
                    try:
                        os.chmod(child, 0o666)
                        child.unlink()
                    except Exception as e:
                        raise RuntimeError(f"Failed deleting file: {safe_rel(child, root)} ({e})") from e

            # Remove now-empty dirs (but keep the root dir itself)
            for d in sorted([x for x in p.rglob("*") if x.is_dir()], key=lambda x: len(str(x)), reverse=True):
                # If directory still has stuff (like .gitkeep), keep it
                try:
                    if not any(d.iterdir()):
                        d.rmdir()
                except Exception:
                    pass

        else:
            shutil.rmtree(p, ignore_errors=False)
        return

    # If file
    if keep_gitkeep and is_gitkeep(p):
        return
    try:
        p.unlink()
    except Exception:
        # Windows often fails if file is read-only
        try:
            os.chmod(p, 0o666)
            p.unlink()
        except Exception as e:
            raise RuntimeError(f"Failed deleting file: {safe_rel(p, root)} ({e})") from e


def count_files(root: Path) -> int:
    return sum(1 for _ in root.rglob("*") if _.is_file())


# ----------------------------
# CLI
# ----------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Clean generated artifacts (dry-run by default).")
    ap.add_argument("--root", type=str, default=None, help="Repo root (defaults to parent of tools/).")
    ap.add_argument("--yes", action="store_true", help="Actually delete (otherwise dry-run).")
    ap.add_argument("--keep-gitkeep", action="store_true", default=True,
                    help="Preserve .gitkeep files (default: on).")
    ap.add_argument("--no-keep-gitkeep", dest="keep_gitkeep", action="store_false",
                    help="Delete .gitkeep files too.")
    ap.add_argument("--extra", action="append", default=[],
                    help="Extra relative paths to delete (can repeat). Example: --extra data/tmp")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else repo_root_from_this_file()
    if not root.exists():
        raise SystemExit(f"Root not found: {root}")

    specs = list(DEFAULT_SPECS)
    for rel in args.extra:
        specs.append(DeleteSpec(f"Extra path: {rel}", rel_path=rel, is_dir=True))

    targets, missing = plan_deletions(root, specs)

    print(f"[INFO] repo root: {root}")
    print(f"[INFO] file count before: {count_files(root)}")
    print(f"[INFO] targets found: {len(targets)}")
    if missing:
        print(f"[INFO] missing targets (ok): {len(missing)}")

    # Show plan
    print("\n=== PLAN ===")
    for p in targets:
        kind = "DIR " if p.is_dir() else "FILE"
        print(f"  {kind} {safe_rel(p, root)}")

    if not args.yes:
        print("\n[DRY RUN] No files deleted. Re-run with --yes to apply.")
        return 0

    print("\n=== DELETING ===")
    deleted = 0
    for p in targets:
        if p.exists():
            delete_path(p, root, keep_gitkeep=args.keep_gitkeep)
            deleted += 1
            print(f"[DEL] {safe_rel(p, root)}")

    print(f"\n[OK] Deleted {deleted} target path(s).")
    print(f"[INFO] file count after: {count_files(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
