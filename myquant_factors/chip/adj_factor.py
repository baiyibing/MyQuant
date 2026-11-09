# -*- coding: utf-8 -*-
"""Adj factor provider and minute price adjustment (RFC-003 §5.3)."""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
from typing import Optional, cast

from myquant_factors.chip.paths import stock_data_path


class StaleDataError(ValueError):
    """adj_factor data does not cover the requested date's prior trading day."""


# ---------------------------------------------------------------------------
# 复权因子表（§10.4.2 方案 B 前置基建）
# ---------------------------------------------------------------------------
_adj_factor_cache: Optional[pd.DataFrame] = None
_data_max_date: Optional[pd.Timestamp] = None
_adj_factor_parquet_path: Optional[str] = None


def reset_adj_factor_cache_for_testing() -> None:
    """测试专用：清空模块级 adj_factor 缓存。"""
    global _adj_factor_cache, _data_max_date, _adj_factor_parquet_path
    _adj_factor_cache = None
    _data_max_date = None
    _adj_factor_parquet_path = None


def _load_adj_factor_table(parquet_path: Optional[str] = None) -> pd.DataFrame:
    """加载复权因子表，缓存到模块级变量。"""
    global _adj_factor_cache, _data_max_date, _adj_factor_parquet_path
    if parquet_path is None:
        parquet_path = str(stock_data_path("adj_factor.parquet"))
    if _adj_factor_cache is not None and _adj_factor_parquet_path == parquet_path:
        return _adj_factor_cache
    _adj_factor_parquet_path = parquet_path
    if os.path.exists(parquet_path):
        _adj_factor_cache = pd.read_parquet(parquet_path)
    else:
        _adj_factor_cache = pd.DataFrame()
    from myquant_infra.bars.adj_factor_meta import read_adj_factor_data_max_date

    sidecar_max = read_adj_factor_data_max_date(parquet_path)
    if sidecar_max is not None:
        _data_max_date = sidecar_max
    elif _adj_factor_cache is not None and not _adj_factor_cache.empty and "date" in _adj_factor_cache.columns:
        _max_raw = pd.to_datetime(_adj_factor_cache["date"], errors="coerce").max()
        if bool(pd.isna(_max_raw)):
            _data_max_date = None
        else:
            _data_max_date = cast(pd.Timestamp, _max_raw).normalize()
    else:
        _data_max_date = None
    return _adj_factor_cache


def get_adj_factor(
    stock_code: str,
    date,
    *,
    strict: bool = True,
    max_staleness_trading_days: int = -1,
) -> float:
    """
    查询指定标的在指定日期的累积复权乘数因子。

    Args:
        stock_code: 如 '000001.SZ'
        date: 日期（str 'YYYY-MM-DD' 或 pd.Timestamp）
        strict: 空表/缺行/NaN 时抛 ValueError
        max_staleness_trading_days: freshness 检查（opt-in）。
            ``-1`` = 不检查（默认，向后兼容）；``0`` = v4 gate 用，要求覆盖上一交易日。

    Returns:
        cumulative_adj_factor = close_front / close_none。
    """
    df = _load_adj_factor_table()
    if df.empty:
        if strict:
            raise ValueError("adj_factor table is empty; cannot compute adjusted minute prices safely")
        return 1.0
    if isinstance(date, str):
        date_ts = pd.Timestamp(date)
    else:
        date_ts = pd.Timestamp(str(date))
    if bool(pd.isna(date_ts)):
        raise ValueError(f"invalid adj_factor date for {stock_code}: {date!r}")
    date_ts_ok = cast(pd.Timestamp, date_ts)

    if max_staleness_trading_days >= 0 and _data_max_date is not None:
        from myquant_factors._runtime import previous_trading_day as get_previous_trading_day

        prev_td_str = get_previous_trading_day(
            cast(pd.Timestamp, date_ts_ok - pd.Timedelta(days=1))
        )
        prev_td = cast(pd.Timestamp, pd.Timestamp(prev_td_str)).normalize()  # pyright: ignore[reportAttributeAccessIssue]
        watermark = prev_td - pd.Timedelta(days=max_staleness_trading_days)
        data_max = cast(pd.Timestamp, _data_max_date)
        if data_max.normalize() < watermark:  # pyright: ignore[reportAttributeAccessIssue]
            raise StaleDataError(
                f"adj_factor stale: covers up to {data_max.date()}, "
                f"previous trading day is {prev_td.date()}"
            )

    # date32 parquet loads as object[datetime.date]; Timestamp == date is always
    # False (2026-09-01 G4: 600000.SH@2026-08-04 exists, lookup missed →
    # ValueError → wiring turtle_ma10_degraded/adj_stale).
    sub = df[df["stock_code"] == stock_code]
    if sub.empty:
        row = sub
    else:
        converted = pd.to_datetime(sub["date"], errors="coerce")
        if not isinstance(converted, pd.Series):
            converted = pd.Series(converted, index=sub.index)
        row = sub.loc[converted.dt.normalize() == date_ts_ok.normalize()]
    if len(row) > 0:
        factor = float(row.iloc[0]["cumulative_adj_factor"])
        if pd.isna(factor):
            msg = (
                f"adj_factor is NaN for {stock_code} @ "
                f"{date_ts_ok.strftime('%Y-%m-%d')} "
                f"(front/none data alignment issue at data boundary)"
            )
            if strict:
                raise ValueError(msg)
            return float("nan")
        return factor
    if strict:
        raise ValueError(
            f"adj_factor missing for {stock_code} @ {date_ts_ok.strftime('%Y-%m-%d')}"
        )
    return 1.0


def adj_minute_prices(
    stock_code: str, date, minute_close: np.ndarray,
    minute_high: Optional[np.ndarray] = None, minute_low: Optional[np.ndarray] = None,
) -> dict:
    """
    将未复权分钟线价格校正为等效前复权价格（§10.4.2 方案 B）。

    公式：adj_price = unadj_price × cumulative_adj_factor_at_date
    """
    factor = get_adj_factor(stock_code, date, strict=True)
    result = {"close": minute_close * factor}
    if minute_high is not None:
        result["high"] = minute_high * factor
    if minute_low is not None:
        result["low"] = minute_low * factor
    return result
