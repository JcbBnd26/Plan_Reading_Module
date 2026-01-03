#!/usr/bin/env python
"""
prepare_exports_run.py

Creates a new run directory with deterministic naming:
YYYYMMDD_00001

Clears and repopulates exports/MostRecent as a mirror target.
Writes run_manifest.json for traceability.

This script MUST be called ONCE per pipeline run.
"""

from pathlib import Path
from datetime import datetime
import json
import shutil
import argparse

# ----------------------------
# CONFIG
# ----------------------------

DEFAULT_EXPORTS_DIR = Path("exports")
RUNS_DIRNAME = "Runs"
MOSTRECENT_DIRNAME = "MostRecent"


# ----------------------------
# HELPERS
# ----------------------------

def next_run_id(runs_dir: Path) -> str:
    today = datetime.now().strftime("%Y%m%d")

    existing = [
        p for p in runs_dir.iterdir()
        if p.is_dir() and p.name.startswith(today)
    ]

    if not existing:
        idx = 1
    else:
        nums = []
        for p in existing:
            try:
                nums.append(int(p.name.split("_")[1]))
            except Exception:
                continue
        idx = max(nums) + 1 if nums else 1

    return f"{today}_{idx:05d}"


def clear_directory(dirpath: Path):
    if not dirpath.exists():
        dirpath.mkdir(parents=True)
        return

    for item in dirpath.iterdir():
        if item.is_file():
            item.unlink()
        else:
            shutil.rmtree(item)


# ----------------------------
# MAIN
# ----------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--exports-dir",
        default=str(DEFAULT_EXPORTS_DIR),
        help="Base exports directory (default: exports/)",
    )
    args = ap.parse_args()

    exports_dir = Path(args.exports_dir).resolve()
    runs_dir = exports_dir / RUNS_DIRNAME
    mostrecent_dir = exports_dir / MOSTRECENT_DIRNAME

    runs_dir.mkdir(parents=True, exist_ok=True)
    mostrecent_dir.mkdir(parents=True, exist_ok=True)

    run_id = next_run_id(runs_dir)
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=False, exist_ok=False)

    # Hard reset MostRecent (NO stale files allowed)
    clear_directory(mostrecent_dir)

    # Write manifest
    manifest = {
        "run_id": run_id,
        "created_utc": datetime.utcnow().isoformat() + "Z",
        "run_dir": str(run_dir),
        "most_recent": str(mostrecent_dir),
    }

    manifest_path = mostrecent_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"[OK] New run_id: {run_id}")
    print(f"[OK] Run dir:    {run_dir}")
    print(f"[OK] MostRecent: {mostrecent_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
