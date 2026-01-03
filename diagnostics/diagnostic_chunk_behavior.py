# diagnostic_chunk_behavior.py
# Read-only script to track CHUNKER BEHAVIOR over time.
# It runs the visual + text pipeline on test.pdf, computes metrics,
# and compares them against a stored baseline. It does NOT modify code.

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# ---------------------------------------------------------------------
# Paths / sys.path wiring
# ---------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backbone.visual.visual_pipeline_integrator import VisualPipelineIntegrator
from backbone.visual.visual_chunker_bridge import VisualChunkerBridge
from backbone.chunking import Chunker
from backbone.chunking.chunk import Chunk


# ---------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------

DIAG = ROOT / "diagnostics"

PDF_PATH = "test.pdf"
BASELINE_PATH = DIAG / "chunk_behavior_baseline.json"
REPORT_PATH = DIAG / "chunk_behavior_report.md"


def ensure_dirs() -> None:
    DIAG.mkdir(parents=True, exist_ok=True)


def run_pipeline() -> List[Chunk]:
    print(">>> STEP 1: Running visual pipeline for behavior check...")
    visual_integrator = VisualPipelineIntegrator()
    visual_result = visual_integrator.run(
        pdf_path=PDF_PATH,
        annotation_path="backbone/visual/schemas/page3_annotation.json",
        schema_path="backbone/visual/schemas/visual_note_schema.json",
        score_notes=True,
        make_debug_overlays=False,
        debug_output_dir="visual_debug",
    )

    pages = visual_result.get("pages", {})
    print("    - Visual pages:", sorted(pages.keys()))

    print("\n>>> STEP 2: Running text chunker for behavior check...")
    bridge = VisualChunkerBridge()
    chunker = Chunker(visual_pages=pages, visual_bridge=bridge)
    chunks: List[Chunk] = chunker.process(PDF_PATH)

    print("    - Total chunks:", len(chunks))
    return chunks


def compute_metrics(chunks: List[Chunk]) -> Dict[str, Any]:
    per_page: Dict[int, Dict[str, Any]] = {}

    for ch in chunks:
        page = getattr(ch, "page", None)
        if page is None:
            continue

        page_metrics = per_page.setdefault(
            page,
            {
                "chunk_count": 0,
                "with_visual": 0,
                "note_like_count": 0,
                "sheet_type_counts": {},
            },
        )

        page_metrics["chunk_count"] += 1

        metadata = getattr(ch, "metadata", {}) or {}

        # visual coverage
        if metadata.get("visual_region_class") is not None:
            page_metrics["with_visual"] += 1

        # note-like types
        ch_type = getattr(ch, "type", None) or metadata.get("chunk_type")
        if ch_type in {"note", "merged_note", "merged"}:
            page_metrics["note_like_count"] += 1

        # sheet type
        sheet_type = metadata.get("sheet_type") or "unknown"
        sheet_counts = page_metrics["sheet_type_counts"]
        sheet_counts[sheet_type] = sheet_counts.get(sheet_type, 0) + 1

    # derived values
    for _, m in per_page.items():
        cc = float(m["chunk_count"]) if m["chunk_count"] else 1.0
        m["visual_coverage"] = m["with_visual"] / cc
        m["note_density"] = m["note_like_count"] / cc

    page_ids = sorted(per_page.keys())
    total_chunks = sum(m["chunk_count"] for m in per_page.values())
    avg_visual_coverage = 0.0
    avg_note_density = 0.0
    if page_ids:
        avg_visual_coverage = sum(
            m["visual_coverage"] for m in per_page.values()
        ) / float(len(page_ids))
        avg_note_density = sum(
            m["note_density"] for m in per_page.values()
        ) / float(len(page_ids))

    per_page_str_keys = {str(k): v for k, v in per_page.items()}

    return {
        "pdf_path": PDF_PATH,
        "pages": page_ids,
        "total_chunks": total_chunks,
        "avg_visual_coverage": avg_visual_coverage,
        "avg_note_density": avg_note_density,
        "per_page": per_page_str_keys,
    }


def save_baseline(metrics: Dict[str, Any]) -> None:
    BASELINE_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(">>> No baseline found. Current metrics saved as baseline:")
    print("    ", BASELINE_PATH)


def load_baseline() -> Dict[str, Any] | None:
    if not BASELINE_PATH.exists():
        return None
    try:
        return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(">>> WARNING: Failed to read baseline:", exc)
        return None


def compare_metrics(
    baseline: Dict[str, Any], current: Dict[str, Any]
) -> Dict[str, Any]:
    diff: Dict[str, Any] = {
        "summary": {},
        "per_page": {},
    }

    b_total = baseline.get("total_chunks", 0)
    c_total = current.get("total_chunks", 0)
    b_vis = baseline.get("avg_visual_coverage") or 0.0
    c_vis = current.get("avg_visual_coverage") or 0.0
    b_note = baseline.get("avg_note_density") or 0.0
    c_note = current.get("avg_note_density") or 0.0

    diff["summary"]["baseline_total_chunks"] = b_total
    diff["summary"]["current_total_chunks"] = c_total
    diff["summary"]["delta_total_chunks"] = c_total - b_total

    diff["summary"]["baseline_avg_visual_coverage"] = b_vis
    diff["summary"]["current_avg_visual_coverage"] = c_vis
    diff["summary"]["baseline_avg_note_density"] = b_note
    diff["summary"]["current_avg_note_density"] = c_note

    base_pages = baseline.get("per_page", {})
    curr_pages = current.get("per_page", {})

    all_pages = sorted(
        set(base_pages.keys()) | set(curr_pages.keys()),
        key=lambda x: int(x),
    )

    for page in all_pages:
        bp = base_pages.get(page, {})
        cp = curr_pages.get(page, {})

        b_count = bp.get("chunk_count", 0)
        c_count = cp.get("chunk_count", 0)
        b_vis_cov = bp.get("visual_coverage", 0.0) or 0.0
        c_vis_cov = cp.get("visual_coverage", 0.0) or 0.0
        b_note_den = bp.get("note_density", 0.0) or 0.0
        c_note_den = cp.get("note_density", 0.0) or 0.0

        diff["per_page"][page] = {
            "baseline_chunk_count": b_count,
            "current_chunk_count": c_count,
            "delta_chunk_count": c_count - b_count,
            "baseline_visual_coverage": b_vis_cov,
            "current_visual_coverage": c_vis_cov,
            "delta_visual_coverage": c_vis_cov - b_vis_cov,
            "baseline_note_density": b_note_den,
            "current_note_density": c_note_den,
            "delta_note_density": c_note_den - b_note_den,
        }

    return diff


def write_report(
    metrics: Dict[str, Any],
    baseline: Dict[str, Any] | None,
    diff: Dict[str, Any] | None,
) -> None:
    lines: List[str] = []
    lines.append("# Chunk Behavior Report")
    lines.append("")

    if baseline is None:
        lines.append("Baseline was just created in this run.")
        lines.append("Future runs will compare against it.")
        lines.append("")
    else:
        lines.append("Baseline exists. This report compares the current run")
        lines.append("against the stored baseline metrics.")
        lines.append("")

    lines.append("## Current Metrics (Global)")
    lines.append("")
    lines.append(f"- PDF path: {metrics.get('pdf_path')}")
    lines.append(f"- Total chunks: {metrics.get('total_chunks')}")
    lines.append(
        f"- Average visual coverage: {metrics.get('avg_visual_coverage', 0.0):.3f}"
    )
    lines.append(
        f"- Average note density: {metrics.get('avg_note_density', 0.0):.3f}"
    )
    lines.append("")

    if baseline is not None and diff is not None:
        s = diff["summary"]

        b_total = s.get("baseline_total_chunks", 0)
        c_total = s.get("current_total_chunks", 0)
        d_total = s.get("delta_total_chunks", 0)

        b_vis = s.get("baseline_avg_visual_coverage", 0.0) or 0.0
        c_vis = s.get("current_avg_visual_coverage", 0.0) or 0.0

        b_note = s.get("baseline_avg_note_density", 0.0) or 0.0
        c_note = s.get("current_avg_note_density", 0.0) or 0.0

        lines.append("## Global Drift Summary")
        lines.append("")
        lines.append(f"- Baseline total chunks: {b_total}")
        lines.append(f"- Current total chunks: {c_total}")
        lines.append(f"- Delta total chunks: {d_total}")
        lines.append("")
        lines.append(f"- Baseline avg visual coverage: {b_vis:.3f}")
        lines.append(f"- Current avg visual coverage: {c_vis:.3f}")
        lines.append("")
        lines.append(f"- Baseline avg note density: {b_note:.3f}")
        lines.append(f"- Current avg note density: {c_note:.3f}")
        lines.append("")

        lines.append("## Per-page Drift")
        lines.append("")
        lines.append(
            "| Page | Base chunks | Curr chunks | Delta | "
            "Base vis | Curr vis | Base note | Curr note |"
        )
        lines.append(
            "|------|-------------|-------------|-------|"
            "----------|----------|-----------|-----------|"
        )

        for page in sorted(diff["per_page"].keys(), key=lambda x: int(x)):
            d = diff["per_page"][page]
            lines.append(
                "| {page} | {bc} | {cc} | {dc} | {bv:.3f} | {cv:.3f} | {bn:.3f} | {cn:.3f} |".format(
                    page=page,
                    bc=d["baseline_chunk_count"],
                    cc=d["current_chunk_count"],
                    dc=d["delta_chunk_count"],
                    bv=d["baseline_visual_coverage"],
                    cv=d["current_visual_coverage"],
                    bn=d["baseline_note_density"],
                    cn=d["current_note_density"],
                )
            )

        lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(">>> Chunk behavior report written to:", REPORT_PATH)


def main() -> None:
    ensure_dirs()
    chunks = run_pipeline()
    current_metrics = compute_metrics(chunks)
    baseline = load_baseline()

    if baseline is None:
        save_baseline(current_metrics)
        write_report(current_metrics, None, None)
        print(">>> Behavior baseline created. No comparison yet.")
        return

    diff = compare_metrics(baseline, current_metrics)
    write_report(current_metrics, baseline, diff)
    print(">>> Behavior comparison complete. See report for details.")
    print("    ", REPORT_PATH)


if __name__ == "__main__":
    main()
