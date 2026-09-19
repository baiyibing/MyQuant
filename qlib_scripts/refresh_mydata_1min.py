# -*- coding: utf-8 -*-
"""Refresh ~/.qlib/qlib_data/my_data_1min from stock+index 1m lakes (OSKH_SOURCE_PARQUET_ROOT).

Never writes daily my_data / pred.pkl. Prefer incremental append when bins exist.
Do not call dump_update (it loads every staging parquet into one DataFrame).
dump_all --freq=1min builds the calendar from a few refs (see dump_bin).
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

import pandas as pd
from tqdm import tqdm

from dump_bin import DumpDataAll
from qlib.utils import code_to_fname

_MY_SCRIPTS = Path(__file__).resolve().parents[1] / "my_scripts"
if str(_MY_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_MY_SCRIPTS))
from data_root import resolve_index_1min_none, resolve_stock_1min_none  # noqa: E402
from stage_1min_from_lake import (
    DEFAULT_MAX_WORKERS,
    DEFAULT_STAGING,
    stage_stock_and_index,
)

DAILY_QLIB = Path.home() / ".qlib" / "qlib_data" / "my_data"
DEFAULT_QLIB_1MIN = Path.home() / ".qlib" / "qlib_data" / "my_data_1min"
DUMP_BIN = Path(__file__).resolve().parent / "dump_bin.py"


def refuse_if_daily(qlib_dir: Path) -> None:
    if Path(qlib_dir).expanduser().resolve() == DAILY_QLIB.resolve():
        raise SystemExit("refusing to write daily my_data")


def clamp_workers(n: int) -> int:
    return min(DEFAULT_MAX_WORKERS, max(1, int(n)))


def daily_calendar_fingerprint(daily_dir: Path | None = None) -> tuple[int, str]:
    path = (daily_dir or DAILY_QLIB) / "calendars" / "day.txt"
    if not path.exists():
        return (0, "")
    data = path.read_bytes()
    return (path.stat().st_mtime_ns, hashlib.sha256(data).hexdigest())


def assert_daily_unchanged(before: tuple[int, str], daily_dir: Path | None = None) -> None:
    after = daily_calendar_fingerprint(daily_dir)
    if after != before:
        raise SystemExit(f"daily my_data calendar changed during 1min refresh: {before} → {after}")


def read_1min_calendar(qlib_dir: Path) -> list[pd.Timestamp]:
    path = Path(qlib_dir) / "calendars" / "1min.txt"
    if not path.exists():
        return []
    return [pd.Timestamp(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def existing_1min_ready(qlib_dir: Path) -> bool:
    cal = read_1min_calendar(qlib_dir)
    feat = Path(qlib_dir) / "features"
    return bool(cal) and feat.is_dir()


def make_dumper(data_path: Path, qlib_dir: Path, mode: str, workers: int = 1) -> DumpDataAll:
    obj = DumpDataAll(
        data_path=str(data_path),
        qlib_dir=str(qlib_dir),
        freq="1min",
        max_workers=workers,
        date_field_name="date",
        file_suffix=".parquet",
        symbol_field_name="symbol",
        exclude_fields="symbol",
    )
    obj._mode = mode
    return obj


def dump_all_1min(staging_dir: Path, qlib_dir: Path, workers: int) -> None:
    cmd = [
        sys.executable,
        str(DUMP_BIN),
        "dump_all",
        f"--data_path={staging_dir}",
        f"--qlib_dir={qlib_dir}",
        "--freq=1min",
        "--file_suffix=.parquet",
        "--date_field_name=date",
        "--symbol_field_name=symbol",
        "--exclude_fields=symbol",
        f"--max_workers={clamp_workers(workers)}",
    ]
    if any("dump_update" in part for part in cmd):
        raise SystemExit("internal error: dump_update is forbidden")
    print("dump", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def append_new_1min_bars(
    staging_inc: Path,
    staging_full: Path,
    qlib_dir: Path,
    new_only: list[pd.Timestamp],
    full_cal: list[pd.Timestamp],
) -> int:
    """UPDATE_MODE append for existing bins; ALL_MODE write new symbols from full staging."""
    d = make_dumper(staging_inc, qlib_dir, DumpDataAll.UPDATE_MODE)
    inst_path = d._instruments_dir / "all.txt"
    inst = d._read_instruments(inst_path) if inst_path.exists() else pd.DataFrame(
        columns=[d.symbol_field_name, d.INSTRUMENTS_START_FIELD, d.INSTRUMENTS_END_FIELD]
    )
    backup_cal = d._calendars_dir / "1min.txt"
    if backup_cal.exists():
        shutil.copy2(backup_cal, backup_cal.with_suffix(".txt.bak"))
    if inst_path.exists():
        shutil.copy2(inst_path, inst_path.with_suffix(".txt.bak"))

    update_files: list[Path] = []
    new_files: list[Path] = []
    for path in d.df_files:
        code = d.get_symbol_from_file(path).upper()
        bin_path = d._features_dir / code_to_fname(code).lower() / "close.1min.bin"
        (update_files if bin_path.exists() else new_files).append(path)

    d.save_calendars(full_cal)
    for path in tqdm(update_files, desc="append 1min"):
        d._dump_bin(path, new_only)

    if new_files:
        full = make_dumper(staging_full, qlib_dir, DumpDataAll.ALL_MODE)
        for path in new_files:
            full_path = staging_full / path.name
            if full_path.exists():
                full._dump_bin(full_path, full_cal)
            else:
                print(f"skip missing full parquet {full_path}", flush=True)

    ends = {d.get_symbol_from_file(p).upper(): d._format_datetime(full_cal[-1]) for p in d.df_files}
    if not inst.empty:
        inst[d.symbol_field_name] = inst[d.symbol_field_name].astype(str).str.upper()
        mask = inst[d.symbol_field_name].isin(ends)
        inst.loc[mask, d.INSTRUMENTS_END_FIELD] = inst.loc[mask, d.symbol_field_name].map(ends)
    have = set(inst[d.symbol_field_name]) if not inst.empty else set()
    extra = []
    for path in list(staging_full.glob("*.parquet")) + list(staging_inc.glob("*.parquet")):
        code = d.get_symbol_from_file(path).upper()
        if code in have:
            continue
        feat = d._features_dir / code_to_fname(code).lower() / "close.1min.bin"
        if not feat.exists():
            continue
        src = pd.read_parquet(path, columns=["date"])
        extra.append(
            {
                d.symbol_field_name: code,
                d.INSTRUMENTS_START_FIELD: d._format_datetime(pd.to_datetime(src["date"]).min()),
                d.INSTRUMENTS_END_FIELD: d._format_datetime(full_cal[-1]),
            }
        )
        have.add(code)
    if extra:
        inst = pd.concat([inst, pd.DataFrame(extra)], ignore_index=True)
    d.save_instruments(inst)
    return len(update_files) + len(new_files)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh qlib 1min bins (not daily my_data)")
    parser.add_argument("--lake-root", type=Path, default=None)
    parser.add_argument("--index-lake", type=Path, default=None)
    parser.add_argument("--skip-index", action="store_true")
    parser.add_argument("--staging-dir", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--qlib-dir", type=Path, default=DEFAULT_QLIB_1MIN)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--rebuild", action="store_true", help="dump_all even if my_data_1min exists")
    parser.add_argument("--skip-stage", action="store_true")
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    qlib_dir = args.qlib_dir.expanduser()
    refuse_if_daily(qlib_dir)
    workers = clamp_workers(args.max_workers)
    daily_fp = daily_calendar_fingerprint()
    lake_root = args.lake_root or resolve_stock_1min_none()
    index_lake = None if args.skip_index else (args.index_lake or resolve_index_1min_none())
    staging = Path(args.staging_dir)
    symbols = args.symbols or None

    incremental = existing_1min_ready(qlib_dir) and not args.rebuild
    old_cal = read_1min_calendar(qlib_dir) if incremental else []
    cutoff = old_cal[-1] if old_cal else None
    stage_start = args.start
    if incremental and cutoff is not None and not args.start:
        stage_start = (cutoff + pd.Timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")

    if not args.skip_stage:
        if incremental:
            for path in staging.glob("*.parquet"):
                path.unlink()
        written = stage_stock_and_index(
            lake_root,
            index_lake,
            staging,
            symbols=symbols,
            start=stage_start,
            end=args.end,
            max_workers=workers,
        )
        if not written:
            raise SystemExit("no 1m parquet staged; check lake path / symbols / window")
        print(f"staged {len(written)} → {staging}", flush=True)

    if incremental:
        ref = staging / "sz000001.parquet"
        if not ref.exists():
            refs = sorted(staging.glob("*.parquet"))
            ref = refs[0] if refs else None
        if ref is None:
            raise SystemExit("incremental staging empty")
        dates = sorted(pd.Timestamp(x) for x in pd.to_datetime(pd.read_parquet(ref, columns=["date"])["date"]).unique())
        new_only = [t for t in dates if cutoff is None or t > cutoff]
        if not new_only:
            print(f"1min already at {cutoff}; nothing to append", flush=True)
            assert_daily_unchanged(daily_fp)
            return 0
        full_cal = (old_cal or []) + new_only
        full_staging = staging.parent / (staging.name + "_full_new")
        new_stems = []
        d_probe = make_dumper(staging, qlib_dir, DumpDataAll.UPDATE_MODE)
        for path in d_probe.df_files:
            code = d_probe.get_symbol_from_file(path).upper()
            if not (d_probe._features_dir / code_to_fname(code).lower() / "close.1min.bin").exists():
                new_stems.append(code)
        if new_stems:
            full_staging.mkdir(parents=True, exist_ok=True)
            stage_stock_and_index(
                args.lake_root,
                index_lake,
                full_staging,
                symbols=new_stems,
                start=args.start,
                end=args.end,
                max_workers=min(2, workers),
            )
        else:
            full_staging.mkdir(parents=True, exist_ok=True)
        n = append_new_1min_bars(staging, full_staging, qlib_dir, new_only, full_cal)
        print(f"appended {len(new_only)} bars for {n} symbols → {qlib_dir} last={full_cal[-1]}", flush=True)
    else:
        dump_all_1min(staging, qlib_dir, workers)
        print(f"qlib 1min dir → {qlib_dir}", flush=True)

    assert_daily_unchanged(daily_fp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
