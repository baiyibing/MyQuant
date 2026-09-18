# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "qlib_scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from dump_bin import DUMP_MAX_WORKERS_CAP, DumpDataAll, is_highfreq  # noqa: E402


def _write_min_parquet(path: Path, times: list[str], close: float = 10.0) -> None:
    idx = pd.to_datetime(times)
    pd.DataFrame(
        {
            "date": idx,
            "symbol": path.stem.upper(),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 100,
            "amount": 1000.0,
        }
    ).to_parquet(path, index=False)


def test_is_highfreq():
    assert is_highfreq("1min")
    assert is_highfreq("5min")
    assert not is_highfreq("day")
    assert not is_highfreq("1d")


def test_highfreq_clamps_workers(tmp_path: Path):
    _write_min_parquet(tmp_path / "sz000001.parquet", ["2026-09-18 09:30:00"])
    d = DumpDataAll(
        data_path=str(tmp_path),
        qlib_dir=str(tmp_path / "qlib"),
        freq="1min",
        max_workers=16,
        date_field_name="date",
        file_suffix=".parquet",
        symbol_field_name="symbol",
        exclude_fields="symbol",
    )
    assert d.works == DUMP_MAX_WORKERS_CAP


def test_highfreq_calendar_from_refs_not_every_symbol(tmp_path: Path):
    _write_min_parquet(
        tmp_path / "sz000001.parquet",
        ["2026-09-18 09:30:00", "2026-09-18 09:31:00"],
    )
    _write_min_parquet(
        tmp_path / "zz999999.parquet",
        ["2026-09-18 09:30:00", "2026-09-18 09:31:00", "2026-09-18 09:32:00"],
    )
    d = DumpDataAll(
        data_path=str(tmp_path),
        qlib_dir=str(tmp_path / "qlib"),
        freq="1min",
        max_workers=1,
        date_field_name="date",
        file_suffix=".parquet",
        symbol_field_name="symbol",
        exclude_fields="symbol",
    )
    d._get_all_date()
    cal = {pd.Timestamp(x) for x in d._kwargs["all_datetime_set"]}
    assert pd.Timestamp("2026-09-18 09:30:00") in cal
    assert pd.Timestamp("2026-09-18 09:31:00") in cal
    assert pd.Timestamp("2026-09-18 09:32:00") not in cal
    joined = "\n".join(d._kwargs["date_range_list"])
    assert "SZ000001" in joined
    assert "ZZ999999" in joined
