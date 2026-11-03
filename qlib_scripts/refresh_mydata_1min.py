# -*- coding: utf-8 -*-
"""Refresh ~/.qlib/qlib_data/my_data_1min from stock+index 1m lakes (OSKH_SOURCE_PARQUET_ROOT).

Never writes daily my_data / pred.pkl. Prefer incremental append when bins exist.
Do not call dump_update (it loads every staging parquet into one DataFrame).
dump_all --freq=1min builds the calendar from a few refs (see dump_bin).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence

import pandas as pd
import numpy as np
from tqdm import tqdm

from dump_bin import DumpDataAll
from qlib.utils import code_to_fname

_MY_SCRIPTS = Path(__file__).resolve().parents[1] / "my_scripts"
if str(_MY_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_MY_SCRIPTS))
from data_root import resolve_index_1min_none, resolve_stock_1min_none  # noqa: E402
from qlib_1min_increment_receipt import (  # noqa: E402
    build_receipt,
    sha256_file,
    snapshot_1min_state,
    write_receipt,
)
from stage_1min_from_lake import (  # noqa: E402
    DEFAULT_MAX_WORKERS,
    DEFAULT_STAGING,
    stage_stock_and_index,
    iter_lake_partitions,
    lake_partition_to_qlib_code,
    qlib_code_to_partition,
)

DAILY_QLIB = Path.home() / ".qlib" / "qlib_data" / "my_data"
DEFAULT_QLIB_1MIN = Path.home() / ".qlib" / "qlib_data" / "my_data_1min"
DUMP_BIN = Path(__file__).resolve().parent / "dump_bin.py"
RECEIPT_PROBE_SYMBOL = "SZ000001"


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


def incremental_calendar(dumper: DumpDataAll, cutoff: pd.Timestamp) -> list[pd.Timestamp]:
    """Use the same bounded reference union as a high-frequency rebuild."""
    dates = set()
    for path in dumper._pick_calendar_ref_files():
        frame = pd.read_parquet(path, columns=['date'])
        dates.update(pd.Timestamp(t) for t in pd.to_datetime(frame['date']).unique() if t > cutoff)
    return sorted(dates)


def requested_codes(symbols) -> set[str] | None:
    if symbols is None:
        return None
    codes = [lake_partition_to_qlib_code(qlib_code_to_partition(s)) for s in symbols]
    if not codes or len(set(codes)) != len(codes):
        raise ValueError('1min explicit symbols must be nonempty and unique after normalization')
    return set(codes)


def validate_increment_sources(lake_root: Path, index_lake: Path | None, symbols) -> None:
    """Reject bad routing before old staging is removed; do not reread source frames."""
    available = set()
    for root in [lake_root] + ([index_lake] if index_lake is not None else []):
        if not Path(root).is_dir():
            raise ValueError('1min source root missing or not a directory')
        for partition in iter_lake_partitions(root, symbols):
            if any(partition.glob('*.parquet')):
                available.add(lake_partition_to_qlib_code(partition.name))
    if not available:
        raise ValueError('1min request has no source parquet files')
    if symbols is not None:
        requested = requested_codes(symbols)
        if not requested.issubset(available):
            raise ValueError('1min requested symbol has no source parquet')


def validate_empty_increment(audit: list[dict], qlib_dir: Path,
                             old_cal: list[pd.Timestamp], symbols) -> dict:
    """Empty automatic selection is noop only with usable, already represented inputs."""
    axis = pd.DatetimeIndex(old_cal)
    if not len(axis) or axis.hasnans or axis.has_duplicates or not axis.is_monotonic_increasing:
        raise ValueError('invalid existing 1min calendar for noop')
    if not audit or any(r['invalid_time_rows'] or r['requested_rows'] for r in audit):
        raise ValueError('empty 1min stage is not proof of no new input')
    if any(r['source_rows'] and not r['usable_source_rows'] for r in audit):
        raise ValueError('1min source contains rows but no usable history')
    by_code = {}
    for row in audit:
        if row['usable_source_rows'] > 0:
            by_code.setdefault(row['code'], []).append(row)
    usable = set(by_code)
    if not usable:
        raise ValueError('empty 1min stage has no usable source history')
    if symbols is not None:
        requested = requested_codes(symbols)
        if not requested.issubset(usable):
            raise ValueError('requested 1min symbol has no usable source history')
    checked = 0
    for code, rows in by_code.items():
        if not symbols and all(pd.Timestamp(r['source_max']) < axis[0] for r in rows):
            continue
        path = qlib_dir / 'features' / code_to_fname(code).lower() / 'close.1min.bin'
        if not path.is_file():
            raise ValueError('1min source symbol absent from provider; import/rebuild required')
        size = path.stat().st_size
        if size < 8 or size % 4:
            raise ValueError('invalid existing 1min close bin for noop')
        first = float(np.fromfile(path, dtype='<f4', count=1)[0])
        if not np.isfinite(first) or first < 0 or not first.is_integer() or int(first)+size//4-1 > len(axis):
            raise ValueError('invalid existing 1min close bin bounds for noop')
        checked += 1
    if not checked:
        raise ValueError('1min provider has no corresponding usable source')
    return {'source_partitions_observed': len(audit),
            'source_rows': sum(r['source_rows'] for r in audit),
            'usable_history_rows': sum(r['usable_source_rows'] for r in audit),
            'raw_rows_in_window': 0, 'invalid_time_rows': 0,
            'provider_close_bins_checked': checked,
            'scope': 'Configured input request only; not market freshness or full provider quality'}


def _append_aligned_symbol(dumper: DumpDataAll, path: Path,
                           full_cal: list[pd.Timestamp], old_len: int) -> pd.Timestamp | None:
    frame = dumper._get_source_data(path).drop_duplicates(dumper.date_field_name)
    frame = frame.loc[frame[dumper.date_field_name] > full_cal[old_len-1]].copy()
    if frame.empty:
        return None
    aligned = dumper.data_merge_calendar(frame, full_cal)
    if aligned.empty:
        return None
    first = full_cal.index(aligned.index.min())
    code = dumper.get_symbol_from_file(path).upper()
    directory = dumper._features_dir / code_to_fname(code).lower()
    plans = []
    # Validate all existing fields for this symbol before replacing any field.
    for field in sorted(dumper.get_dump_fields(aligned.columns)):
        dest = directory / f'{field.lower()}.1min.bin'
        padding = 0
        exists = dest.exists()
        if exists:
            size = dest.stat().st_size
            if size < 8 or size % 4:
                raise ValueError('invalid 1min bin length')
            header = float(np.fromfile(dest, dtype='<f4', count=1)[0])
            if not np.isfinite(header) or header < 0 or not header.is_integer():
                raise ValueError('invalid 1min bin header')
            stop = int(header) + size // 4 - 1
            if stop > old_len:
                raise ValueError('1min bin extends beyond old calendar; rebuild required')
            padding = first - stop
        values = pd.to_numeric(aligned[field], errors='coerce').to_numpy(dtype='<f4')
        plans.append((dest, exists, padding, values))
    directory.mkdir(parents=True, exist_ok=True)
    for dest, exists, padding, values in plans:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, prefix=dest.name+'.', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                if exists:
                    with dest.open('rb') as original:
                        shutil.copyfileobj(original, stream)
                    np.full(padding, np.nan, dtype='<f4').tofile(stream)
                else:
                    np.asarray([first], dtype='<f4').tofile(stream)
                values.tofile(stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, dest)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return aligned.index.max()


def append_new_1min_bars(
    staging_inc: Path,
    staging_full: Path,
    qlib_dir: Path,
    new_only: list[pd.Timestamp],
    full_cal: list[pd.Timestamp],
) -> int:
    """Append by full-axis offsets; publish the calendar after successful feature writes.

    Individual bin replacement is atomic. A multi-file IO failure needs recovery
    or rebuild; this function does not promise a provider-wide transaction.
    """
    old_cal = read_1min_calendar(qlib_dir)
    axis = pd.DatetimeIndex(full_cal)
    if (not old_cal or not new_only or axis.hasnans or axis.has_duplicates
            or not axis.is_monotonic_increasing or full_cal != old_cal + new_only):
        raise ValueError('invalid 1min append calendar prefix/suffix')
    d = make_dumper(staging_inc, qlib_dir, DumpDataAll.UPDATE_MODE)
    inst_path = d._instruments_dir / "all.txt"
    inst = d._read_instruments(inst_path) if inst_path.exists() else pd.DataFrame(
        columns=[d.symbol_field_name, d.INSTRUMENTS_START_FIELD, d.INSTRUMENTS_END_FIELD]
    )
    update_files: list[Path] = []
    new_files: list[Path] = []
    for path in d.df_files:
        code = d.get_symbol_from_file(path).upper()
        bin_path = d._features_dir / code_to_fname(code).lower() / "close.1min.bin"
        (update_files if bin_path.exists() else new_files).append(path)

    for path in new_files:
        if not (staging_full / path.name).is_file():
            raise ValueError('missing full stage for new 1min symbol')
    backup_cal = d._calendars_dir / '1min.txt'
    shutil.copy2(backup_cal, backup_cal.with_suffix('.txt.bak'))
    if inst_path.exists():
        shutil.copy2(inst_path, inst_path.with_suffix('.txt.bak'))
    ends = {}
    touched = 0
    for path in tqdm(update_files, desc="append 1min"):
        last = _append_aligned_symbol(d, path, full_cal, len(old_cal))
        if last is not None:
            ends[d.get_symbol_from_file(path).upper()] = d._format_datetime(last)
            touched += 1

    if new_files:
        full = make_dumper(staging_full, qlib_dir, DumpDataAll.ALL_MODE)
        for path in new_files:
            full_path = staging_full / path.name
            full._dump_bin(full_path, full_cal)
            if not (full._features_dir / code_to_fname(full.get_symbol_from_file(full_path)).lower() / 'close.1min.bin').is_file():
                raise ValueError('new 1min symbol produced no close bin')
            touched += 1

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
        feature_values = np.fromfile(feat, dtype='<f4')
        first = int(feature_values[0])
        last = first + len(feature_values) - 2
        extra.append(
            {
                d.symbol_field_name: code,
                d.INSTRUMENTS_START_FIELD: d._format_datetime(full_cal[first]),
                d.INSTRUMENTS_END_FIELD: d._format_datetime(full_cal[last]),
            }
        )
        have.add(code)
    if extra:
        inst = pd.concat([inst, pd.DataFrame(extra)], ignore_index=True)
    d.save_instruments(inst)
    d.save_calendars(full_cal)
    return touched


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
    parser.add_argument("--receipt", type=Path, default=None, help="write QL11 1min increment receipt JSON on success")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    requested_codes(args.symbols)
    qlib_dir = args.qlib_dir.expanduser()
    refuse_if_daily(qlib_dir)
    workers = clamp_workers(args.max_workers)
    daily_fp = daily_calendar_fingerprint()
    state_before = (
        snapshot_1min_state(qlib_dir, probe_symbol=RECEIPT_PROBE_SYMBOL) if args.receipt else None
    )

    def emit_receipt(mode: str, bars_appended: int | None, symbols_touched: int,
                     empty_proof: dict | None = None) -> None:
        if args.receipt is None:
            return
        receipt = build_receipt(
            mode=mode,
            qlib_1min_dir=qlib_dir,
            daily_dir=DAILY_QLIB,
            daily_day_txt_sha256_before=daily_fp[1],
            daily_day_txt_sha256_after=sha256_file(DAILY_QLIB / "calendars" / "day.txt"),
            state_before=state_before,
            state_after=snapshot_1min_state(qlib_dir, probe_symbol=RECEIPT_PROBE_SYMBOL),
            bars_appended=bars_appended,
            symbols_touched=symbols_touched,
        )
        if empty_proof is not None:
            receipt['empty_increment_proof'] = empty_proof
        write_receipt(args.receipt, receipt)
        print(f"receipt → {args.receipt}", flush=True)

    lake_root = args.lake_root or resolve_stock_1min_none()
    index_lake = None if args.skip_index else (args.index_lake or resolve_index_1min_none())
    staging = Path(args.staging_dir)
    symbols = args.symbols

    incremental = existing_1min_ready(qlib_dir) and not args.rebuild
    old_cal = read_1min_calendar(qlib_dir) if incremental else []
    cutoff = old_cal[-1] if old_cal else None
    stage_start = args.start
    if incremental and cutoff is not None and not args.start:
        stage_start = (cutoff + pd.Timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")

    if not args.skip_stage:
        automatic_increment = incremental and args.start is None
        audit = [] if automatic_increment else None
        if automatic_increment:
            validate_increment_sources(lake_root, index_lake, symbols)
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
            audit=audit,
        )
        if not written:
            if automatic_increment:
                empty_proof = validate_empty_increment(audit, qlib_dir, old_cal, symbols)
                assert_daily_unchanged(daily_fp)
                print(f'1min has no new bars after {cutoff} within the request', flush=True)
                emit_receipt('noop', 0, 0, empty_proof)
                return 0
            raise SystemExit("no 1m parquet staged; check lake path / symbols / window")
        print(f"staged {len(written)} → {staging}", flush=True)

    if incremental:
        d_probe = make_dumper(staging, qlib_dir, DumpDataAll.UPDATE_MODE)
        if not d_probe.df_files:
            raise SystemExit("incremental staging empty")
        new_only = incremental_calendar(d_probe, cutoff)
        if not new_only:
            print(f"1min already at {cutoff}; nothing to append", flush=True)
            assert_daily_unchanged(daily_fp)
            emit_receipt("noop", 0, 0)
            return 0
        full_cal = (old_cal or []) + new_only
        full_staging = staging.parent / (staging.name + "_full_new")
        new_stems = []
        for path in d_probe.df_files:
            code = d_probe.get_symbol_from_file(path).upper()
            if not (d_probe._features_dir / code_to_fname(code).lower() / "close.1min.bin").exists():
                new_stems.append(code)
        if new_stems:
            full_staging.mkdir(parents=True, exist_ok=True)
            stage_stock_and_index(
                lake_root,
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
        mode, bars_appended, symbols_touched = "incremental", len(new_only), n
    else:
        dump_all_1min(staging, qlib_dir, workers)
        print(f"qlib 1min dir → {qlib_dir}", flush=True)
        mode, bars_appended, symbols_touched = "rebuild", None, len(list(staging.glob("*.parquet")))

    assert_daily_unchanged(daily_fp)
    emit_receipt(mode, bars_appended, symbols_touched)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
