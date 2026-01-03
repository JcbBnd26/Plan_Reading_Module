"""
diagnostic_system_autofix.py

Automatic import repair script for Backbone Skeleton.

This script scans Python files in the project, looks for non-canonical
`from ... import ...` statements that reference known backbone symbols,
and rewrites them to use a single canonical module path.

It is intentionally conservative:
    * Only touches `from X import Y` lines.
    * Only rewrites symbols listed in CANONICAL_MAP.
    * Never deletes imports or changes any other code.

Outputs:
    * Backups for each modified file under: diagnostics/backups/<relpath>
    * A markdown report at: diagnostics/fix_report.md
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from difflib import unified_diff
from typing import Dict, Iterable, List, Tuple

# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]  # project root: backbone_skeleton
DIAG = ROOT / "diagnostics"
BACKUPS = DIAG / "backups"
REPORT = DIAG / "fix_report.md"

# We primarily care about code under backbone/, but we will also scan
# top-level helper scripts (run_visual_alignment_check.py, etc.).
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
    """Create diagnostics directories if they do not exist."""
    DIAG.mkdir(parents=True, exist_ok=True)
    BACKUPS.mkdir(parents=True, exist_ok=True)


def iter_py_files() -> Iterable[Path]:
    """Yield all .py files we want to scan.

    Skips:
        * diagnostics/ (including this script and backups)
        * __pycache__ folders
        * virtualenvs, if any
    """
    seen: set[Path] = set()

    for root in CODE_ROOTS:
        if not root.exists():
            continue

        for dirpath, dirnames, filenames in os.walk(root):
            dp = Path(dirpath)

            # Skip diagnostics, backups, and typical env dirs
            if dp.name in {"diagnostics", "backups", "__pycache__", ".venv", "venv", ".env"}:
                dirnames[:] = []  # do not descend further
                continue

            # Avoid scanning the same directory twice
            if dp in seen:
                continue
            seen.add(dp)

            for name in filenames:
                if not name.endswith(".py"):
                    continue
                path = dp / name

                # Skip this script itself
                if path == Path(__file__).resolve():
                    continue

                yield path


def canonical_resolve(symbol: str) -> str | None:
    """Return canonical module path for a symbol, or None if unknown."""
    return CANONICAL_MAP.get(symbol)


def rewrite_import_line(line: str) -> Tuple[str, List[str]]:
    """Possibly rewrite a single `from X import ...` line.

    Returns:
        (new_line, changes)

        new_line:
            Possibly modified import line (always ends with newline).
        changes:
            List of human-readable change descriptions (empty if no change).
    """
    m = re.match(r"^(\s*)from\s+([A-Za-z0-9_.]+)\s+import\s+(.+)$", line)
    if not m:
        return line, []

    indent, module, rest = m.groups()

    # Split on commas but keep "as" portions intact
    parts = [p.strip() for p in rest.split(",")]
    if not parts:
        return line, []

    # Map each imported symbol (before "as") to its canonical module, if any
    canonical_modules: Dict[str, List[str]] = {}
    all_have_canonical = True

    for part in parts:
        # Handle things like "Chunk as BaseChunk"
        base = part.split("as")[0].strip()
        canon_mod = canonical_resolve(base)
        if canon_mod is None:
            all_have_canonical = False
            break
        canonical_modules.setdefault(canon_mod, []).append(part)

    # Only rewrite if:
    #   * every imported name has a canonical module, and
    #   * all canonical modules are the same.
    if not all_have_canonical or len(canonical_modules) != 1:
        return line, []

    target_module = next(iter(canonical_modules.keys()))

    # If we already import from the canonical module, don't touch it
    if target_module == module:
        return line, []

    new_line = f"{indent}from {target_module} import {', '.join(parts)}\n"
    change = (
        f"REWRITE: `from {module} import {rest.strip()}` "
        f"-> `from {target_module} import {rest.strip()}`"
    )
    return new_line, [change]


def rewrite_imports(src: str) -> Tuple[str, List[str]]:
    """Rewrite import lines in a source string.

    Returns:
        (new_src, changes)
    """
    changes: List[str] = []
    new_lines: List[str] = []

    for line in src.splitlines(keepends=True):
        new_line, line_changes = rewrite_import_line(line)
        new_lines.append(new_line)
        changes.extend(line_changes)

    return "".join(new_lines), changes


def backup_file(path: Path) -> None:
    """Copy the original file into diagnostics/backups, preserving structure."""
    rel = path.relative_to(ROOT)
    dest = BACKUPS / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)


def main() -> None:
    """Entry point."""
    ensure_dirs()

    all_changes: List[str] = []

    for pyfile in iter_py_files():
        src = pyfile.read_text(encoding="utf-8")

        new_src, changes = rewrite_imports(src)

        if not changes:
            continue  # no modifications needed

        backup_file(pyfile)
        pyfile.write_text(new_src, encoding="utf-8")

        # Compute diff for the report
        diff = unified_diff(
            src.splitlines(),
            new_src.splitlines(),
            fromfile=str(pyfile),
            tofile=str(pyfile),
            lineterm="",
        )
        diff_text = "\n".join(diff)

        all_changes.append(
            f"## {pyfile}\n\n"
            + "\n".join(f"- {c}" for c in changes)
            + "\n\n### Diff:\n```diff\n"
            + diff_text
            + "\n```"
        )

    if not all_changes:
        REPORT.write_text("# AutoFix Report\n\nNo changes required.\n", encoding="utf-8")
        print(">>> AutoFix completed. No changes needed.")
    else:
        REPORT.write_text(
            "# AutoFix Report\n\n" + "\n\n".join(all_changes),
            encoding="utf-8",
        )
        print(">>> AutoFix complete.")
        print(f">>> Report written to: {REPORT}")
        print(f">>> Backups in: {BACKUPS}")


if __name__ == "__main__":
    main()
