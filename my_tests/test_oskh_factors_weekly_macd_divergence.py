# -*- coding: utf-8 -*-
"""周线 MACD 底背离因子单测（oskh_factors，plan-weekly-macd-divergence-2026-07-20 v3 §8 P0）。

全部合成数据，不依赖本机 stock_data 行情树、不触 oskh_data（RFC-003 零依赖规约）。
覆盖：背离 / 非背离 / 三条件各自边界 / 合并 last_kept 语义 / trailing-52 计数窗口 /
MA200 unknown / 强度分级矩阵 / signal_date=该周最后交易日 / 端到端（DataFrame 入口）。

script 层（数据装载 loud fail / 标的枚举 / CLI wrapper）测试见
``tests/test_weekly_macd_divergence.py``。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from myquant_factors.weekly_macd_divergence import (
    DEFAULT_COUNT_WINDOW_WEEKS,
    _assess_trend_and_grade,
    _compute_macd,
    _daily_to_weekly,
    _find_candidates,
    _merge_and_classify,
    detect_weekly_macd_divergence,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _weekly_df(closes, difs=None, hists=None):
    """直接构造周线帧（绕开 MACD 计算，给条件判定喂确定值）。"""
    idx = pd.date_range("2020-01-03", periods=len(closes), freq="W-FRI")
    df = pd.DataFrame({"close": list(closes)}, index=idx)
    df["dif"] = list(difs) if difs is not None else 0.0
    df["macd_hist"] = list(hists) if hists is not None else 0.0
    df["_last_day"] = idx
    return df


def _ref_ema(values, span):
    """独立参考实现：EMA 种子=首值，alpha=2/(span+1)（交易软件口径）。"""
    alpha = 2.0 / (span + 1.0)
    out = [float(values[0])]
    for v in values[1:]:
        out.append(alpha * float(v) + (1.0 - alpha) * out[-1])
    return out


def _gen_divergence_daily():
    """260 周日线（每周 5 个交易日同值）：急跌→反弹→浅跌→缓穿前低，数值原型验证
    在 week 240-242 触发三条件（合并为 1 个 first 事件，uptrend=False → WEAK）。"""
    weekly_closes = [50 + 0.1 * i for i in range(130)]
    weekly_closes += [62.9 - 0.5 * (i - 129) for i in range(130, 180)]   # low#1 = 55.4 @179
    weekly_closes += [55.4 + 0.35 * (i - 179) for i in range(180, 200)]  # 反弹 62.4
    weekly_closes += [62.4 - 0.22 * (i - 199) for i in range(200, 230)]  # 浅跌 55.78
    weekly_closes += [55.78 - 0.08 * (i - 229) for i in range(230, 260)]  # 缓穿前低
    idx = pd.bdate_range("2015-01-05", periods=260 * 5, freq="B")  # 2015-01-05 周一
    closes = np.repeat(weekly_closes, 5)
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1000.0},
        index=idx,
    )


# ---------------------------------------------------------------------------
# 日线 → 周线聚合
# ---------------------------------------------------------------------------


def test_daily_to_weekly_aggregation():
    idx = pd.to_datetime(
        ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05",  # week1 Mon-Fri
         "2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11"]  # week2 Mon-Thu（周五休市）
    )
    close = [10, 11, 12, 13, 14, 20, 21, 22, 23]
    daily = pd.DataFrame(
        {
            "open": [c - 1 for c in close],
            "high": [c + 2 for c in close],
            "low": [c - 2 for c in close],
            "close": close,
            "volume": [100 * (i + 1) for i in range(9)],
        },
        index=idx,
    )
    weekly = _daily_to_weekly(daily)
    assert len(weekly) == 2
    w1, w2 = weekly.iloc[0], weekly.iloc[1]
    assert w1["open"] == 9 and w1["high"] == 16 and w1["low"] == 8 and w1["close"] == 14
    assert w1["volume"] == sum(100 * (i + 1) for i in range(5))
    assert w2["close"] == 23 and w2["open"] == 19
    # signal_date 真源 = 该周最后交易日（week2 周五休市 → 周四，非周五标签）
    assert pd.Timestamp(weekly["_last_day"].iloc[0]).date().isoformat() == "2024-01-05"
    assert pd.Timestamp(weekly["_last_day"].iloc[1]).date().isoformat() == "2024-01-11"


def test_daily_to_weekly_rejects_non_datetime_index():
    daily = pd.DataFrame({"close": [1.0, 2.0], "time": [1, 2]})
    with pytest.raises(TypeError):
        _daily_to_weekly(daily)


# ---------------------------------------------------------------------------
# MACD 计算（对标标准 EMA 口径）
# ---------------------------------------------------------------------------


def test_compute_macd_matches_reference_ema():
    closes = pd.Series([10 + 0.3 * i + 0.5 * np.sin(i / 3.0) for i in range(120)])
    macd = _compute_macd(closes, 12, 26, 9)
    ema12 = _ref_ema(closes, 12)
    ema26 = _ref_ema(closes, 26)
    ref_dif = [f - s for f, s in zip(ema12, ema26)]
    ref_dea = _ref_ema(ref_dif, 9)
    ref_hist = [(d - e) * 2 for d, e in zip(ref_dif, ref_dea)]
    assert np.allclose(macd["dif"].to_numpy(), ref_dif, atol=1e-12)
    assert np.allclose(macd["dea"].to_numpy(), ref_dea, atol=1e-12)
    assert np.allclose(macd["macd_hist"].to_numpy(), ref_hist, atol=1e-12)


# ---------------------------------------------------------------------------
# 第一级：候选三条件
# ---------------------------------------------------------------------------


def test_find_candidates_constructed_divergence():
    closes = [100.0 - i for i in range(66)]  # 严格递减：t=65 创 60 周新低
    difs = [-0.05 * i for i in range(63)] + [-2.9, -2.7, -2.5]  # t=62 触底回升 → t=65 DIF 未新低
    hists = [-0.30] * 62 + [-0.40, -0.50, -0.60, -0.20]  # t=65 绿柱收敛；t=63/64 扩张
    df = _weekly_df(closes, difs, hists)
    assert _find_candidates(df, lookback=60) == [65]


def test_find_candidates_condition_a_requires_strict_new_low():
    closes = [100.0 - i for i in range(65)] + [36.0]  # closes[65] == 窗口最小值 36，非严格 <
    difs = [-0.05 * i for i in range(63)] + [-2.9, -2.7, -2.5]
    hists = [-0.30] * 62 + [-0.40, -0.50, -0.60, -0.20]
    df = _weekly_df(closes, difs, hists)
    assert _find_candidates(df, lookback=60) == []


def test_find_candidates_condition_c_rejects_red_hist():
    # macd_hist > 0（红柱）abs 收缩 ≠ 绿柱收敛（v1 语义修正）
    closes = [100.0 - i for i in range(66)]
    difs = [-3.0 + 0.05 * i for i in range(66)]  # 持续回升，B 处处成立
    hists = [0.5] * 65 + [0.2]  # 红柱收缩
    df = _weekly_df(closes, difs, hists)
    assert _find_candidates(df, lookback=60) == []


def test_find_candidates_condition_c_rejects_expanding_green():
    closes = [100.0 - i for i in range(66)]
    difs = [-3.0 + 0.05 * i for i in range(66)]
    hists = [-0.1] * 65 + [-0.3]  # 绿柱扩张（abs 未收敛）
    df = _weekly_df(closes, difs, hists)
    assert _find_candidates(df, lookback=60) == []


# ---------------------------------------------------------------------------
# 第二级：合并 + 计数分类
# ---------------------------------------------------------------------------


def test_merge_gap_lt8_same_event():
    events = _merge_and_classify([100, 105], min_gap=8)
    assert len(events) == 1
    assert events[0]["pos"] == 100  # 保留首次出现点为代表
    assert events[0]["divergence_type"] == "first"


def test_merge_uses_last_kept_not_previous_candidate():
    # last_kept 语义：107-100=7<8 并入；114-100=14≥8 新事件（非 114-107=7<8 链式并入）
    events = _merge_and_classify([100, 107, 114], min_gap=8)
    assert [e["pos"] for e in events] == [100, 114]
    assert [e["divergence_type"] for e in events] == ["first", "second"]  # 间隔 14 ≤ 52


def test_count_window_trailing_52():
    events = _merge_and_classify([10, 20, 100], min_gap=8, count_window=DEFAULT_COUNT_WINDOW_WEEKS)
    assert [e["pos"] for e in events] == [10, 20, 100]
    # 100 与 10/20 间隔均 >52 → 窗口外事件不参与计数 → 重新 first
    assert [e["divergence_type"] for e in events] == ["first", "second", "first"]


def test_count_window_third_and_excessive():
    events = _merge_and_classify([100, 110, 120, 130, 140], min_gap=8)
    assert [e["divergence_type"] for e in events] == ["first", "second", "third", "excessive", "excessive"]


# ---------------------------------------------------------------------------
# 第三级：趋势 + 强度
# ---------------------------------------------------------------------------


def test_assess_trend_unknown_below_200_weeks():
    weekly = _weekly_df([10 + 0.1 * i for i in range(150)])  # 不足 200 周 → unknown
    events = [{"pos": 100, "divergence_type": "second"}, {"pos": 120, "divergence_type": "first"}]
    sigs = _assess_trend_and_grade(events, weekly, "000001.SZ", "2026-07-20")
    assert sigs[0].is_uptrend is None
    assert sigs[0].signal_strength == "MEDIUM"  # unknown 视为「不满足 uptrend 条件」→ second+非uptrend
    assert sigs[1].is_uptrend is None
    assert sigs[1].signal_strength == "WEAK"  # first+unknown
    assert "趋势未知" in sigs[0].description


def test_assess_strength_matrix_uptrend_and_downtrend():
    up = _weekly_df([10 + 0.1 * i for i in range(250)])  # close[220+] > MA200
    events = [
        {"pos": 220, "divergence_type": "second"},
        {"pos": 225, "divergence_type": "first"},
        {"pos": 230, "divergence_type": "third"},
        {"pos": 235, "divergence_type": "excessive"},
    ]
    sigs = _assess_trend_and_grade(events, up, "000001.SZ", "2026-07-20")
    assert [(s.is_uptrend, s.signal_strength) for s in sigs] == [
        (True, "STRONG"),   # second + uptrend
        (True, "MEDIUM"),   # first + uptrend
        (True, "WEAK"),     # third → 其他
        (True, "WEAK"),     # excessive → 其他
    ]
    down = _weekly_df([100 - 0.1 * i for i in range(250)])  # close < MA200
    sigs2 = _assess_trend_and_grade(events, down, "000001.SZ", "2026-07-20")
    assert [(s.is_uptrend, s.signal_strength) for s in sigs2] == [
        (False, "MEDIUM"),  # second + 非uptrend
        (False, "WEAK"),    # first + 非uptrend
        (False, "WEAK"),
        (False, "WEAK"),
    ]


def test_signal_date_is_last_trading_day_of_week():
    idx = pd.to_datetime(
        ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05",
         "2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11"]  # week2 周五休市
    )
    daily = pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": range(1, 10), "volume": 1.0}, index=idx
    )
    weekly = _daily_to_weekly(daily)
    weekly["dif"] = 0.0
    weekly["macd_hist"] = 0.0
    events = [{"pos": 1, "divergence_type": "first"}]
    sigs = _assess_trend_and_grade(events, weekly, "000001.SZ", "2026-07-20")
    assert sigs[0].signal_date == "2024-01-11"  # 周四（最后交易日），非周五标签 01-12


# ---------------------------------------------------------------------------
# 端到端（DataFrame 纯因子入口）
# ---------------------------------------------------------------------------


def test_detect_weekly_macd_divergence_end_to_end_constructed():
    daily = _gen_divergence_daily()
    sigs = detect_weekly_macd_divergence(daily, "000001.SZ", as_of_date="2026-07-20")
    assert sigs is not None and len(sigs) == 1
    sig = sigs[0]
    assert sig.signal_date == "2019-08-16"  # week 240 周五（数值原型锁定）
    assert sig.divergence_type == "first"
    assert sig.is_uptrend is False  # close 54.9 < MA200 56.37
    assert sig.signal_strength == "WEAK"
    assert sig.close == pytest.approx(54.9, abs=1e-3)
    assert "第1次底背离" in sig.description


def test_detect_weekly_macd_divergence_no_signal_uptrend():
    idx = pd.bdate_range("2015-01-05", periods=300 * 5, freq="B")
    closes = np.repeat([10 + 0.1 * i for i in range(300)], 5)  # 单调上升，无 60 周新低
    daily = pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1000.0}, index=idx
    )
    sigs = detect_weekly_macd_divergence(daily, "000001.SZ")
    assert sigs == []


def test_detect_weekly_macd_divergence_skips_insufficient_history():
    idx = pd.bdate_range("2024-01-01", periods=100, freq="B")  # ~20 周 < 260
    closes = np.linspace(10, 20, 100)
    daily = pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1000.0}, index=idx
    )
    assert detect_weekly_macd_divergence(daily, "000001.SZ") is None  # skipped


def test_detect_weekly_macd_divergence_none_or_empty_input():
    assert detect_weekly_macd_divergence(None, "000001.SZ") is None
    empty = pd.DataFrame({"open": [], "high": [], "low": [], "close": [], "volume": []},
                         index=pd.DatetimeIndex([]))
    assert detect_weekly_macd_divergence(empty, "000001.SZ") is None
