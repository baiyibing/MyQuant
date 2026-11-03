# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "qlib_scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from refresh_mydata_1min import (  # noqa: E402
    DAILY_QLIB,
    append_new_1min_bars,
    assert_daily_unchanged,
    clamp_workers,
    daily_calendar_fingerprint,
    existing_1min_ready,
    refuse_if_daily,
)


def test_refuse_if_daily():
    with pytest.raises(SystemExit, match="daily my_data"):
        refuse_if_daily(DAILY_QLIB)


def test_clamp_workers():
    assert clamp_workers(16) == 8
    assert clamp_workers(0) == 1
    assert clamp_workers(4) == 4


def test_daily_fingerprint_stable(tmp_path: Path):
    cal = tmp_path / "calendars"
    cal.mkdir()
    (cal / "day.txt").write_text("2026-09-15\n", encoding="utf-8")
    fp = daily_calendar_fingerprint(tmp_path)
    assert_daily_unchanged(fp, tmp_path)
    (cal / "day.txt").write_text("2026-09-16\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="daily my_data calendar changed"):
        assert_daily_unchanged(fp, tmp_path)


def _write_close_bin(path: Path, start_index: int, values: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.hstack([np.float32(start_index), np.asarray(values, dtype=np.float32)]).astype("<f").tofile(path)


def _write_stage(path: Path, times: list[str], close: float) -> None:
    pd.DataFrame(
        {
            "date": pd.to_datetime(times),
            "symbol": path.stem.upper(),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1,
            "amount": 10.0,
        }
    ).to_parquet(path, index=False)


def test_append_new_1min_bars(tmp_path: Path):
    qlib_dir = tmp_path / "my_data_1min"
    (qlib_dir / "calendars").mkdir(parents=True)
    (qlib_dir / "instruments").mkdir()
    old = ["2026-09-18 09:30:00", "2026-09-18 09:31:00"]
    (qlib_dir / "calendars" / "1min.txt").write_text("\n".join(old) + "\n", encoding="utf-8")
    (qlib_dir / "instruments" / "all.txt").write_text(
        "SZ000001\t2026-09-18 09:30:00\t2026-09-18 09:31:00\n",
        encoding="utf-8",
    )
    _write_close_bin(qlib_dir / "features" / "sz000001" / "close.1min.bin", 0, [10.0, 10.1])

    staging_inc = tmp_path / "inc"
    staging_full = tmp_path / "full"
    staging_inc.mkdir()
    staging_full.mkdir()
    _write_stage(staging_inc / "sz000001.parquet", ["2026-09-18 09:32:00"], 10.2)

    new_only = [pd.Timestamp("2026-09-18 09:32:00")]
    full_cal = [pd.Timestamp(x) for x in old] + new_only
    n = append_new_1min_bars(staging_inc, staging_full, qlib_dir, new_only, full_cal)
    assert n == 1
    cal = (qlib_dir / "calendars" / "1min.txt").read_text(encoding="utf-8").splitlines()
    assert cal[-1] == "2026-09-18 09:32:00"
    bars = (np.fromfile(qlib_dir / "features" / "sz000001" / "close.1min.bin", dtype="<f").size) - 1
    assert bars == 3
    assert existing_1min_ready(qlib_dir)


def _alignment_case(tmp_path, *, header=0, values=(10.0,), incoming=(3,)):
    cal = list(pd.date_range('2026-10-30 09:30', periods=4, freq='min'))
    provider = tmp_path / 'provider'
    (provider / 'calendars').mkdir(parents=True)
    (provider / 'instruments').mkdir()
    (provider / 'calendars/1min.txt').write_text('\n'.join(map(str, cal[:2]))+'\n', encoding='utf-8')
    (provider / 'instruments/all.txt').write_text(
        f'SZ000001\t{cal[int(header)] if np.isfinite(header) and 0 <= header < 2 else cal[0]}\t{cal[0]}\n', encoding='utf-8')
    feature = provider / 'features/sz000001/close.1min.bin'
    _write_close_bin(feature, header, values)
    inc, full = tmp_path / 'inc', tmp_path / 'full'
    inc.mkdir()
    full.mkdir()
    _write_stage(inc / 'sz000001.parquet', [str(cal[i]) for i in incoming], 11.0)
    return provider, feature, inc, full, cal


@pytest.mark.parametrize('header,values,expected', [
    (0, (10.0,), [0, 10, np.nan, np.nan, 11]),
    (0, (10.0, 10.1), [0, 10, 10.1, np.nan, 11]),
    (1, (10.0,), [1, 10, np.nan, 11]),
])
def test_append_preserves_global_minute_positions_and_old_bytes(tmp_path, header, values, expected):
    provider, feature, inc, full, cal = _alignment_case(tmp_path, header=header, values=values)
    before = feature.read_bytes()
    append_new_1min_bars(inc, full, provider, cal[2:], cal)
    assert feature.read_bytes().startswith(before)
    np.testing.assert_equal(np.fromfile(feature, dtype='<f4'), np.asarray(expected, dtype='<f4'))
    # A field first introduced by this increment starts on the FULL calendar.
    np.testing.assert_equal(np.fromfile(feature.with_name('open.1min.bin'), dtype='<f4'), [3, 11])


@pytest.mark.parametrize('header,values', [
    (np.nan, (10,)), (np.inf, (10,)), (-1, (10,)), (0.5, (10,)), (2, (10,)),
])
def test_malformed_old_bin_rejected_before_calendar_advance(tmp_path, header, values):
    provider, feature, inc, full, cal = _alignment_case(tmp_path, header=header, values=values)
    old_file, old_cal = feature.read_bytes(), (provider/'calendars/1min.txt').read_bytes()
    with pytest.raises(ValueError, match='1min'):
        append_new_1min_bars(inc, full, provider, cal[2:], cal)
    assert feature.read_bytes() == old_file
    assert (provider/'calendars/1min.txt').read_bytes() == old_cal


@pytest.mark.parametrize('kind', ['duplicate', 'reverse', 'prefix', 'suffix'])
def test_invalid_append_calendar_rejected_without_writes(tmp_path, kind):
    provider, feature, inc, full, cal = _alignment_case(tmp_path)
    before = feature.read_bytes()
    original = (provider/'calendars/1min.txt').read_bytes()
    new = cal[2:]
    if kind == 'duplicate':
        cal = [cal[0], cal[0], *cal[2:]]
    elif kind == 'reverse':
        cal = list(reversed(cal))
    elif kind == 'prefix':
        cal = [cal[0] - pd.Timedelta(minutes=1), *cal[1:]]
    else:
        new = [cal[3]]
    with pytest.raises(ValueError, match='1min'):
        append_new_1min_bars(inc, full, provider, new, cal)
    assert feature.read_bytes() == before
    assert (provider/'calendars/1min.txt').read_bytes() == original


def test_missing_new_symbol_full_stage_is_failure_before_existing_changes(tmp_path):
    provider, feature, inc, full, cal = _alignment_case(tmp_path)
    _write_stage(inc/'sh600000.parquet', [str(cal[3])], 20)
    before = feature.read_bytes()
    original = (provider/'calendars/1min.txt').read_bytes()
    with pytest.raises(ValueError, match='full'):
        append_new_1min_bars(inc, full, provider, cal[2:], cal)
    assert feature.read_bytes() == before
    assert (provider/'calendars/1min.txt').read_bytes() == original


def test_new_symbol_global_header_and_actual_instrument_end(tmp_path):
    provider, _, inc, full, cal = _alignment_case(tmp_path)
    _write_stage(inc/'sh600000.parquet', [str(cal[2])], 20)
    _write_stage(full/'sh600000.parquet', [str(cal[1]), str(cal[2])], 20)
    append_new_1min_bars(inc, full, provider, cal[2:], cal)
    np.testing.assert_equal(np.fromfile(provider/'features/sh600000/close.1min.bin', dtype='<f4'), [1,20,20])
    row = next(line for line in (provider/'instruments/all.txt').read_text().splitlines() if line.startswith('SH600000'))
    assert row.split('\t')[1:] == [str(cal[1]), str(cal[2])]


@pytest.mark.parametrize('old_rows,new_rows', [((0,2),(5,7)), ((1,),(6,)), ((0,3),(4,5,7))])
def test_sparse_increment_all_fields_equal_independent_rebuild(tmp_path, old_rows, new_rows):
    from refresh_mydata_1min import make_dumper
    from dump_bin import DumpDataAll
    cal = list(pd.date_range('2026-10-30 09:30', periods=8, freq='min'))
    stage = tmp_path/'stage'
    stage.mkdir()
    values = np.asarray([10+i for i in old_rows+new_rows], dtype=float)
    frame = pd.DataFrame({'date':[cal[i] for i in old_rows+new_rows], 'symbol':'SZ000001',
        'close':values, 'open':values, 'high':values+1, 'low':values-1,
        'volume':values*10, 'amount':values*100, 'vwap':values})
    source = stage/'sz000001.parquet'
    frame.loc[:len(old_rows)-1].to_parquet(source, index=False)
    provider = tmp_path/'incremental'
    initial = make_dumper(stage, provider, DumpDataAll.ALL_MODE)
    initial._dump_bin(source, cal[:4])
    initial.save_calendars(cal[:4])
    initial.save_instruments([f'SZ000001\t{cal[old_rows[0]]}\t{cal[old_rows[-1]]}'])
    old_bytes = {p.name:p.read_bytes() for p in (provider/'features/sz000001').glob('*.bin')}
    inc, full = tmp_path/'inc', tmp_path/'full'
    inc.mkdir()
    full.mkdir()
    frame.iloc[len(old_rows):].to_parquet(inc/source.name, index=False)
    append_new_1min_bars(inc, full, provider, cal[4:], cal)
    frame.to_parquet(source, index=False)
    expected = tmp_path/'rebuild'
    make_dumper(stage, expected, DumpDataAll.ALL_MODE)._dump_bin(source, cal)
    for path in (expected/'features/sz000001').glob('*.bin'):
        actual = provider/'features/sz000001'/path.name
        assert actual.read_bytes().startswith(old_bytes[path.name])
        assert actual.read_bytes() == path.read_bytes()


def test_increment_calendar_uses_bounded_rebuild_reference_union(tmp_path):
    from refresh_mydata_1min import incremental_calendar, make_dumper
    from dump_bin import DumpDataAll
    stage = tmp_path/'stage'
    stage.mkdir()
    _write_stage(stage/'sz000001.parquet', ['2026-10-30 09:31:00'], 10)
    _write_stage(stage/'sh000300.parquet', ['2026-10-30 09:32:00'], 20)
    _write_stage(stage/'sh600000.parquet', ['2026-10-30 09:33:00'], 30)
    d = make_dumper(stage, tmp_path/'provider', DumpDataAll.UPDATE_MODE)
    assert incremental_calendar(d, pd.Timestamp('2026-10-30 09:30')) == list(pd.to_datetime([
        '2026-10-30 09:31:00','2026-10-30 09:32:00']))


def test_atomic_bin_replace_failure_leaves_original_and_calendar(tmp_path, monkeypatch):
    import refresh_mydata_1min as refresh
    provider, feature, inc, full, cal = _alignment_case(tmp_path)
    # Only one field so this checks file atomicity, not a provider transaction.
    pd.DataFrame({'date':[cal[3]],'symbol':['SZ000001'],'close':[11]}).to_parquet(inc/'sz000001.parquet', index=False)
    before, calendar = feature.read_bytes(), (provider/'calendars/1min.txt').read_bytes()
    def fail_replace(*args):
        raise OSError('injected replace failure')
    monkeypatch.setattr(refresh.os, 'replace', fail_replace)
    with pytest.raises(OSError, match='injected'):
        append_new_1min_bars(inc, full, provider, cal[2:], cal)
    assert feature.read_bytes() == before
    assert (provider/'calendars/1min.txt').read_bytes() == calendar
    assert not list(feature.parent.glob('*.tmp'))
