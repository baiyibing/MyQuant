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
