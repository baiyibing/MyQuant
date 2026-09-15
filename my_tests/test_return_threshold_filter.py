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


def _qlib_range_frame(day_closes: dict) -> pd.DataFrame:
    """模拟区间 D.features：多日 MultiIndex (instrument, datetime)。"""
    rows = []
    index = []
    for d, closes in day_closes.items():
        for code, px in closes.items():
            rows.append(px)
            index.append((code, pd.Timestamp(d)))
    return pd.DataFrame(
        {"$close": rows},
        index=pd.MultiIndex.from_tuples(index, names=["instrument", "datetime"]),
    )


def test_range_slice_matches_two_single_day_align():
    """单次区间切片 == 两次单日 closes_by_instrument；中间日不得污染首尾。"""
    from custom_strategy import closes_from_range_frame

    start_d, mid_d, end_d = "2026-01-05", "2026-01-08", "2026-01-12"
    # 中间日故意给离谱价格；点查语义不得用到它
    range_df = _qlib_range_frame(
        {
            start_d: {"SH600000": 10.0, "SZ000001": 20.0},
            mid_d: {"SH600000": 999.0, "SZ000001": 999.0},
            end_d: {"SH600000": 10.5, "SZ000001": 24.0},
        }
    )
    start_s, end_s = closes_from_range_frame(range_df, start_d, end_d)
    start_ref = closes_by_instrument(_qlib_day_frame(start_d, {"SH600000": 10.0, "SZ000001": 20.0}))
    end_ref = closes_by_instrument(_qlib_day_frame(end_d, {"SH600000": 10.5, "SZ000001": 24.0}))
    pd.testing.assert_series_equal(start_s.sort_index(), start_ref.sort_index(), check_names=False)
    pd.testing.assert_series_equal(end_s.sort_index(), end_ref.sort_index(), check_names=False)
    out = select_by_return_threshold(["SH600000", "SZ000001"], start_s, end_s, 0.15, 10)
    assert out == ["SH600000"]


def test_range_slice_missing_endpoint_is_none():
    """缺交易日端点 → None（与单日空 frame 回退一致），勿滑窗到中间日。"""
    from custom_strategy import closes_from_range_frame

    range_df = _qlib_range_frame(
        {
            "2026-01-08": {"SH600000": 10.0},
            "2026-01-12": {"SH600000": 10.5},
        }
    )
    start_s, end_s = closes_from_range_frame(range_df, "2026-01-05", "2026-01-12")
    assert start_s is None
    assert end_s is not None


def _bare_filter_strategy(*, close_cache=None):
    """绕过父类 signal 构造，只测涨幅过滤 IO 路径。"""
    from custom_strategy import TopkDropoutStrategyWithFilter

    strat = TopkDropoutStrategyWithFilter.__new__(TopkDropoutStrategyWithFilter)
    strat.max_return_threshold = 0.15
    strat.lookback_days = 5
    strat.timing_interval_steps = 10
    from custom_strategy import wide_close_from_features

    strat._close_wide = wide_close_from_features(close_cache) if close_cache is not None else None
    strat._bar_close_scratch = None
    strat.df_calls = 0
    return strat


def test_fallback_one_df_call_then_scratch_reuse(monkeypatch):
    """无宽表：一 bar 首次过滤 df_calls==1；补足重叠股不重复打；新增股再 +1。"""
    import custom_strategy as cs

    calls = []

    def fake_features(instruments, fields, start_time, end_time):
        instruments = list(instruments)
        calls.append({"instruments": instruments, "start": start_time, "end": end_time})
        # 区间内含两端 + 中间日
        frame = _qlib_range_frame(
            {
                start_time: {c: 10.0 for c in instruments},
                "2026-01-08": {c: 50.0 for c in instruments},
                end_time: {c: 10.5 for c in instruments},
            }
        )
        return frame

    monkeypatch.setattr(cs, "D", type("D", (), {"features": staticmethod(fake_features)})())
    monkeypatch.setattr(cs, "get_date_by_shift", lambda dt, n, future=False: {
        -1: "2026-01-12",
        -6: "2026-01-05",
    }[n])

    strat = _bare_filter_strategy()
    trade_day = "2026-01-13"
    first = ["SH600000", "SZ000001", "SH600519"]
    out1 = strat._filter_stocks_by_return_threshold(first, trade_day, 10)
    assert strat.df_calls == 1
    assert len(calls) == 1
    assert set(calls[0]["instruments"]) == set(first)
    assert calls[0]["start"] == "2026-01-05"
    assert calls[0]["end"] == "2026-01-12"
    assert out1 == first  # +5% 全过

    # 同 bar 补足：重叠 + 新股 → 只差量拉新股
    second = ["SZ000001", "SZ000002"]
    out2 = strat._filter_stocks_by_return_threshold(second, trade_day, 10)
    assert strat.df_calls == 2
    assert len(calls) == 2
    assert calls[1]["instruments"] == ["SZ000002"]
    assert out2 == second

    # 纯重叠再调：不再打 D.features
    out3 = strat._filter_stocks_by_return_threshold(["SH600000", "SZ000002"], trade_day, 10)
    assert strat.df_calls == 2
    assert len(calls) == 2
    assert out3 == ["SH600000", "SZ000002"]

    strat.clear_bar_close_scratch()
    assert strat._bar_close_scratch is None


def test_wide_cache_path_df_calls_stay_zero(monkeypatch):
    """有 _close_wide 时不打 D.features，df_calls 保持 0。"""
    import custom_strategy as cs

    def boom(*args, **kwargs):
        raise AssertionError("D.features must not be called when close_wide is set")

    monkeypatch.setattr(cs, "D", type("D", (), {"features": staticmethod(boom)})())
    monkeypatch.setattr(cs, "get_date_by_shift", lambda dt, n, future=False: {
        -1: "2026-01-12",
        -6: "2026-01-05",
    }[n])

    cache = _qlib_range_frame(
        {
            "2026-01-05": {"SH600000": 10.0, "SZ000001": 20.0},
            "2026-01-12": {"SH600000": 10.5, "SZ000001": 24.0},
        }
    )
    strat = _bare_filter_strategy(close_cache=cache)
    out = strat._filter_stocks_by_return_threshold(
        ["SH600000", "SZ000001"], "2026-01-13", 10
    )
    assert strat.df_calls == 0
    assert out == ["SH600000"]
