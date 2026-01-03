#!/usr/bin/env python
"""
clean_generated_exports.py

Delete all generated files in:

    exports/MostRecent/
    exports/PreviousExports/

Does NOT delete the folders themselves.
"""

from __future__ import annotations

import shutil
from pathlib import Path


def clear_dir_contents(path: Path) -> None:
    if not path.exists():
        return
    for entry in path.iterdir():
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def main() -> None:
    tools_dir = Path(__file__).resolve().parent
    project_root = tools_dir.parent
    exports_root = project_root / "exports"

    most_recent = exports_root / "MostRecent"
    previous = exports_root / "PreviousExports"

    print("[INFO] Cleaning generated exports...")

    clear_dir_contents(most_recent)
    clear_dir_contents(previous)

    print("[INFO] Done. MostRecent and PreviousExports are now empty.")


if __name__ == "__main__":
    main()
