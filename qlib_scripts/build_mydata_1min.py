# -*- coding: utf-8 -*-
"""First-time / smoke dump of ~/.qlib/qlib_data/my_data_1min.

Writes my_data_1min only. Never touches my_data / pred.pkl.
Daily updates of an existing 1min provider: refresh_mydata_1min.py (incremental).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from refresh_mydata_1min import clamp_workers, dump_all_1min, refuse_if_daily
from stage_1min_from_lake import (
    DEFAULT_INDEX_LAKE,
    DEFAULT_LAKE,
    DEFAULT_MAX_WORKERS,
    DEFAULT_STAGING,
    stage_stock_and_index,
)

DEFAULT_QLIB_DIR = Path.home() / ".qlib" / "qlib_data" / "my_data_1min"
SMOKE_SYMBOLS = (
    "SZ000001",
    "SH600000",
    "SZ000002",
    "SH600519",
    "SZ000858",
    "SZ300750",
    "SH601318",
    "SZ000725",
    "SH600036",
    "SH601166",
    "SZ002415",
    "SZ000063",
    "SH600276",
    "SZ300059",
    "SZ002594",
    "SH601012",
    "SZ000333",
    "SH600900",
    "SZ002714",
    "SH601888",
    "SH000300",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage + dump qlib 1min bins (not my_data)")
    parser.add_argument("--lake-root", type=Path, default=DEFAULT_LAKE)
    parser.add_argument("--index-lake", type=Path, default=DEFAULT_INDEX_LAKE)
    parser.add_argument("--skip-index", action="store_true")
    parser.add_argument("--staging-dir", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--qlib-dir", type=Path, default=DEFAULT_QLIB_DIR)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--all-symbols", action="store_true", help="Dump every lake partition (large)")
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    parser.add_argument("--skip-stage", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    qlib_dir = args.qlib_dir.expanduser()
    refuse_if_daily(qlib_dir)
    workers = clamp_workers(args.max_workers)
    if int(args.max_workers) > DEFAULT_MAX_WORKERS:
        print(f"clamped --max-workers {args.max_workers} → {workers}", flush=True)
    symbols = None if args.all_symbols else (args.symbols or list(SMOKE_SYMBOLS))
    if not args.skip_stage:
        written = stage_stock_and_index(
            args.lake_root,
            None if args.skip_index else args.index_lake,
            args.staging_dir,
            symbols=symbols,
            start=args.start,
            end=args.end,
            max_workers=workers,
        )
        if not written:
            raise SystemExit("no 1m parquet staged; check lake path / symbols / window")
        print(f"staged {len(written)} → {args.staging_dir}")
    dump_all_1min(args.staging_dir, qlib_dir, workers)
    print(f"qlib 1min dir → {qlib_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
