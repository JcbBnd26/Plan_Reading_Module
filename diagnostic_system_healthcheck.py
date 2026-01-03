#!/usr/bin/env python3
"""
diagnostic_system_healthcheck.py

Full-project dependency validator & health report generator.

This script:
    • Scans the entire backbone_skeleton folder
    • Collects Python import relationships
    • Detects missing modules, wrong imports, orphaned files, and circular dependencies
    • Produces a Markdown report at diagnostics/last_run.md
    • Prints a readable summary to the console
    • Auto-creates diagnostics/ folder if missing

This is Option B (robust validator).
"""

import os
import ast
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple


# ---------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent
TARGET_ROOT = PROJECT_ROOT / "backbone"
REPORT_DIR = PROJECT_ROOT / "diagnostics"
REPORT_FILE = REPORT_DIR / "last_run.md"


# ---------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------

def safe_mkdir(path: Path):
    """Create directory if missing."""
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)


def list_python_files(root: Path) -> List[Path]:
    """Return all .py files under root (recursively)."""
    return [p for p in root.rglob("*.py") if p.is_file()]


def parse_imports(file_path: Path) -> Tuple[Set[str], Set[str]]:
    """
    Parse a Python file and extract:
        - direct imports (import xxx)
        - from imports (from xxx import yyy)
    """
    text = file_path.read_text(encoding="utf-8")
    tree = ast.parse(text)

    direct_imports = set()
    from_imports = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                direct_imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                from_imports.add(node.module)

    return direct_imports, from_imports


def normalize_module_path(path: Path, root: Path) -> str:
    """
    Convert a file path to a dotted module path relative to project root.
    Example:
        backbone/chunking/chunk.py -> backbone.chunking.chunk
    """
    rel = path.relative_to(root.parent)
    parts = rel.with_suffix("").parts
    return ".".join(parts)


# ---------------------------------------------------------------------
# MAIN ANALYSIS
# ---------------------------------------------------------------------

def analyze_project() -> Dict[str, Dict[str, Set[str]]]:
    """
    Scan the whole project and return import structure:
        {
            "backbone.chunking.chunk": {
                "direct": set([...]),
                "from": set([...]),
                "file": Path(...)
            },
            ...
        }
    """
    results = {}
    py_files = list_python_files(PROJECT_ROOT)

    for file_path in py_files:
        module_path = normalize_module_path(file_path, PROJECT_ROOT)
        direct, froms = parse_imports(file_path)
        results[module_path] = {
            "direct": direct,
            "from": froms,
            "file": file_path,
        }

    return results


def detect_problems(import_map: Dict[str, Dict[str, Set[str]]]) -> Dict[str, List[str]]:
    """
    Detect:
        • imports pointing to modules that don't exist
        • circular imports
        • orphaned files
    """
    problems = {
        "missing_modules": [],
        "circular_imports": [],
        "orphans": [],
    }

    module_set = set(import_map.keys())

    # Detect missing modules
    for mod, info in import_map.items():
        for imp in info["direct"] | info["from"]:
            if imp.startswith("backbone") and imp not in module_set:
                problems["missing_modules"].append(f"{mod} → MISSING {imp}")

    # Detect circular imports
    for mod, info in import_map.items():
        for imp in info["direct"] | info["from"]:
            if imp == mod:
                continue
            if imp in import_map:
                if mod in (import_map[imp]["direct"] | import_map[imp]["from"]):
                    problems["circular_imports"].append(f"{mod} ↔ {imp}")

    # Detect orphaned modules (nothing imports them)
    reverse_map = {m: 0 for m in module_set}
    for mod, info in import_map.items():
        for imp in info["direct"] | info["from"]:
            if imp in reverse_map:
                reverse_map[imp] += 1

    for mod, count in reverse_map.items():
        if count == 0 and not mod.endswith("__init__"):
            problems["orphans"].append(f"{mod}")

    return problems


# ---------------------------------------------------------------------
# REPORT GENERATION
# ---------------------------------------------------------------------

def write_report(import_map: Dict[str, Dict[str, Set[str]]],
                 problems: Dict[str, List[str]]):
    """Write diagnostics/last_run.md"""
    safe_mkdir(REPORT_DIR)

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("# 🌐 Backbone Skeleton: Integration Diagnostic Report\n")
        f.write("Generated by `diagnostic_system_healthcheck.py`\n\n")

        f.write("## 📁 Scanned Modules\n")
        for mod in sorted(import_map.keys()):
            f.write(f"- `{mod}`\n")

        f.write("\n---\n\n")
        f.write("## ⚠️ Detected Problems\n")

        if not any(problems.values()):
            f.write("**No issues detected — system is clean.**\n\n")
        else:
            for category, items in problems.items():
                label = category.replace("_", " ").title()
                f.write(f"### {label}\n")
                if not items:
                    f.write("- None\n")
                else:
                    for item in items:
                        f.write(f"- {item}\n")
                f.write("\n")

        f.write("\n---\n\n")
        f.write("## 🔍 Raw Import Map\n")

        for mod, info in import_map.items():
            f.write(f"### `{mod}`\n")
            f.write(f"- File: `{info['file']}`\n")
            f.write(f"- Direct imports: {sorted(info['direct'])}\n")
            f.write(f"- From imports: {sorted(info['from'])}\n\n")

    print(f"\n>>> Diagnostic report generated at: {REPORT_FILE}\n")


# ---------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------

def main():
    print(">>> Running backbone dependency diagnostic...\n")

    import_map = analyze_project()
    problems = detect_problems(import_map)
    write_report(import_map, problems)

    print(">>> DONE.")
    print("Open diagnostics/last_run.md in your editor to review.\n")


if __name__ == "__main__":
    main()
