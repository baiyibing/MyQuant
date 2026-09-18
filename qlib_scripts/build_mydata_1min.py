# -*- coding: utf-8 -*-
"""Build ~/.qlib-style 1min bins from the E: minute lake.

Writes ~/.qlib/qlib_data/my_data_1min only. Never touches my_data / pred.pkl.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from stage_1min_from_lake import DEFAULT_LAKE, DEFAULT_STAGING, stage_lake

DEFAULT_QLIB_DIR = Path.home() / ".qlib" / "qlib_data" / "my_data_1min"
DUMP_BIN = Path(__file__).resolve().parent / "dump_bin.py"
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
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage + dump qlib 1min bins (not my_data)")
    parser.add_argument("--lake-root", type=Path, default=DEFAULT_LAKE)
    parser.add_argument("--staging-dir", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--qlib-dir", type=Path, default=DEFAULT_QLIB_DIR)
    parser.add_argument("--start", default="20260801")
    parser.add_argument("--end", default="20260909")
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--all-symbols", action="store_true", help="Dump every lake partition (large)")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--skip-stage", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    qlib_dir = args.qlib_dir.expanduser()
    if qlib_dir.resolve() == (Path.home() / ".qlib/qlib_data/my_data").resolve():
        raise SystemExit("refusing to write daily my_data")
    symbols = None if args.all_symbols else (args.symbols or list(SMOKE_SYMBOLS))
    if not args.skip_stage:
        written = stage_lake(
            args.lake_root,
            args.staging_dir,
            symbols=symbols,
            start=args.start,
            end=args.end,
            max_workers=int(args.max_workers),
        )
        if not written:
            raise SystemExit("no 1m parquet staged; check lake path / symbols / window")
        print(f"staged {len(written)} → {args.staging_dir}")
    cmd = [
        sys.executable,
        str(DUMP_BIN),
        "dump_all",
        f"--data_path={args.staging_dir}",
        f"--qlib_dir={qlib_dir}",
        "--freq=1min",
        "--file_suffix=.parquet",
        "--date_field_name=date",
        "--symbol_field_name=symbol",
        "--exclude_fields=symbol",
        f"--max_workers={int(args.max_workers)}",
    ]
    print("dump", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"qlib 1min dir → {qlib_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
