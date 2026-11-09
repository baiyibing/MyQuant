# -*- coding: utf-8 -*-
"""Float shares loaders and turnover estimation (RFC-003 §5.2)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional, cast

from myquant_factors._runtime import get_logger
from myquant_factors.chip.paths import stock_data_path

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 流通股本数据
# ---------------------------------------------------------------------------
# 默认值：100 亿股（中大盘典型值）。仅在 _estimate_turnover(float_shares=None) 窄路径使用。
_FLOAT_SHARES_DEFAULT: int = 10_000_000_000

# 模块级缓存
_float_shares_cache: Optional[pd.DataFrame] = None
_free_float_shares_cache: Optional[pd.DataFrame] = None


def _load_float_shares_map(parquet_path: Optional[str] = None) -> pd.DataFrame:
    """加载流通股本 Parquet（当前快照），缓存到模块级变量。"""
    global _float_shares_cache
    if _float_shares_cache is not None:
        return _float_shares_cache
    import os as _os
    if parquet_path is None:
        parquet_path = str(stock_data_path("float_shares.parquet"))
    if _os.path.exists(parquet_path):
        _float_shares_cache = pd.read_parquet(parquet_path)
    else:
        _float_shares_cache = pd.DataFrame()
    return _float_shares_cache


def _load_free_float_shares(parquet_path: Optional[str] = None) -> pd.DataFrame:
    """加载自由流通股本 Parquet（miniQMT Capital 财务表），缓存到模块级变量。"""
    global _free_float_shares_cache
    if _free_float_shares_cache is not None:
        return _free_float_shares_cache
    import os as _os
    if parquet_path is None:
        parquet_path = str(stock_data_path("free_float_shares.parquet"))
    if not _os.path.exists(parquet_path):
        _free_float_shares_cache = pd.DataFrame()
        return _free_float_shares_cache
    df = pd.read_parquet(parquet_path)
    if not df.empty and "m_timetag" in df.columns:
        df = df.copy()
        df["m_timetag"] = pd.to_datetime(df["m_timetag"]).dt.normalize()
    _free_float_shares_cache = df
    return _free_float_shares_cache


def _get_float_shares(stock_code: Optional[str] = None, date=None) -> float:
    """
    获取流通股本（circulating_capital / FloatVolume）。

    1. date is not None → free_float_shares.parquet → circulating_capital
    2. date is None     → float_shares.parquet → FloatVolume
    """
    if stock_code and date is not None:
        ffs = _load_free_float_shares()
        if not ffs.empty:
            target_date = cast(pd.Timestamp, pd.Timestamp(date)).normalize()  # pyright: ignore[reportAttributeAccessIssue]
            subset = ffs.loc[
                (ffs["stock_code"] == stock_code) & (ffs["m_timetag"] <= target_date)
            ]
            matches = subset.sort_values(by="m_timetag")
            if len(matches) > 0:
                row = matches.iloc[-1]
                fs = row.get("circulating_capital")
                if fs is not None and fs > 0:
                    gap_days = int((target_date - pd.Timestamp(row["m_timetag"])).days)
                    if gap_days > 90:
                        logger.warning(
                            "circulating_capital history gap >90 days",
                            context={
                                "stock": stock_code,
                                "target_date": target_date.strftime("%Y-%m-%d"),
                                "found_date": cast(pd.Timestamp, pd.Timestamp(row["m_timetag"])).strftime("%Y-%m-%d"),
                                "gap_days": gap_days,
                            },
                        )
                    return float(fs)

    if stock_code:
        df = _load_float_shares_map()
        if not df.empty:
            row = df[df["stock_code"] == stock_code]
            if len(row) > 0:
                fs = row.iloc[0].get("FloatVolume") or row.iloc[0].get("float_shares")  # v2 compat
                if fs is not None and fs > 0:
                    return float(fs)
        # P0-18 FIX: 有 stock_code 但找不到数据时抛异常，禁止静默回退 100 亿默认值
        logger.error(
            "float_shares missing",
            context={"stock": stock_code, "date": str(date)},
        )
        raise ValueError(
            f"float_shares missing for {stock_code}"
            f"{f' (date={date})' if date else ''}; "
            f"chip calculation cannot proceed with default"
        )

    # P0-18 FIX: stock_code=None 也不允许静默回退 —— 没有股票代码就无法查流通股本，
    # 使用 100 亿默认值会产生严重失真的筹码分布。调用方必须提供 stock_code。
    logger.error(
        "float_shares unavailable: stock_code not provided",
        context={"stock": stock_code, "date": str(date)},
    )
    raise ValueError(
        "float_shares unavailable: stock_code is required "
        "for chip calculation; cannot use 100亿 default"
    )


def _get_free_float_shares(stock_code: Optional[str] = None, date=None) -> float:
    """
    获取自由流通股本（freeFloatCapital）。

    查询逻辑：
    1. date is not None → 查 free_float_shares.parquet（Capital 财务表）
       → merge_asof: m_timetag <= target_date 的最新行
       → gap > 90 天：warning + 继续用旧值
    2. 查不到 → raise ValueError
       （不回退 FloatVolume：194 亿 vs 86 亿，不同口径）
    3. date is None → raise ValueError
       （get_instrument_detail 不返回 freeFloatCapital）
    """
    if stock_code and date is not None:
        ffs = _load_free_float_shares()
        if not ffs.empty:
            target_date = cast(pd.Timestamp, pd.Timestamp(date)).normalize()  # pyright: ignore[reportAttributeAccessIssue]
            subset = ffs.loc[
                (ffs["stock_code"] == stock_code) & (ffs["m_timetag"] <= target_date)
            ]
            matches = subset.sort_values(by="m_timetag")
            if len(matches) > 0:
                row = matches.iloc[-1]
                ff = row.get("freeFloatCapital")
                if ff is not None and ff > 0:
                    gap_days = int((target_date - pd.Timestamp(row["m_timetag"])).days)
                    if gap_days > 90:
                        logger.warning(
                            "freeFloatCapital history gap >90 days; using stale value "
                            "(free-float changes rarely, stale is better than switching to FloatVolume)",
                            context={
                                "stock": stock_code,
                                "target_date": target_date.strftime("%Y-%m-%d"),
                                "found_date": cast(pd.Timestamp, pd.Timestamp(row["m_timetag"])).strftime("%Y-%m-%d"),
                                "gap_days": gap_days,
                            },
                        )
                    return float(ff)

    raise ValueError(
        f"freeFloatCapital missing for {stock_code}"
        f"{f' (date={date})' if date else ''}"
        f"; FloatVolume fallback intentionally NOT used "
        f"(different metric: FloatVolume={194}亿 vs freeFloatCapital={86}亿 for 000001.SZ)"
    )


def _estimate_turnover(volume: np.ndarray, float_shares: Optional[float] = None) -> np.ndarray:
    """
    估算 turnover_rate。

    公式：turnover_rate = (volume * 100) / float_shares
    单位换算：volume（手） × 100 = 股 ÷ 流通股本（股）。

    Args:
        volume: 成交量数组（单位：手）
        float_shares: 流通股本（股）。为 None 时回退到 100 亿默认值。
                      P0-18 后主路径（adapt_columns→compute_chip_factors）已强制要求
                      stock_code 并 fail-close；None 分支仅服务于外部调用者
                      （chip_indicator TurnoverChipFactor 无 stock_code 时、chip_factor_analysis）。

    Returns:
        turnover_rate 数组（比例，0-1，非百分比）
    """
    if float_shares is None:
        logger.warning(
            "_estimate_turnover using 100亿 default float_shares; "
            "turnover_rate may be significantly distorted for small-cap stocks",
            context={},
        )
        fs = float(_FLOAT_SHARES_DEFAULT)
    else:
        fs = float_shares
    return (volume.astype(np.float64) * 100.0) / fs
