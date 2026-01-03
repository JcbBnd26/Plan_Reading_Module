# tools/diagnose_run_integrity.py
from pathlib import Path
import hashlib
import json
from datetime import datetime

EXPORTS = Path("exports")

def file_hash(p: Path):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:12]

def scan(dirpath: Path):
    rows = []
    for p in sorted(dirpath.glob("*")):
        if p.is_file():
            rows.append({
                "name": p.name,
                "size": p.stat().st_size,
                "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
                "hash": file_hash(p)
            })
    return rows

def main():
    most = EXPORTS / "MostRecent"
    runs = EXPORTS / "Runs"

    print("\n=== MOSTRECENT ===")
    for r in scan(most):
        print(r)

    print("\n=== LATEST RUN ===")
    run_dirs = sorted([d for d in runs.iterdir() if d.is_dir()], key=lambda p: p.name)
    if not run_dirs:
        print("No runs found.")
        return

    latest = run_dirs[-1]
    print(f"Run: {latest.name}")
    for r in scan(latest):
        print(r)

if __name__ == "__main__":
    main()
