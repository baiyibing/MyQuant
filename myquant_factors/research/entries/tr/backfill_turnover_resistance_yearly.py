#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backfill turnover resistance one calendar year at a time (newest year first).

Each year writes TR rows to a staging Parquet (``tr_staging/turnover_resistance_daily_YYYY.parquet``),
then merges into the canonical store. TR Bollinger Bands run once on the merged canonical file
after all years complete (avoids year-boundary history gaps).
"""

from __future__ import annotations

from myquant_factors._runtime import research_root, resolve_source_parquet

import argparse
import os
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = research_root()
BACKFILL = Path(__file__).with_name("backfill_turnover_resistance_bands.py")
PROGRESS = ROOT / "backtest_output" / "tr_backfill_yearly_progress.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from myquant_factors._runtime import ensure_repo_on_syspath, resolve_oskh_python

ensure_repo_on_syspath(__file__)
PY = str(resolve_oskh_python())

from myquant_factors.research._inputs import (  # noqa: E402
    merge_parquet_into_canonical,
    resolve_parquet_path,
    resolve_year_staging_path,
)


def _run(cmd: list[str]) -> int:
    print(">>>", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(ROOT), env={**os.environ, "MYQUANT_RESEARCH_ROOT": str(ROOT)})
    return int(proc.returncode)


def _write_progress(payload: dict) -> None:
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Year-by-year TR backfill (descending years)")
    parser.add_argument("--from-year", type=int, default=2026, help="Start year (default 2026, run first)")
    parser.add_argument("--to-year", type=int, default=2020, help="Stop year inclusive (default 2020)")
    parser.add_argument(
        "--staging-dir",
        default="",
        help="Override staging directory (default: stock_data/tr_staging)",
    )
    parser.add_argument(
        "--canonical-path",
        default="",
        help="Override canonical Parquet path (default: turnover_resistance_daily.parquet)",
    )
    parser.add_argument(
        "--final-recompute-bands",
        action="store_true",
        default=True,
        help="After all years, run full-store TR BB recompute (default on)",
    )
    parser.add_argument(
        "--no-final-recompute-bands",
        action="store_true",
        help="Skip final full-store TR BB recompute",
    )
    parser.add_argument(
        "--merge-only",
        action="store_true",
        help="Only merge existing staging files into canonical (no TR backfill)",
    )
    args = parser.parse_args(argv)

    if args.from_year < args.to_year:
        print("[error] --from-year must be >= --to-year (descending order)")
        return 1

    staging_dir = args.staging_dir or None
    # Resolve host policy once; the facade passes the explicit filename to infra.
    canonical_path = resolve_parquet_path(args.canonical_path or None)
    t0 = time.perf_counter()

    for year in range(args.from_year, args.to_year - 1, -1):
        staging_path = resolve_year_staging_path(year, staging_dir)

        if not args.merge_only:
            _write_progress(
                {
                    "status": "running",
                    "current_year": year,
                    "phase": "tr",
                    "staging_path": str(staging_path),
                }
            )
            rc = _run(
                [
                    PY,
                    "-u",
                    str(BACKFILL),
                    "--year",
                    str(year),
                    "--tr-only",
                    "--skip-existing",
                    "--parquet-path",
                    str(staging_path),
                ]
            )
            if rc != 0:
                _write_progress({"status": "failed", "year": year, "phase": "tr", "exit_code": rc})
                return rc

        _write_progress(
            {
                "status": "running",
                "current_year": year,
                "phase": "merge",
                "staging_path": str(staging_path),
                "canonical_path": str(resolve_parquet_path(canonical_path)),
            }
        )
        merge_stats = merge_parquet_into_canonical(staging_path, canonical_path=canonical_path)
        print(
            f"[merge {year}] source_rows={merge_stats['source_rows']} "
            f"keys_updated={merge_stats['keys_updated']} "
            f"total={merge_stats['total_after']}",
            flush=True,
        )

        _write_progress(
            {
                "status": "year_done",
                "completed_year": year,
                "merge": merge_stats,
                "elapsed_s": round(time.perf_counter() - t0, 1),
            }
        )
        print(f"[year-done] {year}", flush=True)

    if not args.no_final_recompute_bands and not args.merge_only:
        _write_progress({"status": "running", "phase": "final-recompute-bands"})
        cmd = [PY, "-u", str(BACKFILL), "--recompute-bands"]
        if canonical_path:
            cmd.extend(["--parquet-path", str(resolve_parquet_path(canonical_path))])
        rc = _run(cmd)
        if rc != 0:
            _write_progress({"status": "failed", "phase": "final-recompute-bands", "exit_code": rc})
            return rc

    _write_progress(
        {
            "status": "completed",
            "from_year": args.from_year,
            "to_year": args.to_year,
            "staging_dir": str(resolve_year_staging_path(args.from_year, staging_dir).parent),
            "canonical_path": str(resolve_parquet_path(canonical_path)),
            "elapsed_s": round(time.perf_counter() - t0, 1),
        }
    )
    print(
        f"[all-done] years {args.from_year}..{args.to_year} "
        f"elapsed={time.perf_counter()-t0:.1f}s",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
