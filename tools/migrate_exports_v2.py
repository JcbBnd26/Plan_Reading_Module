#!/usr/bin/env python
"""
migrate_exports_v2.py

One-time, SAFE migration of legacy exports structure into the modern layout.

Target final layout
-------------------
exports/
  ├─ MostRecent/          (ephemeral, current run only)
  ├─ Runs/
  │    ├─ <run_id>/
  │    ├─ legacy_archive_<timestamp>/
  │    └─ legacy_previousexports_<timestamp>/
data/
  └─ structural_masks/    (cached structural artifacts)

What this script does
---------------------
1) Moves exports/Archive/*        -> exports/Runs/<run_id or legacy_archive_*>
2) Moves exports/PreviousExports  -> exports/Runs/legacy_previousexports_<ts>
3) Moves exports/structural/*     -> data/structural_masks/
4) Leaves exports/MostRecent untouched
5) Writes migration_report.json (every move recorded)

Safety
------
- Dry-run supported
- Refuses to overwrite existing destinations
- Never deletes data
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


# -------------------------
# Helpers
# -------------------------

def now_utc_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def move_safe(src: Path, dst: Path, report: Dict, dry_run: bool) -> None:
    if not src.exists():
        return

    if dst.exists():
        raise RuntimeError(f"Destination already exists, refusing to overwrite: {dst}")

    report["moves"].append({"from": str(src), "to": str(dst)})

    if dry_run:
        return

    ensure_dir(dst.parent)
    shutil.move(str(src), str(dst))


# -------------------------
# Migration logic
# -------------------------

def migrate_exports(project_root: Path, dry_run: bool) -> Dict:
    exports = project_root / "exports"
    data = project_root / "data"
    runs = exports / "Runs"
    most_recent = exports / "MostRecent"

    archive = exports / "Archive"
    previous = exports / "PreviousExports"
    structural = exports / "structural"

    structural_dst = data / "structural_masks"

    report = {
        "timestamp_utc": now_utc_tag(),
        "dry_run": dry_run,
        "moves": [],
        "notes": [],
    }

    ensure_dir(runs)
    ensure_dir(most_recent)
    ensure_dir(structural_dst)

    # --- Archive ---
    if archive.exists():
        for run in archive.iterdir():
            if not run.is_dir():
                continue
            dst = runs / run.name
            move_safe(run, dst, report, dry_run)
        report["notes"].append("Archived Archive/* -> Runs/")

    # --- PreviousExports ---
    if previous.exists() and any(previous.iterdir()):
        tag = f"legacy_previousexports_{now_utc_tag()}"
        dst = runs / tag
        move_safe(previous, dst, report, dry_run)
        report["notes"].append("Moved PreviousExports -> Runs/legacy_previousexports_*")

    # --- structural ---
    if structural.exists():
        for item in structural.iterdir():
            dst = structural_dst / item.name
            move_safe(item, dst, report, dry_run)
        report["notes"].append("Moved exports/structural/* -> data/structural_masks/")

    return report


# -------------------------
# CLI
# -------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate legacy exports layout to modern structure.")
    parser.add_argument("--dry-run", action="store_true", help="Print actions but do not move files")
    args = parser.parse_args()

    tools_dir = Path(__file__).resolve().parent
    project_root = tools_dir.parent

    report = migrate_exports(project_root, dry_run=args.dry_run)

    report_path = project_root / "exports" / f"migration_report_{report['timestamp_utc']}.json"

    if args.dry_run:
        print("[DRY-RUN] Migration preview:")
        print(json.dumps(report, indent=2))
        return

    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[OK] Migration complete.")
    print(f"[OK] Report written to: {report_path}")


if __name__ == "__main__":
    main()
