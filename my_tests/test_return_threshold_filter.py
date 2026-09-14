"""涨幅过滤：对齐 instrument 后的语义 + 预取宽表查表。"""

from __future__ import annotations

import os
import sys

import pandas as pd

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from custom_strategy import (  # noqa: E402
    closes_by_instrument,
    closes_on_date,
    select_by_return_threshold,
    wide_close_from_features,
)


def _qlib_day_frame(date, closes: dict) -> pd.DataFrame:
    """模拟 D.features 单日返回：MultiIndex (instrument, datetime)。"""
    idx = pd.MultiIndex.from_tuples(
        [(code, pd.Timestamp(date)) for code in closes],
        names=["instrument", "datetime"],
    )
    return pd.DataFrame({"$close": list(closes.values())}, index=idx)


def test_raw_multindex_intersection_is_empty():
    """旧实现的病灶：两日 MultiIndex 直接 intersection → 空，过滤空转。"""
    start = _qlib_day_frame("2026-01-05", {"SH600000": 10.0, "SZ000001": 20.0})
    end = _qlib_day_frame("2026-01-12", {"SH600000": 10.5, "SZ000001": 24.0})
    assert start["$close"].index.intersection(end["$close"].index).empty


def test_closes_by_instrument_aligns_and_filters():
    start = closes_by_instrument(_qlib_day_frame("2026-01-05", {"SH600000": 10.0, "SZ000001": 20.0}))
    end = closes_by_instrument(_qlib_day_frame("2026-01-12", {"SH600000": 10.5, "SZ000001": 24.0}))
    # 600000 +5%；000001 +20% > 15%
    out = select_by_return_threshold(
        ["SH600000", "SZ000001", "SH600519"], start, end, 0.15, 10
    )
    assert out == ["SH600000", "SH600519"]  # 缺价当 -inf，放行


def test_early_stop_at_required_count():
    start = pd.Series({"A": 10.0, "B": 10.0, "C": 10.0})
    end = pd.Series({"A": 10.1, "B": 10.1, "C": 10.1})
    out = select_by_return_threshold(["A", "B", "C"], start, end, 0.15, 2)
    assert out == ["A", "B"]


def test_wide_cache_lookup_matches_live_align():
    rows = []
    index = []
    for d, prices in (
        ("2026-01-05", {"SH600000": 10.0, "SZ000001": 20.0}),
        ("2026-01-12", {"SH600000": 10.5, "SZ000001": 24.0}),
    ):
        for code, px in prices.items():
            rows.append(px)
            index.append((code, pd.Timestamp(d)))
    raw = pd.DataFrame(
        {"$close": rows},
        index=pd.MultiIndex.from_tuples(index, names=["instrument", "datetime"]),
    )
    wide = wide_close_from_features(raw)
    start = closes_on_date(wide, "2026-01-05")
    end = closes_on_date(wide, pd.Timestamp("2026-01-12 00:00:00"))
    out = select_by_return_threshold(["SZ000001", "SH600000"], start, end, 0.15, 10)
    assert out == ["SH600000"]
