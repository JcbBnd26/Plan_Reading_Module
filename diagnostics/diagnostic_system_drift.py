"""
diagnostic_system_drift.py

Read-only diagnostic script to detect *import drift* in the Backbone Skeleton.

It does NOT modify any files.

It scans Python files for `from X import Y` lines where Y has a configured
canonical module, and X does not match that canonical module.

Outputs:
    - diagnostics/drift_report.md (markdown report)
    - Console summary with number of files that have drift
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]  # project root: backbone_skeleton
DIAG = ROOT / "diagnostics"
REPORT = DIAG / "drift_report.md"

CODE_ROOTS = [
    ROOT / "backbone",
    ROOT,
]

# ---------------------------------------------------------------------
# Canonical symbol -> module map
# ---------------------------------------------------------------------
CANONICAL_MAP: Dict[str, str] = {
    # chunking
    "Chunk": "backbone.chunking.chunk",
    "MergedChunk": "backbone.chunking.chunk",
    "BBox": "backbone.chunking.chunk",
    "merge_chunks": "backbone.chunking.chunk_utils",
    "detect_sheet_type": "backbone.chunking.sheet_type_detector",
    "ColumnDetector": "backbone.chunking.column_detector",
    "SemanticGrouper": "backbone.chunking.semantic_grouper",

    # visual
    "VisualPipelineIntegrator": "backbone.visual.visual_pipeline_integrator",
    "AutoBoxDetector": "backbone.visual.auto_box_detector",
    "VisualChunkerBridge": "backbone.visual.visual_chunker_bridge",
    "VisualConfidenceModel": "backbone.visual.visual_confidence",
}


def ensure_dirs() -> None:
    """Ensure diagnostics directory exists."""
    DIAG.mkdir(parents=True, exist_ok=True)


def iter_py_files() -> Iterable[Path]:
    """Yield all .py files we want to scan.

    Skips:
        * diagnostics/ (including this script)
        * __pycache__
        * venv/.venv/.env
    """
    seen: set[Path] = set()

    for root in CODE_ROOTS:
        if not root.exists():
            continue

        for dirpath, dirnames, filenames in os.walk(root):
            dp = Path(dirpath)

            # Skip diagnostics and typical env dirs
            if dp.name in {"diagnostics", "__pycache__", ".venv", "venv", ".env"}:
                dirnames[:] = []
                continue

            if dp in seen:
                continue
            seen.add(dp)

            for name in filenames:
                if not name.endswith(".py"):
                    continue
                path = dp / name

                # Skip this script itself for safety
                if path == Path(__file__).resolve():
                    continue

                yield path


def canonical_resolve(symbol: str) -> str | None:
    """Return canonical module path for a symbol, or None if unknown."""
    return CANONICAL_MAP.get(symbol)


def analyze_import_line(
    line: str, lineno: int
) -> List[Tuple[int, str, str, str]]:
    """Analyze one import line and return drift records if any.

    Returns list of tuples:
        (lineno, module, imported, canonical_module)
    """
    m = re.match(r"^(\s*)from\s+([A-Za-z0-9_.]+)\s+import\s+(.+)$", line)
    if not m:
        return []

    module = m.group(2)
    rest = m.group(3).strip()

    # Split comma-separated imports, keep "as" parts
    parts = [p.strip() for p in rest.split(",") if p.strip()]
    if not parts:
        return []

    records: List[Tuple[int, str, str, str]] = []

    for part in parts:
        base = part.split("as")[0].strip()
        canon_mod = canonical_resolve(base)
        if canon_mod is None:
            continue  # we do not care about this symbol

        if canon_mod != module:
            records.append((lineno, module, part, canon_mod))

    return records


def analyze_file(path: Path) -> List[Tuple[int, str, str, str]]:
    """Return drift records for a single file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    all_records: List[Tuple[int, str, str, str]] = []

    for idx, line in enumerate(lines, start=1):
        recs = analyze_import_line(line, idx)
        all_records.extend(recs)

    return all_records


def write_report(results: Dict[Path, List[Tuple[int, str, str, str]]]) -> None:
    """Write markdown drift report."""
    if not results:
        REPORT.write_text(
            "# Drift Report\n\nNo import drift detected.\n",
            encoding="utf-8",
        )
        return

    parts: List[str] = ["# Drift Report", ""]

    for path, records in sorted(results.items(), key=lambda x: str(x[0])):
        rel = path.relative_to(ROOT)
        parts.append(f"## {rel}")
        parts.append("")
        parts.append("| Line | Current import | Canonical module |")
        parts.append("|------|-----------------|------------------|")

        for lineno, module, imported, canon_mod in records:
            parts.append(
                f"| {lineno} | from {module} import {imported} | {canon_mod} |"
            )

        parts.append("")

    REPORT.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    ensure_dirs()

    results: Dict[Path, List[Tuple[int, str, str, str]]] = {}

    for pyfile in iter_py_files():
        recs = analyze_file(pyfile)
        if recs:
            results[pyfile] = recs

    if not results:
        write_report(results)
        print(">>> Drift check: no import drift detected.")
        print(f">>> Report written to: {REPORT}")
    else:
        write_report(results)
        print(
            f">>> Drift check: import drift detected in {len(results)} file(s). "
            f"See report: {REPORT}"
        )


if __name__ == "__main__":
    main()
