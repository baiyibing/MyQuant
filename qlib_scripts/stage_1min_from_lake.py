# -*- coding: utf-8 -*-
"""Hive 1m parquet → dump_bin staging (one parquet per qlib code).

Does not write ~/.qlib/qlib_data/my_data. Lake default is E: 1m/none.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Sequence

import pandas as pd

DEFAULT_LAKE = Path(r"E:\stock_data\stock\period=1m\dividend_type=none")
DEFAULT_STAGING = Path(r"D:\qlib_data\_staging_1min")
OHLCV = ("open", "high", "low", "close", "volume", "amount")


def lake_partition_to_qlib_code(name: str) -> str:
    """``symbol=000001_SZ`` / ``000001_SZ`` → ``SZ000001``."""
    key = name[len("symbol=") :] if name.startswith("symbol=") else name
    if "_" not in key:
        return key.upper()
    bare, exch = key.rsplit("_", 1)
    return f"{exch.upper()}{bare}"


def qlib_code_to_partition(code: str) -> str:
    text = str(code).strip().upper()
    if "." in text:
        bare, exch = text.split(".", 1)
        return f"{bare}_{exch}"
    compact = text.replace(".", "")
    if len(compact) >= 8 and compact[:2] in {"SH", "SZ", "BJ"}:
        return f"{compact[2:]}_{compact[:2]}"
    return compact


def iter_lake_partitions(lake_root: Path, symbols: Sequence[str] | None = None) -> list[Path]:
    root = Path(lake_root)
    if symbols:
        out = []
        for raw in symbols:
            part = qlib_code_to_partition(raw)
            path = root / f"symbol={part}"
            if path.is_dir():
                out.append(path)
        return out
    return sorted(p for p in root.glob("symbol=*") if p.is_dir())


def _as_naive(index_or_series) -> pd.DatetimeIndex:
    values = pd.DatetimeIndex(pd.to_datetime(index_or_series))
    if values.tz is not None:
        return values.tz_convert("Asia/Shanghai").tz_localize(None)
    return pd.DatetimeIndex(values)


def load_symbol_frame(partition: Path, start: str | None, end: str | None) -> pd.DataFrame:
    files = sorted(partition.glob("*.parquet"))
    if not files:
        return pd.DataFrame()
    frame = pd.concat((pd.read_parquet(path) for path in files), ignore_index=False)
    if isinstance(frame.index, pd.DatetimeIndex) and len(frame.index) == len(frame):
        dates = _as_naive(frame.index)
        work = frame.reset_index(drop=True)
    elif "time" in frame.columns:
        work = frame.reset_index(drop=True)
        raw = work["time"]
        if pd.api.types.is_numeric_dtype(raw):
            dates = _as_naive(pd.to_datetime(raw, unit="ms"))
        else:
            dates = _as_naive(raw)
    else:
        raise ValueError(f"{partition} has no datetime index or time column")
    out = pd.DataFrame({col: pd.to_numeric(work[col], errors="coerce") for col in OHLCV if col in work.columns})
    out.insert(0, "date", dates)
    if start:
        out = out.loc[out["date"] >= pd.Timestamp(start)]
    if end:
        end_ts = pd.Timestamp(end)
        if end_ts.hour == 0 and end_ts.minute == 0:
            end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        out = out.loc[out["date"] <= end_ts]
    vol = out.get("volume")
    amt = out.get("amount")
    if vol is not None and amt is not None:
        denom = vol.astype("float64") * 100.0
        out["vwap"] = (amt.astype("float64") / denom).where(denom > 0)
    out = out.dropna(subset=["date", "close"])
    out = out.drop_duplicates("date").sort_values("date")
    return out.reset_index(drop=True)


def stage_symbol(partition: Path, staging_dir: Path, start: str | None, end: str | None) -> Path | None:
    code = lake_partition_to_qlib_code(partition.name)
    frame = load_symbol_frame(partition, start, end)
    if frame.empty:
        return None
    frame.insert(1, "symbol", code)
    dest = Path(staging_dir) / f"{code.lower()}.parquet"
    dest.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(dest, index=False)
    return dest


def _stage_job(item: tuple[str, str, str | None, str | None]) -> str | None:
    partition, staging_dir, start, end = item
    dest = stage_symbol(Path(partition), Path(staging_dir), start, end)
    return str(dest) if dest is not None else None


def stage_lake(
    lake_root: Path,
    staging_dir: Path,
    *,
    symbols: Sequence[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    max_workers: int = 1,
) -> list[Path]:
    partitions = iter_lake_partitions(Path(lake_root), symbols)
    staging = Path(staging_dir)
    staging.mkdir(parents=True, exist_ok=True)
    jobs = [(str(p), str(staging), start, end) for p in partitions]
    written: list[Path] = []
    workers = max(1, int(max_workers))
    if workers == 1 or len(jobs) <= 1:
        for i, job in enumerate(jobs, 1):
            dest = _stage_job(job)
            if dest:
                written.append(Path(dest))
            if i % 200 == 0 or i == len(jobs):
                print(f"stage {i}/{len(jobs)} written={len(written)}", flush=True)
        return written
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, dest in enumerate(pool.map(_stage_job, jobs, chunksize=8), 1):
            if dest:
                written.append(Path(dest))
            if i % 200 == 0 or i == len(jobs):
                print(f"stage {i}/{len(jobs)} written={len(written)}", flush=True)
    return written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage hive 1m parquet for qlib dump_bin --freq=1min")
    parser.add_argument("--lake-root", type=Path, default=DEFAULT_LAKE)
    parser.add_argument("--staging-dir", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--symbols", nargs="*", help="SZ000001 / 000001.SZ / 000001_SZ")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    written = stage_lake(
        args.lake_root,
        args.staging_dir,
        symbols=args.symbols,
        start=args.start,
        end=args.end,
    )
    print(f"staged {len(written)} files → {args.staging_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
