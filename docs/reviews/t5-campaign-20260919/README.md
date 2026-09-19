# T5 campaign 2026-09-18/19 — lightweight facts bundle

Read-only artifacts for VM Codex / Cursor review. **Do not invent numbers** — use FACTS.json and per-knife files only.

## Include
- FACTS.json
- *verdict.md / erdict.json
- _diag*/REPORT.md, pseudo*/REPORT.md + summary.json
- sidecar manifest.json + SHA256.txt (parquet themselves not in git)

## Exclude
- *.parquet, pred_*.csv, mlruns/

## Online freeze
pred 8a061ea4 and 10/3 untouched.
