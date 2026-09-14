"""买入资格过滤（buy_eligibility）与可交易宇宙构建器的纯函数单测。"""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from buy_eligibility import (  # noqa: E402
    BuyEligibilityFilter,
    buy_state_ok,
    load_extra_exclude,
)
from build_tradable_universe import drop_excluded, shift_start_for_age  # noqa: E402


CAL = list(pd.DatetimeIndex(pd.to_datetime(
    ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09",
     "2026-01-12", "2026-01-13", "2026-01-14", "2026-01-15", "2026-01-16"]
)))


def test_buy_state_ok_truth_table():
    # 站上 MA20 → 可买（无论 MA60/盈筹率）
    assert buy_state_ok(11.0, 10.0, 9.0, 12.0) is True
    # MA20 之下：需同时深于 MA60 且低于 Q10（盈筹率<10% 近似）
    assert buy_state_ok(8.0, 10.0, 9.0, 8.5) is True
    assert buy_state_ok(8.0, 10.0, 7.0, 7.5) is False   # 未深于 MA60
    assert buy_state_ok(8.5, 10.0, 7.0, 8.0) is False   # 未低于 Q10
    # NaN → 不可买
    assert buy_state_ok(float("nan"), 10.0, 9.0, 8.0) is False
    assert buy_state_ok(11.0, float("nan"), 9.0, 8.0) is False


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
        # 逐码全窗特征：close, MA20, MA60, Q10
        data = {
            "SH600000": [11.0, 10.0, 9.0, 12.0],   # 站上 MA20 → 可买
            "SH600001": [8.0, 10.0, 9.0, 8.5],     # 深坑+低盈筹率 → 可买
            "SH600002": [8.5, 10.0, 7.0, 8.0],     # 中间态 → 不可买
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

    f = BuyEligibilityFilter(check_buy_state=True, features_fn=fake_features)
    f.preload(["SH600000", "SH600001", "SH600002"], "2026-03-01", "2026-03-05")
    out = f.eligible(["SH600000", "SH600001", "SH600002"], pd.Timestamp("2026-03-02"))
    assert out == ["SH600000", "SH600001"]
    out2 = f.eligible(["SH600000", "SH600001", "SH600002"], pd.Timestamp("2026-03-03"))
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
