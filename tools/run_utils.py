# tools/run_utils.py
"""
Run folder + MostRecent utilities.

Rules:
- Each run gets run_id: YYYYMMDD_00001, YYYYMMDD_00002, ...
- Canonical artifacts live in: exports/Runs/<run_id>/
- exports/MostRecent is a *latest view*:
  - cleaned at run start
  - receives canonical filenames (overlay_final.png, stage2_headers_split.json, ...)
  - ALSO receives run-stamped copies for visual verification:
      overlay_final__YYYYMMDD_00001.png
      stage2_headers_split__YYYYMMDD_00001.json
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class RunContext:
    run_id: str
    run_dir: Path
    most_recent_dir: Path
    created_utc: str


def project_root() -> Path:
    # tools/ is one level below project root
    return Path(__file__).resolve().parents[1]


def exports_dir() -> Path:
    return project_root() / "exports"


def runs_dir() -> Path:
    return exports_dir() / "Runs"


def most_recent_dir() -> Path:
    return exports_dir() / "MostRecent"


def _today_yyyymmdd_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_run_id(name: str) -> bool:
    # YYYYMMDD_00001
    if len(name) != 14:
        return False
    if name[8] != "_":
        return False
    date = name[:8]
    seq = name[9:]
    return date.isdigit() and seq.isdigit()


def _next_run_id_for_today(today: str, base: Path) -> str:
    base.mkdir(parents=True, exist_ok=True)
    seqs = []
    for p in base.iterdir():
        if not p.is_dir():
            continue
        n = p.name
        if not _is_run_id(n):
            continue
        if not n.startswith(today + "_"):
            continue
        try:
            seqs.append(int(n.split("_")[1]))
        except Exception:
            pass
    next_seq = (max(seqs) + 1) if seqs else 1
    return f"{today}_{next_seq:05d}"


def clean_most_recent(keep: Iterable[str] = ("run_manifest.json",)) -> None:
    """
    Keep MostRecent as a clean *latest* folder.
    We remove:
      - stage*.json, overlay*.png
      - any run-stamped copies: *__YYYYMMDD_00001.(json|png)
    """
    mr = most_recent_dir()
    mr.mkdir(parents=True, exist_ok=True)

    keep_set = set(keep)
    for f in mr.iterdir():
        if f.is_dir():
            continue
        if f.name in keep_set:
            continue

        name = f.name.lower()
        # canonical
        if name.startswith("stage") and name.endswith(".json"):
            f.unlink(missing_ok=True)
            continue
        if name.startswith("overlay") and (name.endswith(".png") or name.endswith(".jpg") or name.endswith(".jpeg")):
            f.unlink(missing_ok=True)
            continue
        if name == "final.json":
            f.unlink(missing_ok=True)
            continue

        # run-stamped
        if "__" in name and (name.endswith(".json") or name.endswith(".png") or name.endswith(".jpg") or name.endswith(".jpeg")):
            f.unlink(missing_ok=True)
            continue


def write_run_manifest(ctx: RunContext) -> Path:
    mr = ctx.most_recent_dir
    mr.mkdir(parents=True, exist_ok=True)

    manifest = {
        "run_id": ctx.run_id,
        "created_utc": ctx.created_utc,
        "run_dir": str(ctx.run_dir),
        "most_recent": str(ctx.most_recent_dir),
    }
    path = mr / "run_manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def read_run_manifest() -> dict:
    path = most_recent_dir() / "run_manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"run_manifest.json not found at: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def create_new_run(clean_mr: bool = True) -> RunContext:
    rdir = runs_dir()
    mr = most_recent_dir()
    rdir.mkdir(parents=True, exist_ok=True)
    mr.mkdir(parents=True, exist_ok=True)

    if clean_mr:
        clean_most_recent()

    today = _today_yyyymmdd_utc()
    run_id = _next_run_id_for_today(today, rdir)
    run_path = rdir / run_id
    run_path.mkdir(parents=True, exist_ok=False)

    ctx = RunContext(
        run_id=run_id,
        run_dir=run_path,
        most_recent_dir=mr,
        created_utc=_now_iso_utc(),
    )
    write_run_manifest(ctx)
    return ctx


def stamped_name(filename: str, run_id: str) -> str:
    p = Path(filename)
    return f"{p.stem}__{run_id}{p.suffix}"


def sync_to_most_recent(src: Path, run_id: str, also_write_canonical: bool = True) -> tuple[Path, Path]:
    """
    Copy a file into exports/MostRecent as:
      - canonical name (optional)
      - run-stamped name (always)
    Returns: (canonical_path, stamped_path)
    """
    mr = most_recent_dir()
    mr.mkdir(parents=True, exist_ok=True)

    canonical = mr / src.name
    stamped = mr / stamped_name(src.name, run_id)

    if also_write_canonical:
        shutil.copy2(src, canonical)
    shutil.copy2(src, stamped)

    return canonical, stamped


def safe_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
