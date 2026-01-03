# tools/assert_pipeline_invariants.py
from pathlib import Path
import sys

MOST = Path("exports/MostRecent")

required = [
    "stage0_base.json",
    "stage1_headers_tagged.json",
    "stage2_headers_split.json",
    "stage3_notes_merged.json",
    "final.json"
]

missing = [f for f in required if not (MOST / f).exists()]

if missing:
    print("PIPELINE INVARIANT FAILED")
    print("Missing files:", missing)
    sys.exit(1)

pngs = list(MOST.glob("overlay_*.png"))
if not pngs:
    print("NO VISUAL OUTPUT PRODUCED")
    sys.exit(1)

print("Pipeline invariants OK")
