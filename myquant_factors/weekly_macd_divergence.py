# -*- coding: utf-8 -*-
"""周线 MACD 底背离因子（纯算法，零 oskh_data 依赖 — RFC-003 包规约）。

方案 SSOT：``docs/engineering/plan-weekly-macd-divergence-2026-07-20.md`` v3。
输入为**前复权**日线 DataFrame（DatetimeIndex；复权由调用方/数据层保证——多年
轻新低检测必须复权，否则除权跳空 → 假新低 → 假背离），输出信号列表。
批量扫描 runner / 数据装载见 ``scripts/analysis/weekly_macd_divergence.py``。

三级判定：

1. 候选背离（60 周窗口三条件 AND）：价格创 60 周新低（严格 ``<``）+
   DIF 未同步新低 + 绿柱收敛（``macd_hist < 0`` 且 abs 收敛——v1 语义修正，
   需求文档伪代码未限定符号，但文字描述是「绿柱收敛」，红柱 abs 收缩不算）。
2. 合并 + 分类：相邻候选间隔 <8 周 → 同一次背离事件（v1 修参考代码 merge bug：
   与上一个 kept 候选比间隔 ``last_kept``，非 ``candidates[-1]``）；
   按 trailing-52 周窗口内事件序号标 first/second/third/excessive
   （防全程累加把 90 周前事件误当序列 → STRONG 误标）。
3. 趋势评级：``close > MA200`` → uptrend；不足 200 周 → ``is_uptrend=None``
   （unknown，强度判定时视为「不满足 uptrend 条件」）。

口径：

- 日线→周线：``resample('W-FRI')`` on **DatetimeIndex**（A 股交易日周 Mon-Fri，
  周收盘 = 该周最后交易日收盘）。
- MACD(12,26,9) ``ewm adjust=False``（标准交易软件口径，种子=首值）。
- ``signal_date`` = 该周**最后交易日**（非周五标签，节假日周对齐真实可交易日）。
- ``as_of_date`` = 扫描快照日（provenance，非 point-in-time）。前复权 repaint
  数学无害（乘性因子 c>0，min/max/符号比较不变 → 信号 date/type/strength 稳定）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, cast

import pandas as pd

# ---------------------------------------------------------------------------
# 常量（方案 §2 默认值，均可由入口参数覆盖）
# ---------------------------------------------------------------------------

DEFAULT_LOOKBACK_WEEKS = 60  # 条件 A/B 回望窗口（方案默认）
DEFAULT_MIN_GAP_WEEKS = 8  # 候选合并阈值：<8 周同一事件
DEFAULT_COUNT_WINDOW_WEEKS = 52  # 分类计数窗口（trailing-52 周，~1 年）
DEFAULT_MIN_HISTORY_WEEKS = 260  # skip 底线（295=MA200 全覆盖；260-294 可检但 trend=unknown）
MA200_WINDOW_WEEKS = 200
WEEK_RULE = "W-FRI"  # A 股交易日周 Mon-Fri，周五收盘为周收盘

_TYPE_BY_ORDINAL = {1: "first", 2: "second", 3: "third"}
TYPE_EXCESSIVE = "excessive"
STRENGTH_STRONG = "STRONG"
STRENGTH_MEDIUM = "MEDIUM"
STRENGTH_WEAK = "WEAK"

_TYPE_CN = {"first": "第1次底背离", "second": "第2次底背离", "third": "第3次底背离", TYPE_EXCESSIVE: "多次底背离(过度)"}
_TREND_CN = {True: "上涨趋势", False: "非上涨趋势", None: "趋势未知"}
_STRENGTH_CN = {STRENGTH_STRONG: "强烈买入", STRENGTH_MEDIUM: "中等关注", STRENGTH_WEAK: "信号较弱"}


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DivergenceSignal:
    """单条底背离信号（CSV 一行；r1 codex 🔴4 明确字段）。"""

    stock_code: str
    signal_date: str  # YYYY-MM-DD，该周最后交易日
    close: float  # 前复权周收盘
    dif: float
    macd_hist: float
    divergence_type: str  # first / second / third / excessive
    is_uptrend: Optional[bool]  # None = unknown（不足 200 周历史）
    signal_strength: str  # STRONG / MEDIUM / WEAK
    as_of_date: str  # 扫描快照日（provenance）
    description: str


# ---------------------------------------------------------------------------
# 管线各阶段（方案 §3 结构）
# ---------------------------------------------------------------------------


def _daily_to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """日线 → 周线（W-FRI）。``_last_day`` = 该周最后交易日（signal_date 真源）。"""
    if not isinstance(daily.index, pd.DatetimeIndex):
        raise TypeError(
            "daily 必须是 DatetimeIndex（reader 输出契约）；resample 不能用 on='time'（int64 ms 列会 TypeError）"
        )
    d = daily.copy()
    d["_last_day"] = d.index
    weekly = d.resample(WEEK_RULE).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "_last_day": "max",
        }
    )
    return cast(pd.DataFrame, weekly.dropna())


def _compute_macd(
    weekly_close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """标准 MACD：``ewm(span, adjust=False)``（交易软件口径，种子=首值）。"""
    ema_fast = weekly_close.ewm(span=fast, adjust=False).mean()
    ema_slow = weekly_close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_hist = (dif - dea) * 2
    return pd.DataFrame({"dif": dif, "dea": dea, "macd_hist": macd_hist})


def _find_candidates(macd_df: pd.DataFrame, lookback: int = DEFAULT_LOOKBACK_WEEKS) -> List[int]:
    """第一级：三条件 AND，返回候选点位置（positional int）。"""
    close = macd_df["close"].to_numpy(dtype=float)
    dif = macd_df["dif"].to_numpy(dtype=float)
    hist = macd_df["macd_hist"].to_numpy(dtype=float)
    candidates: List[int] = []
    for t in range(lookback, len(macd_df)):
        # 条件 A：价格创 lookback 周新低（严格 <，非 ≤）
        if not close[t] < close[t - lookback : t].min():
            continue
        # 条件 B：DIF 未同步新低（核心背离）
        if not dif[t] > dif[t - lookback : t].min():
            continue
        # 条件 C：绿柱收敛（v1 修正：限定 macd_hist < 0；红柱 abs 收缩不算）
        if not (hist[t] < 0 and abs(hist[t]) < abs(hist[t - 1])):
            continue
        candidates.append(t)
    return candidates


def _merge_and_classify(
    candidates: Sequence[int],
    min_gap: int = DEFAULT_MIN_GAP_WEEKS,
    count_window: int = DEFAULT_COUNT_WINDOW_WEEKS,
) -> List[Dict[str, Any]]:
    """第二级：相邻候选 <min_gap 周合并为同一事件 + trailing-count_window 计数分类。

    v1 修参考代码 merge bug：与上一个 **kept** 候选比间隔（``last_kept``），
    非 ``candidates[-1]``（随 filtered 增长变化）。合并保留首次出现点为代表
    （信号最早可行动日）。
    """
    events: List[Dict[str, Any]] = []
    last_kept: Optional[int] = None
    for pos in candidates:
        if last_kept is None or pos - last_kept >= min_gap:
            events.append({"pos": pos, "divergence_type": ""})
            last_kept = pos
        # 间隔 < min_gap → 并入当前事件（不新建；仍与 last_kept 比下一个）
    positions = [e["pos"] for e in events]
    for i, ev in enumerate(events):
        ordinal = 1 + sum(1 for p in positions[:i] if 0 < ev["pos"] - p <= count_window)
        ev["divergence_type"] = _TYPE_BY_ORDINAL.get(ordinal, TYPE_EXCESSIVE)
    return events


def _describe(divergence_type: str, is_uptrend: Optional[bool], strength: str) -> str:
    return f"{_TYPE_CN.get(divergence_type, divergence_type)} {_TREND_CN[is_uptrend]} {_STRENGTH_CN.get(strength, strength)}"


def _assess_trend_and_grade(
    events: Sequence[Dict[str, Any]],
    weekly: pd.DataFrame,
    stock_code: str,
    as_of_date: str,
) -> List[DivergenceSignal]:
    """第三级：MA200 趋势 + STRONG/MEDIUM/WEAK 评级，落成 DivergenceSignal。

    MA200 = 200 周滚动均值；不足 200 周 → ``is_uptrend=None``（unknown），
    强度判定中视为「不满足 uptrend 条件」（v3 §2.5：不系统性降级较早信号，
    但 CSV 标注 unknown 与 False 区别）。
    """
    ma200 = cast(pd.Series, weekly["close"].rolling(MA200_WINDOW_WEEKS).mean())
    signals: List[DivergenceSignal] = []
    for ev in events:
        t = int(ev["pos"])
        ma = ma200.iloc[t]
        is_uptrend: Optional[bool] = None if pd.isna(ma) else bool(weekly["close"].iloc[t] > ma)
        dtype = str(ev["divergence_type"])
        if dtype == "second" and is_uptrend is True:
            strength = STRENGTH_STRONG
        elif (dtype == "first" and is_uptrend is True) or (dtype == "second" and is_uptrend is not True):
            strength = STRENGTH_MEDIUM
        else:
            strength = STRENGTH_WEAK
        signal_day = cast(pd.Timestamp, pd.Timestamp(weekly["_last_day"].iloc[t])).date().isoformat()
        signals.append(
            DivergenceSignal(
                stock_code=stock_code,
                signal_date=signal_day,
                close=round(float(weekly["close"].iloc[t]), 3),
                dif=round(float(weekly["dif"].iloc[t]), 4),
                macd_hist=round(float(weekly["macd_hist"].iloc[t]), 4),
                divergence_type=dtype,
                is_uptrend=is_uptrend,
                signal_strength=strength,
                as_of_date=as_of_date,
                description=_describe(dtype, is_uptrend, strength),
            )
        )
    return signals


def detect_weekly_macd_divergence(
    daily: Optional[pd.DataFrame],
    stock_code: str,
    *,
    lookback: int = DEFAULT_LOOKBACK_WEEKS,
    min_gap: int = DEFAULT_MIN_GAP_WEEKS,
    count_window: int = DEFAULT_COUNT_WINDOW_WEEKS,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    min_history_weeks: int = DEFAULT_MIN_HISTORY_WEEKS,
    as_of_date: str = "",
) -> Optional[List[DivergenceSignal]]:
    """纯因子入口：前复权日线 DataFrame → 底背离信号列表。

    ``daily`` 须为 DatetimeIndex、含 ``open/high/low/close/volume`` 列（reader 输出
    契约）。返回 ``list[DivergenceSignal]``（可为空 = 无信号）；``None`` = skipped
    （空数据或周线数 < ``min_history_weeks``）。
    """
    if daily is None or len(daily) == 0:
        return None
    weekly = _daily_to_weekly(daily)
    if len(weekly) < min_history_weeks:
        return None
    macd = _compute_macd(cast(pd.Series, weekly["close"]), fast, slow, signal)
    weekly = pd.concat([weekly, macd], axis=1)
    candidates = _find_candidates(weekly, lookback=lookback)
    events = _merge_and_classify(candidates, min_gap=min_gap, count_window=count_window)
    return _assess_trend_and_grade(events, weekly, stock_code, as_of_date)
