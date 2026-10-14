# -*- coding: utf-8 -*-
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qlib_scripts.stage_etf_daily_from_lake import (  # noqa: E402
    WINDOW_END,
    WINDOW_START,
    basis_evidence,
    basis_passes,
    lake_partition_to_qlib_code,
    prepare_frame,
    stage_symbol,
)


def _ms(day: str) -> int:
    return int(pd.Timestamp(day, tz="UTC").timestamp() * 1000)


def _lake(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    for col in ("open", "high", "low", "close", "volume", "amount"):
        if col not in frame.columns:
            frame[col] = frame["close"] if col != "volume" else 100
            if col == "amount":
                frame[col] = frame["close"] * frame["volume"] * 100
    return frame


def test_symbol_code():
    assert lake_partition_to_qlib_code("symbol=510300_SH") == "SH510300"
    assert lake_partition_to_qlib_code("159915_SZ") == "SZ159915"


def test_prepare_drops_zeros_scales_vwap_and_clips_window():
    front = _lake(
        [
            {"time": _ms("2019-12-31"), "close": 9.0, "volume": 100, "amount": 90000.0},
            {"time": _ms("2020-01-02"), "close": 10.0, "volume": 100, "amount": 80000.0},
            {"time": _ms("2020-01-03"), "close": 0.0, "volume": 0, "amount": 0.0},
            {"time": _ms("2026-10-14"), "close": 11.0, "volume": 100, "amount": 110000.0},
        ]
    )
    none = _lake(
        [
            {"time": _ms("2019-12-31"), "close": 9.0, "volume": 100, "amount": 90000.0},
            {"time": _ms("2020-01-02"), "close": 8.0, "volume": 100, "amount": 80000.0},
            {"time": _ms("2020-01-03"), "close": 0.0, "volume": 0, "amount": 0.0},
            {"time": _ms("2026-10-14"), "close": 11.0, "volume": 100, "amount": 110000.0},
        ]
    )
    out, stats = prepare_frame(front, none)
    assert list(out["date"].dt.strftime("%Y-%m-%d")) == ["2020-01-02"]
    assert stats["before_window"] == 1
    assert stats["beyond_window"] == 1
    assert stats["dropped_placeholder"] == 1
    # raw vwap = 80000/(100*100) = 8；front/none = 10/8；缩放后 = 10
    assert abs(float(out["vwap"].iloc[0]) - 10.0) < 1e-9


def test_stage_symbol_writes_qlib_filename(tmp_path: Path):
    day = "2020-01-02"
    front_part = tmp_path / "dividend_type=front" / "symbol=510300_SH"
    none_part = tmp_path / "dividend_type=none" / "symbol=510300_SH"
    front_part.mkdir(parents=True)
    none_part.mkdir(parents=True)
    front = _lake([{"time": _ms(day), "close": 10.0, "volume": 100, "amount": 80000.0}])
    none = _lake([{"time": _ms(day), "close": 8.0, "volume": 100, "amount": 80000.0}])
    front.to_parquet(front_part / "data.parquet")
    none.to_parquet(none_part / "data.parquet")
    dest, _stats = stage_symbol(front_part, tmp_path / "staging", none_root=none_part.parent)
    assert dest is not None
    assert dest.name == "sh510300.parquet"
    staged = pd.read_parquet(dest)
    assert staged["symbol"].iloc[0] == "SH510300"
    assert str(pd.Timestamp(staged["date"].iloc[0]).date()) == WINDOW_START
    assert WINDOW_END not in set(staged["date"].dt.strftime("%Y-%m-%d"))


def test_all_zero_symbol_writes_nothing(tmp_path: Path):
    front_part = tmp_path / "front" / "symbol=510300_SH"
    none_part = tmp_path / "none" / "symbol=510300_SH"
    front_part.mkdir(parents=True)
    none_part.mkdir(parents=True)
    zeros = _lake([{"time": _ms("2020-01-02"), "close": 0.0, "volume": 0, "amount": 0.0}])
    zeros.to_parquet(front_part / "data.parquet")
    zeros.to_parquet(none_part / "data.parquet")
    dest, _stats = stage_symbol(front_part, tmp_path / "staging", none_root=none_part.parent)
    assert dest is None
    assert list((tmp_path / "staging").glob("*.parquet")) == []


def test_basis_flags_unadjusted_amount():
    front = _lake(
        [
            {"time": _ms("2020-01-02"), "close": 8.8, "volume": 100, "amount": 100000.0},
            {"time": _ms("2026-10-13"), "close": 10.0, "volume": 100, "amount": 100000.0},
        ]
    )
    none = _lake(
        [
            {"time": _ms("2020-01-02"), "close": 10.0, "volume": 100, "amount": 100000.0},
            {"time": _ms("2026-10-13"), "close": 10.0, "volume": 100, "amount": 100000.0},
        ]
    )
    evidence = basis_evidence(front, none)
    assert evidence["px_start"] < 0.9
    assert abs(evidence["px_end"] - 1.0) < 1e-9
    assert abs(evidence["amt_ratio_median"] - 1.0) < 1e-9
    assert evidence["raw_gap_median"] > evidence["scaled_gap_median"]
    assert basis_passes(evidence)
