#!/usr/bin/env python3
"""
tools/run_notes_page_pipeline.py

Pipeline runner for a single page that enforces stage contracts.

Core contract this runner enforces
----------------------------------
For each stage:
- tool runs
- output file MUST exist
- output file MUST be minimally valid JSON + bbox schema
If any of those fail, the pipeline aborts immediately (no misleading downstream crashes).

Outputs
-------
Run artifacts are written to:
  exports/Runs/<run_id>/

After a successful run, a "latest view" is published to:
  exports/MostRecent/
(including both canonical filenames AND run-stamped copies)

This runner does NOT write into MostRecent until the run is fully successful.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

import bbox_utils
import validate_stage_json


# -----------------------------------------------------------------------------
# Run folder utilities
# -----------------------------------------------------------------------------


def _repo_root() -> Path:
    # tools/ is one level below project root
    return Path(__file__).resolve().parents[1]


def _exports_dir(root: Path) -> Path:
    return root / "exports"


def _runs_dir(root: Path) -> Path:
    return _exports_dir(root) / "Runs"


def _most_recent_dir(root: Path) -> Path:
    return _exports_dir(root) / "MostRecent"


def _today_yyyymmdd_local() -> str:
    return datetime.now().strftime("%Y%m%d")


def _next_run_id(runs_dir: Path, date_prefix: str) -> str:
    runs_dir.mkdir(parents=True, exist_ok=True)
    max_seq = 0
    prefix = f"{date_prefix}_"
    for p in runs_dir.iterdir():
        if not p.is_dir():
            continue
        name = p.name
        if not name.startswith(prefix):
            continue
        try:
            seq = int(name.split("_")[1])
            max_seq = max(max_seq, seq)
        except Exception:
            continue
    return f"{date_prefix}_{(max_seq + 1):05d}"


def create_run_dir(root: Path) -> Path:
    runs = _runs_dir(root)
    date_prefix = _today_yyyymmdd_local()

    # Extremely defensive: handle rare collisions.
    for _ in range(1000):
        run_id = _next_run_id(runs, date_prefix)
        run_dir = runs / run_id
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
            return run_dir
        except FileExistsError:
            continue

    raise RuntimeError("Failed to allocate a unique run folder after many attempts.")


def write_run_manifest(run_dir: Path, *, pdf: Path, base_json: Path, page: int) -> dict:
    manifest = {
        "run_id": run_dir.name,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "pdf": str(pdf.resolve()),
        "base_json": str(base_json.resolve()),
        "page": int(page),
        "run_dir": str(run_dir.resolve()),
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


# -----------------------------------------------------------------------------
# Subprocess helper
# -----------------------------------------------------------------------------


def run_cmd(args: List[str], *, cwd: Path) -> None:
    print(f"[cmd] {' '.join(args)}")
    subprocess.run(args, cwd=str(cwd), check=True)


# -----------------------------------------------------------------------------
# Assertions + validations
# -----------------------------------------------------------------------------


def assert_file_exists(path: Path, *, stage: str) -> None:
    if not path.exists():
        raise FileNotFoundError(
            f"[PIPELINE CONTRACT BROKEN] {stage} did not produce expected output:\n  {path}\n"
            "Root cause is upstream of the crash; fix the stage that should have written this file."
        )


def assert_stage_json(path: Path, *, stage: str, page: int) -> None:
    """
    Minimal "stop the world" validation.
    """
    try:
        validate_stage_json.validate_stage(
            path,
            page=page,
            require_bbox_dict=True,
            require_dict_root=True,
        )
    except ValueError as e:
        raise RuntimeError(f"[PIPELINE CONTRACT BROKEN] Invalid JSON for {stage}: {e}") from e


def assert_no_header_inside_note(path: Path, *, page: int, containment_thresh: float = 0.80) -> None:
    """
    Automated correctness assertion (catches the classic 'green header inside red note' bug).

    Fails if any header bbox is mostly contained within any note_group bbox.
    """
    root = json.loads(path.read_text(encoding="utf-8"))
    chunks = root.get("chunks") if isinstance(root, dict) else None
    if not isinstance(chunks, list):
        return

    page_str = str(page)

    headers: List[bbox_utils.BBox] = []
    notes: List[bbox_utils.BBox] = []

    for ch in chunks:
        if not isinstance(ch, dict):
            continue
        if str(ch.get("page")) != page_str:
            continue
        t = str(ch.get("type", "")).lower()
        box = bbox_utils.extract_bbox(ch)
        if not box:
            continue
        if t == "header":
            headers.append(box)
        elif t == "note_group":
            notes.append(box)

    for hb in headers:
        for nb in notes:
            # How much of the header sits inside the note?
            ratio = bbox_utils.overlap_ratio(hb, nb)
            if ratio >= float(containment_thresh):
                raise RuntimeError(
                    "[PIPELINE ASSERTION FAILED] Header bbox appears to be inside a note_group bbox.\n"
                    f"  stage: {path.name}\n"
                    f"  page: {page}\n"
                    f"  header: {hb.as_tuple()}\n"
                    f"  note:   {nb.as_tuple()}\n"
                    f"  overlap_ratio(header_in_note)={ratio:.3f} (thresh={containment_thresh})\n"
                    "This is a real data correctness issue (not a visualization issue)."
                )


# -----------------------------------------------------------------------------
# MostRecent publish (canonical + run-stamped)
# -----------------------------------------------------------------------------


def _stamped_name(filename: str, run_id: str) -> str:
    p = Path(filename)
    return f"{p.stem}__{run_id}{p.suffix}"


def publish_to_most_recent(
    *,
    most_recent: Path,
    run_id: str,
    files: Iterable[Path],
    manifest: dict,
) -> None:
    """
    Publish outputs to exports/MostRecent.

    Order is intentional:
    1) Always write run-stamped copies first (never overwrite old runs).
    2) Then try to overwrite canonical names.

    If canonical writes fail due to Windows file locks, you still have the stamped copies.
    """
    most_recent.mkdir(parents=True, exist_ok=True)

    failures: List[str] = []

    # Write manifest first (small, unlikely to be locked)
    try:
        (most_recent / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except Exception as e:
        failures.append(f"run_manifest.json :: {e!r}")

    for src in files:
        if not src.exists():
            failures.append(f"(missing src) {src}")
            continue

        stamped = most_recent / _stamped_name(src.name, run_id)
        canonical = most_recent / src.name

        # 1) run-stamped copy (never overwrites)
        try:
            shutil.copy2(src, stamped)
        except Exception as e:
            failures.append(f"{stamped.name} :: {e!r}")
            continue

        # 2) canonical copy (overwrites)
        try:
            shutil.copy2(src, canonical)
        except Exception as e:
            failures.append(f"{canonical.name} :: {e!r}")

    if failures:
        msg = (
            "[PUBLISH WARNING/FAIL]\n"
            "Some files could not be published into exports/MostRecent.\n"
            "This is usually caused by Windows locking an image file (Photos app).\n\n"
            "Failures:\n- " + "\n- ".join(failures)
        )
        raise RuntimeError(msg)


# -----------------------------------------------------------------------------
# CLI + main
# -----------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the notes header/split/merge pipeline with strict stage contracts.")
    p.add_argument("--pdf", default="test.pdf")
    p.add_argument("--base-json", default="data/structural_masks/all_pages_notes_sheetwide_no_legend.json")
    p.add_argument("--page", type=int, default=3)
    p.add_argument("--dpi", type=int, default=200)
    p.add_argument("--no-overlays", action="store_true", help="Skip overlay PNG generation (faster).")
    p.add_argument("--debug-tools", action="store_true", help="Pass --debug to certain tools when supported.")
    return p.parse_args()


def main() -> int:
    a = parse_args()
    root = _repo_root()

    pdf_path = (root / a.pdf).resolve()
    base_json = (root / a.base_json).resolve()

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if not base_json.exists():
        raise FileNotFoundError(f"Base JSON not found: {base_json}")

    run_dir = create_run_dir(root)
    run_id = run_dir.name
    most_recent = _most_recent_dir(root)

    # Manifest lives in run_dir immediately (useful even if later stages fail)
    manifest = write_run_manifest(run_dir, pdf=pdf_path, base_json=base_json, page=int(a.page))

    tools = root / "tools"

    # Stage paths
    stage0 = run_dir / "stage0_base.json"
    stage1 = run_dir / "stage1_headers_tagged.json"
    stage1b = run_dir / "stage1b_headers_tagged_tight.json"
    stage2 = run_dir / "stage2_headers_split.json"
    stage2b = run_dir / "stage2b_headers_split_tight.json"
    stage3 = run_dir / "stage3_notes_merged.json"
    stage4 = run_dir / "stage4_notes_stitched.json"
    final_json = run_dir / "final.json"

    # --- Stage 0: copy base ---
    shutil.copy2(base_json, stage0)
    assert_file_exists(stage0, stage="stage0 (copy base)")
    assert_stage_json(stage0, stage="stage0", page=int(a.page))

    # --- Stage 1: tag headers ---
    cmd = [
        sys.executable, str(tools / "tag_header_candidates.py"),
        "--input", str(stage0),
        "--output", str(stage1),
        "--page", str(a.page),
    ]
    run_cmd(cmd, cwd=root)
    assert_file_exists(stage1, stage="stage1 (tag headers)")
    assert_stage_json(stage1, stage="stage1", page=int(a.page))

    # --- Stage 1b: tighten note_group bboxes ---
    cmd = [
        sys.executable, str(tools / "tighten_group_bboxes.py"),
        "--input", str(stage1),
        "--output", str(stage1b),
        "--page", str(a.page),
        "--group-types", "note_group",
        "--child-types", "text_line",
        "--min-child-overlap", "0.20",
        "--pad", "0.0",
    ]
    if a.debug_tools:
        cmd.append("--debug")
    run_cmd(cmd, cwd=root)
    assert_file_exists(stage1b, stage="stage1b (tighten note_group)")
    assert_stage_json(stage1b, stage="stage1b", page=int(a.page))

    # --- Stage 2: split banner headers ---
    cmd = [
        sys.executable, str(tools / "split_banner_headers.py"),
        "--input", str(stage1b),
        "--output", str(stage2),
        "--page", str(a.page),
        "--x-tol", "140",
        "--split-gap", "2.0",
        "--edge-inset", "0.75",
        "--min-banner-width", "250.0",
    ]
    if a.debug_tools:
        cmd.append("--debug")
    run_cmd(cmd, cwd=root)
    assert_file_exists(stage2, stage="stage2 (split headers)")
    assert_stage_json(stage2, stage="stage2", page=int(a.page))

    # --- Stage 2b: tighten header bboxes ---
    cmd = [
        sys.executable, str(tools / "tighten_group_bboxes.py"),
        "--input", str(stage2),
        "--output", str(stage2b),
        "--page", str(a.page),
        "--group-types", "header",
        "--child-types", "text_line",
        "--min-child-overlap", "0.20",
        "--pad", "1.5",
    ]
    if a.debug_tools:
        cmd.append("--debug")
    run_cmd(cmd, cwd=root)
    assert_file_exists(stage2b, stage="stage2b (tighten headers)")
    assert_stage_json(stage2b, stage="stage2b", page=int(a.page))

    # --- Stage 3: merge note fragments ---
    cmd = [
        sys.executable, str(tools / "merge_note_fragments.py"),
        "--input", str(stage2b),
        "--output", str(stage3),
        "--page", str(a.page),
    ]
    if a.debug_tools:
        cmd.append("--debug")
    run_cmd(cmd, cwd=root)
    assert_file_exists(stage3, stage="stage3 (merge notes)")
    assert_stage_json(stage3, stage="stage3", page=int(a.page))

    # Correctness assertion: header should not be inside merged note boxes
    assert_no_header_inside_note(stage3, page=int(a.page), containment_thresh=0.80)

    # --- Stage 4: stitch split notes (safety net) ---
    cmd = [
        sys.executable, str(tools / "fix_split_notes_postmerge.py"),
        "--input", str(stage3),
        "--output", str(stage4),
        "--only-page", str(a.page),
    ]
    run_cmd(cmd, cwd=root)
    assert_file_exists(stage4, stage="stage4 (stitch notes)")
    assert_stage_json(stage4, stage="stage4", page=int(a.page))

    # --- Final JSON ---
    shutil.copy2(stage4, final_json)
    assert_file_exists(final_json, stage="final.json")
    assert_stage_json(final_json, stage="final.json", page=int(a.page))

    # --- Overlays ---
    overlays: List[Path] = []
    if not a.no_overlays:
        for js in [stage0, stage1, stage1b, stage2, stage2b, stage3, stage4]:
            png = run_dir / f"overlay_{js.stem}.png"
            cmd = [
                sys.executable, str(tools / "visualize_notes_from_json.py"),
                "--pdf", str(pdf_path),
                "--json", str(js),
                "--page", str(a.page),
                "--out", str(png),
                "--dpi", str(a.dpi),
                "--scheme", "type",
                "--exclude-types", "text_line",
                "--label", run_id,
            ]
            run_cmd(cmd, cwd=root)
            assert_file_exists(png, stage=f"overlay for {js.name}")
            overlays.append(png)

        # Stable alias
        overlay_final = run_dir / "overlay_final.png"
        shutil.copy2(overlays[-1], overlay_final)
        overlays.append(overlay_final)

    # --- Publish to MostRecent (only after success) ---
    publish_files: List[Path] = [
        stage0, stage1, stage1b, stage2, stage2b, stage3, stage4, final_json, run_dir / "run_manifest.json"
    ] + overlays

    publish_to_most_recent(
        most_recent=most_recent,
        run_id=run_id,
        files=publish_files,
        manifest=manifest,
    )

    print("\n[OK] Pipeline complete.")
    print(f"  run_dir:      {run_dir}")
    print(f"  most_recent:  {most_recent}")
    print(f"  final.json:   {final_json}")
    if overlays:
        print(f"  overlay_final:{run_dir / 'overlay_final.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
