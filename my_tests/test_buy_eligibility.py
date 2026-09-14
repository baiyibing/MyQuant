"""买入资格过滤（buy_eligibility）与可交易宇宙构建器的纯函数单测。"""

from __future__ import annotations

import math
import os
import sys

import pandas as pd
import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from buy_eligibility import (  # noqa: E402
    MA5_SLOPE_MIN_DEG,
    BuyEligibilityFilter,
    buy_state_ok,
    load_extra_exclude,
    ma5_slope_deg,
    ma20_stand_ok,
)
from build_tradable_universe import drop_excluded, shift_start_for_age  # noqa: E402


CAL = list(pd.DatetimeIndex(pd.to_datetime(
    ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09",
     "2026-01-12", "2026-01-13", "2026-01-14", "2026-01-15", "2026-01-16"]
)))


def _ma5_pair(deg: float, ma5: float = 10.0) -> tuple[float, float]:
    """构造使通达信斜率恰好为 deg 的 (MA5, 昨日MA5)。"""
    prev = ma5 / (1.0 + math.tan(math.radians(deg)) / 100.0)
    return ma5, prev


def _feat(close, ma20, ma60, q10, ma5=10.0, ma5_prev=10.0):
    return [close, ma20, ma60, q10, ma5, ma5_prev]


def test_ma5_slope_deg():
    assert ma5_slope_deg(10.0, 10.0) == pytest.approx(0.0)
    ma5, prev = _ma5_pair(-30.0)
    assert ma5_slope_deg(ma5, prev) == pytest.approx(-30.0)
    assert math.isnan(ma5_slope_deg(10.0, float("nan")))
    assert math.isnan(ma5_slope_deg(10.0, 0.0))


def test_buy_state_ok_truth_table():
    flat = _ma5_pair(0.0)
    # 条件2：站上 MA20 且斜率未跌破 -30° → 可买（不要求条件1）
    assert buy_state_ok(11.0, 10.0, 9.0, 12.0, *flat) is True
    assert buy_state_ok(11.0, 10.0, 9.0, 12.0, *_ma5_pair(MA5_SLOPE_MIN_DEG)) is True
    assert buy_state_ok(11.0, 10.0, 9.0, 12.0, *_ma5_pair(-31.0)) is False
    assert ma20_stand_ok(11.0, 10.0, *flat) is True
    assert ma20_stand_ok(11.0, 10.0, *_ma5_pair(-45.0)) is False
    # 条件1：MA20/MA60 之下且低于 Q10；与条件2 为 OR，斜率不参与
    assert buy_state_ok(8.0, 10.0, 9.0, 8.5, *_ma5_pair(-45.0)) is True
    assert buy_state_ok(8.0, 10.0, 7.0, 7.5, *flat) is False   # 未深于 MA60
    assert buy_state_ok(8.5, 10.0, 7.0, 8.0, *flat) is False   # 未低于 Q10
    # NaN → 不可买
    assert buy_state_ok(float("nan"), 10.0, 9.0, 8.0, *flat) is False
    assert buy_state_ok(11.0, float("nan"), 9.0, 8.0, *flat) is False
    assert buy_state_ok(11.0, 10.0, 9.0, 12.0, float("nan"), 10.0) is False


def _make_filter(**kw):
    return BuyEligibilityFilter(
        st_codes={"SZ000001"},
        age_map={"SH600000": pd.Timestamp("2026-01-05"), "SZ300001": pd.Timestamp("2020-01-02")},
        age_days=3,
        calendar=CAL,
        **kw,
    )


def test_eligibility_st_and_age():
    f = _make_filter()
    # SZ000001 命中 ST 黑名单；SH600000 数据起始 2026-01-05 + 3 交易日 = 2026-01-08 才可买
    out = f.eligible(["SZ000001", "SH600000", "SH600519"], pd.Timestamp("2026-01-07"))
    assert out == ["SH600519"]  # SH600000 年龄不足
    out2 = f.eligible(["SZ000001", "SH600000", "SH600519"], pd.Timestamp("2026-01-08"))
    assert out2 == ["SH600000", "SH600519"]  # 年龄达标


def test_eligibility_unknown_age_passes():
    """不在 all.txt 登记里的代码（理论不存在）不设年龄限制。"""
    f = _make_filter()
    assert f.eligible(["SH688888"], pd.Timestamp("2026-01-05")) == ["SH688888"]


def test_eligibility_buy_state_filter():
    def fake_features(codes, start, end):
        # 逐码全窗特征：close, MA20, MA60, Q10, MA5, 昨日MA5
        steep = _ma5_pair(-45.0)
        data = {
            "SH600000": _feat(11.0, 10.0, 9.0, 12.0),              # 站上 MA20 + 斜率 0 → 可买
            "SH600001": _feat(8.0, 10.0, 9.0, 8.5, *steep),        # 深坑+低盈筹率（斜率再差也放行）
            "SH600002": _feat(8.5, 10.0, 7.0, 8.0),                # 中间态 → 不可买
            "SH600003": _feat(11.0, 10.0, 9.0, 12.0, *steep),      # 站上 MA20 但斜率过陡 → 不可买
        }
        dates = pd.DatetimeIndex(pd.to_datetime(["2026-03-02", "2026-03-03"]))
        rows, index = [], []
        for c in codes:
            if c not in data:
                continue
            for d in dates:
                rows.append(data[c])
                index.append((d, c))
        return pd.DataFrame(rows, index=pd.MultiIndex.from_tuples(index, names=["datetime", "instrument"]))

    codes = ["SH600000", "SH600001", "SH600002", "SH600003"]
    f = BuyEligibilityFilter(check_buy_state=True, features_fn=fake_features)
    f.preload(codes, "2026-03-01", "2026-03-05")
    out = f.eligible(codes, pd.Timestamp("2026-03-02"))
    assert out == ["SH600000", "SH600001"]
    out2 = f.eligible(codes, pd.Timestamp("2026-03-03"))
    assert out2 == ["SH600000", "SH600001"]


def test_load_extra_exclude_missing_file():
    assert load_extra_exclude(None) == set()
    assert load_extra_exclude("Z:/definitely/not/exist.txt") == set()


def test_drop_excluded():
    lines = ["sz000001\t2020-01-02\t2026-09-08", "SH600000\t2020-01-02\t2026-09-08"]
    keep, dropped = drop_excluded(lines, {"SZ000001"})
    assert keep == ["SH600000\t2020-01-02\t2026-09-08"]
    assert dropped == ["SZ000001"]  # 大小写不敏感


def test_shift_start_for_age():
    cal = pd.DatetimeIndex(pd.to_datetime([d.strftime("%Y-%m-%d") for d in CAL]))
    lines = [
        "SH600000\t2020-01-02\t2026-09-08",   # 日历外起始（老股）→ 不动
        "SZ300001\t2026-01-05\t2026-09-08",   # → 顺延 3 个交易日 = 2026-01-08
        "SZ300002\t2026-01-16\t2026-09-08",   # 顺延越界 → 不动
    ]
    out = shift_start_for_age(lines, cal, 3)
    assert out[0] == lines[0]
    assert out[1] == "SZ300001\t2026-01-08\t2026-09-08"
    assert out[2] == lines[2]


def test_shift_start_matches_strategy_age_map():
    """构建器顺延结果与 BuyEligibilityFilter 的最早可买日一致（同一日历同一偏移）。"""
    cal = pd.DatetimeIndex(pd.to_datetime([d.strftime("%Y-%m-%d") for d in CAL]))
    lines = ["SZ300001\t2026-01-05\t2026-09-08"]
    (shifted,) = shift_start_for_age(lines, cal, 3)
    new_start = pd.Timestamp(shifted.split("\t")[1])

    f = BuyEligibilityFilter(age_map={"SZ300001": pd.Timestamp("2026-01-05")}, age_days=3, calendar=CAL)
    assert f.min_trade_date["SZ300001"] == new_start
    assert f.eligible(["SZ300001"], pd.Timestamp("2026-01-07")) == []
    assert f.eligible(["SZ300001"], new_start) == ["SZ300001"]


def test_eligibility_precise_winner_ratio_overrides_proxy():
    """精确盈筹率命中时替代 Q10 代理：代理判深洗但精确值高 → 剔除；精确值低 → 放行。"""
    from datetime import date as _date

    def fake_features(codes, start, end):
        data = {
            "SH600001": _feat(8.0, 10.0, 9.0, 8.5),   # 代理判深洗（close<q10）
            "SH600002": _feat(8.0, 10.0, 9.0, 8.0),   # 代理判深洗
        }
        dates = pd.DatetimeIndex(pd.to_datetime(["2026-03-02"]))
        rows, index = [], []
        for c in codes:
            if c not in data:
                continue
            for d in dates:
                rows.append(data[c])
                index.append((d, c))
        return pd.DataFrame(rows, index=pd.MultiIndex.from_tuples(index, names=["datetime", "instrument"]))

    wr_map = {
        ("SH600001", _date(2026, 3, 2)): 0.55,  # 精确值高 → 代理误判，剔除
        ("SH600002", _date(2026, 3, 2)): 0.05,  # 精确值低 → 确认深洗，放行
    }
    f = BuyEligibilityFilter(check_buy_state=True, features_fn=fake_features, winner_ratio_map=wr_map)
    f.preload(["SH600001", "SH600002"], "2026-03-01", "2026-03-05")
    out = f.eligible(["SH600001", "SH600002"], pd.Timestamp("2026-03-02"))
    assert out == ["SH600002"]


def test_deep_washout_ok():
    from buy_eligibility import deep_washout_ok

    assert deep_washout_ok(8.0, 10.0, 9.0, 0.05) is True
    assert deep_washout_ok(8.0, 10.0, 9.0, 0.15) is False
    assert deep_washout_ok(11.0, 10.0, 9.0, 0.05) is False  # 站上 MA20 不走条件1
    assert deep_washout_ok(8.0, 10.0, 9.0, None) is False


def test_bulk_fetch_skips_quantile_when_winner_ratio_present():
    """有精确盈筹率时 preload 不再拉 Quantile($close,250)。"""
    from datetime import date as _date

    from buy_eligibility import BUY_STATE_FIELDS, BUY_STATE_FIELDS_CORE, BUY_STATE_Q10, BuyEligibilityFilter

    with_wr = BuyEligibilityFilter(
        check_buy_state=True,
        winner_ratio_map={("SH600000", _date(2026, 3, 2)): 0.05},
    )
    assert with_wr._buy_state_fetch_fields() == BUY_STATE_FIELDS_CORE
    assert BUY_STATE_Q10 not in with_wr._buy_state_fetch_fields()

    bare = BuyEligibilityFilter(check_buy_state=True)
    assert bare._buy_state_fetch_fields() == BUY_STATE_FIELDS
