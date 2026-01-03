# tools/export_manager.py
"""
Export Manager (Milestone 1)

Goals:
- NEVER move/rename exports/MostRecent (Windows Explorer will lie to you).
- Create a new run folder every run:
    exports/Runs/YYYYMMDD_00001
    exports/Runs/YYYYMMDD_00002
- Clear contents of exports/MostRecent before each run (strict by default).
- Write run_manifest.json into BOTH:
    exports/MostRecent/run_manifest.json
    exports/Runs/<run_id>/run_manifest.json

Why strict MostRecent clearing?
- If overlay_final.png is open in Windows Photos, it can lock the file.
- If we can't clear MostRecent, your visuals won't update reliably.
- We fail loudly so you close the viewer and rerun.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Tuple


RUN_ID_RE = re.compile(r"^(?P<date>\d{8})_(?P<seq>\d{5})$")


@dataclass(frozen=True)
class ExportPaths:
    project_root: Path
    exports_dir: Path
    runs_dir: Path
    most_recent_dir: Path


@dataclass(frozen=True)
class RunContext:
    run_id: str
    run_dir: Path
    most_recent_dir: Path
    exports_dir: Path
    runs_dir: Path


# -----------------------------
# Path helpers
# -----------------------------

def get_paths(project_root: Path) -> ExportPaths:
    exports_dir = project_root / "exports"
    return ExportPaths(
        project_root=project_root,
        exports_dir=exports_dir,
        runs_dir=exports_dir / "Runs",
        most_recent_dir=exports_dir / "MostRecent",
    )


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


# -----------------------------
# Windows-safe delete helpers
# -----------------------------

def _make_writable(p: Path) -> None:
    try:
        os.chmod(p, stat.S_IWRITE)
    except Exception:
        pass


def clear_dir_contents(path: Path, strict: bool = True) -> None:
    """
    Delete everything inside `path` but keep the directory.

    strict=True:
      - If any file cannot be deleted (locked by viewer), raise an error listing offenders.

    strict=False:
      - Best effort delete; ignores failures (NOT recommended for your workflow).
    """
    ensure_dir(path)

    failures: list[str] = []

    for item in path.iterdir():
        try:
            if item.is_dir():
                shutil.rmtree(item, onerror=lambda func, p, exc: (_make_writable(Path(p)), func(p)))
            else:
                _make_writable(item)
                item.unlink(missing_ok=True)
        except Exception as e:
            failures.append(f"{item} :: {e!r}")

    if failures and strict:
        msg = (
            "[ERROR] Could not clear exports/MostRecent.\n"
            "This is almost always a locked PNG (Windows Photos).\n"
            "Close any image viewers and rerun.\n\n"
            "Locked items:\n- " + "\n- ".join(failures)
        )
        raise RuntimeError(msg)


# -----------------------------
# Run ID: YYYYMMDD_00001
# -----------------------------

def _today_local_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")


def _iter_existing_run_ids(runs_dir: Path, date_prefix: str) -> Iterable[int]:
    """
    Yield integer sequences for runs that match YYYYMMDD_00001 for the given date.
    """
    if not runs_dir.exists():
        return
    for p in runs_dir.iterdir():
        if not p.is_dir():
            continue
        m = RUN_ID_RE.match(p.name)
        if not m:
            continue
        if m.group("date") != date_prefix:
            continue
        yield int(m.group("seq"))


def next_run_id(runs_dir: Path, date_prefix: Optional[str] = None) -> str:
    """
    Find the next run id for today's date (or provided date):
      20251225_00001, 20251225_00002, ...
    """
    date_prefix = date_prefix or _today_local_yyyymmdd()
    ensure_dir(runs_dir)
    max_seq = 0
    for seq in _iter_existing_run_ids(runs_dir, date_prefix):
        max_seq = max(max_seq, seq)
    return f"{date_prefix}_{(max_seq + 1):05d}"


def create_run_dir(runs_dir: Path, run_id: str) -> Path:
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


# -----------------------------
# Manifests
# -----------------------------

def _manifest_payload(ctx: RunContext) -> dict:
    return {
        "run_id": ctx.run_id,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "exports_dir": str(ctx.exports_dir.resolve()),
        "runs_dir": str(ctx.runs_dir.resolve()),
        "run_dir": str(ctx.run_dir.resolve()),
        "most_recent_dir": str(ctx.most_recent_dir.resolve()),
    }


def write_manifest(folder: Path, ctx: RunContext) -> None:
    ensure_dir(folder)
    (folder / "run_manifest.json").write_text(
        json.dumps(_manifest_payload(ctx), indent=2),
        encoding="utf-8",
    )


def write_pointer_file(exports_dir: Path, ctx: RunContext) -> None:
    """
    Optional human-friendly pointer (nice for debugging):
      exports/MOST_RECENT_RUN.txt -> absolute path to current run folder
    """
    (exports_dir / "MOST_RECENT_RUN.txt").write_text(str(ctx.run_dir.resolve()), encoding="utf-8")


# -----------------------------
# Cleanup
# -----------------------------

def cleanup_old_runs(runs_dir: Path, keep_last_runs: int) -> int:
    """
    Keep N newest run folders (by name descending). Only considers folders matching RUN_ID_RE.
    """
    if keep_last_runs <= 0:
        return 0
    ensure_dir(runs_dir)

    runs: list[Path] = []
    for p in runs_dir.iterdir():
        if p.is_dir() and RUN_ID_RE.match(p.name):
            runs.append(p)

    runs.sort(key=lambda p: p.name)  # ascending
    to_delete = max(0, len(runs) - keep_last_runs)
    deleted = 0
    for p in runs[:to_delete]:
        shutil.rmtree(p, onerror=lambda func, path, exc: (_make_writable(Path(path)), func(path)))
        deleted += 1
    return deleted


# -----------------------------
# Primary API
# -----------------------------

def start_new_run(project_root: Path, keep_last_runs: int = 20, strict_most_recent_clear: bool = True) -> RunContext:
    """
    Milestone 1 entrypoint.

    - Creates exports/Runs/YYYYMMDD_00001
    - Clears exports/MostRecent contents (does NOT move it)
    - Writes run_manifest.json into both run dir and MostRecent
    """
    paths = get_paths(project_root)
    ensure_dir(paths.exports_dir)
    ensure_dir(paths.runs_dir)
    ensure_dir(paths.most_recent_dir)

    # Create unique run dir (handles rare collisions)
    while True:
        run_id = next_run_id(paths.runs_dir)
        try:
            run_dir = create_run_dir(paths.runs_dir, run_id)
            break
        except FileExistsError:
            continue

    # Prepare MostRecent (stable folder; clear contents only)
    clear_dir_contents(paths.most_recent_dir, strict=strict_most_recent_clear)

    ctx = RunContext(
        run_id=run_id,
        run_dir=run_dir,
        most_recent_dir=paths.most_recent_dir,
        exports_dir=paths.exports_dir,
        runs_dir=paths.runs_dir,
    )

    write_manifest(ctx.run_dir, ctx)
    write_manifest(ctx.most_recent_dir, ctx)
    write_pointer_file(paths.exports_dir, ctx)

    cleanup_old_runs(paths.runs_dir, keep_last_runs=keep_last_runs)

    return ctx
