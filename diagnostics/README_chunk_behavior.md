# Chunk Behavior Diagnostics

This package adds a read-only diagnostic script to track how the text + visual
chunking pipeline behaves over time.

It focuses on:
- Chunk counts per page
- Visual coverage per page (fraction of chunks with visual metadata)
- Note density per page (fraction of chunks that look like note / merged note)

## Files

- `diagnostic_chunk_behavior.py`
  Runs the full pipeline on `test.pdf`, computes metrics, and compares them
  against a stored baseline.

## Usage

From the project root (`C:\Projects\backbone_skeleton`):

```powershell
cd C:\Projects\backbone_skeleton

# First run: creates the baseline and a report
py diagnostics\diagnostic_chunk_behavior.py

# Later runs: compare current behavior against baseline
py diagnostics\diagnostic_chunk_behavior.py
```

Outputs are written under `diagnostics\`:

- `chunk_behavior_baseline.json` – the reference metrics
- `chunk_behavior_report.md` – human-friendly diff for each run
