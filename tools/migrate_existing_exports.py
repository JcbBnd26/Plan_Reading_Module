#!/usr/bin/env python
"""
migrate_existing_exports.py

One-time helper to clean up a messy exports/ directory.

- Creates:
    exports/MostRecent/
    exports/PreviousExports/
- Moves EVERYTHING currently in exports/ (except those two folders)
  into exports/MostRecent/.

After running this once, exports/ root should only contain:
    MostRecent/
    PreviousExports/
"""

from __future__ import annotations

import shutil
from pathlib import Path


def ensure_dir(path: Path) -> None:
    """Create directory if it does not exist."""
    path.mkdir(parents=True, exist_ok=True)


def main() -> None:
    tools_dir = Path(__file__).resolve().parent
    project_root = tools_dir.parent
    exports_root = project_root / "exports"

    most_recent = exports_root / "MostRecent"
    previous = exports_root / "PreviousExports"

    ensure_dir(exports_root)
    ensure_dir(most_recent)
    ensure_dir(previous)

    print("[INFO] Migrating existing exports into exports/MostRecent ...")

    for entry in exports_root.iterdir():
        if entry.name in {"MostRecent", "PreviousExports"}:
            continue
        target = most_recent / entry.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        shutil.move(str(entry), str(target))

    print("[INFO] Done. exports/ now only contains MostRecent/ and PreviousExports/.")


if __name__ == "__main__":
    main()
