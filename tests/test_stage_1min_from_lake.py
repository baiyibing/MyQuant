# -*- coding: utf-8 -*-
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qlib_scripts.stage_1min_from_lake import (
    lake_partition_to_qlib_code,
    load_symbol_frame,
    qlib_code_to_partition,
    stage_symbol,
)


def test_symbol_roundtrip():
    assert lake_partition_to_qlib_code("symbol=000001_SZ") == "SZ000001"
    assert lake_partition_to_qlib_code("600000_SH") == "SH600000"
    assert qlib_code_to_partition("SZ000001") == "000001_SZ"
    assert qlib_code_to_partition("000001.SZ") == "000001_SZ"


def test_stage_writes_dump_columns(tmp_path: Path):
    part = tmp_path / "symbol=600000_SH"
    part.mkdir()
    idx = pd.date_range("2026-08-03 09:30:00", periods=3, freq="min")
    raw = pd.DataFrame(
        {
            "time": (idx.view("int64") // 1_000_000).astype("int64"),
            "open": [10.0, 10.1, 10.2],
            "high": [10.2, 10.2, 10.3],
            "low": [9.9, 10.0, 10.1],
            "close": [10.1, 10.15, 10.25],
            "volume": [100, 80, 90],
            "amount": [101000.0, 81200.0, 92250.0],
        },
        index=idx,
    )
    raw.to_parquet(part / "data.parquet")
    dest = stage_symbol(part, tmp_path / "staging", "2026-08-03", "2026-08-03")
    assert dest is not None
    staged = pd.read_parquet(dest)
    assert list(staged.columns)[:2] == ["date", "symbol"]
    assert staged["symbol"].iloc[0] == "SH600000"
    assert "vwap" in staged.columns
    assert len(staged) == 3
