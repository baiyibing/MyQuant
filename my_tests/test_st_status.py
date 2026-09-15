"""Consume-only ST lake readers (no download / merge)."""

from __future__ import annotations

import os
import sys

import pandas as pd

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from st_status import (  # noqa: E402
    coverage_fallback_qlib,
    load_st_codes_asof,
    load_st_daily_index,
    to_qlib_code,
    to_wind_code,
)


def test_code_roundtrip():
    assert to_wind_code("SZ000504") == "000504.SZ"
    assert to_qlib_code("000504.SZ") == "SZ000504"
    assert to_qlib_code("600000.SH") == "SH600000"
    assert to_qlib_code("920305.BJ") == "BJ920305"


def test_coverage_fallback_and_asof(tmp_path):
    daily = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2026-01-07", "2026-01-08"]),
            "code": ["000615.SZ", "000615.SZ"],
            "is_st": [True, True],
            "st_kind": ["star_st", "star_st"],
            "name": ["*ST美谷", "*ST美谷"],
        }
    )
    daily_path = tmp_path / "st_daily.parquet"
    daily.to_parquet(daily_path, index=False)
    (tmp_path / "st_coverage.json").write_text(
        '{"harvested_wind_codes": ["000615.SZ", "000504.SZ"], '
        '"unknown_end_wind_codes": ["000504.SZ"]}',
        encoding="utf-8",
    )
    static = {"SZ000615", "SZ000504", "SH688999"}
    fallback = coverage_fallback_qlib(
        {"harvested_wind_codes": ["000615.SZ", "000504.SZ"], "unknown_end_wind_codes": ["000504.SZ"]},
        static,
    )
    assert "SZ000504" in fallback
    assert "SH688999" in fallback
    assert "SZ000615" not in fallback
    by_date, fb = load_st_daily_index(daily_path, fallback_static=static)
    assert by_date[pd.Timestamp("2026-01-07").date()] == {"SZ000615"}
    assert fb == fallback
    asof = load_st_codes_asof(daily_path, asof="2026-01-07", fallback_static=static)
    assert asof == {"SZ000615", "SZ000504", "SH688999"}
    snap = coverage_fallback_qlib(
        {
            "harvested_wind_codes": ["000615.SZ"],
            "unknown_end_wind_codes": [],
            "snapshot_fallback_wind_codes": ["603825.SH"],
        },
        {"SZ000615"},
    )
    assert snap == {"SH603825"}
