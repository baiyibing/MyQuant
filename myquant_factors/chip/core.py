# -*- coding: utf-8 -*-
"""Chip distribution and cross-day turnover resistance core (RFC-003 §5.1)."""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
from typing import Optional, cast

from myquant_factors._runtime import get_logger
from myquant_factors.distribution_of_chips import make_price_grid
from myquant_factors import cyq
from myquant_factors.cyq import calc_curpdf
from myquant_factors import turnover_coefficient_ops as tco

from myquant_factors.chip.adj_factor import get_adj_factor
from myquant_factors.chip.shares import (
    _estimate_turnover,
    _get_float_shares,
    _get_free_float_shares,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 列名适配器
# ---------------------------------------------------------------------------
def adapt_columns(
    df: pd.DataFrame,
    stock_code: Optional[str] = None,
    as_of_date: Optional[pd.Timestamp] = None,
    use_free_float: bool = False,
) -> np.ndarray:
    """
    适配 backtrader DataFrame 列名到 cyq.py 期望的列名契约。

    cyq.py:100 要求 [\"close\", \"high\", \"low\", \"vol\", \"turnover_rate\"]
    现有数据：volume（非 vol），无 turnover_rate。
    传入 stock_code 时从 float_shares.parquet / history 获取流通股本计算 turnover_rate。

    Args:
        df: backtrader 风格的 DataFrame（columns: close, high, low, volume）
        stock_code: 标的代码（如 '000001.SZ'），用于查找真实流通股本
        as_of_date: 可选，按该日期查询历史股本（用于回测避免前视）
        use_free_float: True=自由流通股本（freeFloatCapital），False=流通股本（FloatVolume）

    Returns:
        np.ndarray with columns: close, high, low, vol, turnover_rate
    """
    df = df.rename(columns={"volume": "vol"})
    if "turnover_rate" not in df.columns:
        if use_free_float:
            float_shares = _get_free_float_shares(stock_code, date=as_of_date)
        else:
            float_shares = _get_float_shares(stock_code, date=as_of_date)
        df["turnover_rate"] = _estimate_turnover(
            np.asarray(df["vol"].values, dtype=np.float64), float_shares
        )
    return cast(
        np.ndarray,
        df[["close", "high", "low", "vol", "turnover_rate"]].values,
    )


# ---------------------------------------------------------------------------
# 日线筹码分布（三角/均匀 PDF fallback）
# ---------------------------------------------------------------------------
def daily_chip_distribution(arr: np.ndarray, method: str = "triang") -> pd.Series:
    """
    日线筹码分布：使用三角/均匀 PDF 假设。

    直接委托给 qlib_cost 的 calc_dist_chips()。

    Args:
        arr: adapt_columns() 输出 (N, 5) 数组
        method: "triang" 或 "uniform"

    Returns:
        pd.Series, index=price, values=chip volume
    """
    return cyq.calc_dist_chips(arr, method=method)


# ---------------------------------------------------------------------------
# 分钟线筹码分布（实际量价累积，跳过 PDF 假设）
# Optional numba path gated like scan_held_day (H15 / D2).
# ---------------------------------------------------------------------------

try:
    from numba import njit as _njit  # type: ignore

    @_njit(cache=True)
    def _minute_chip_cumpdf_numba(close, vol, decay, diff, min_p, step, n_bins):
        """Accumulate + normalize cumpdf; mirrors minute_chip_distribution_python."""
        cumpdf = np.zeros(n_bins, dtype=np.float64)
        n = len(close)
        for i in range(n):
            c = close[i]
            v = vol[i]
            if np.isnan(c) or v <= 0.0:
                continue
            idx = int((c - min_p) / step)
            if idx < 0:
                idx = 0
            elif idx >= n_bins:
                idx = n_bins - 1
            add = v * decay[i]
            if i == 0:
                for j in range(n_bins):
                    cumpdf[j] = 0.0
                cumpdf[idx] = add
            else:
                scale = diff[i]
                for j in range(n_bins):
                    cumpdf[j] *= scale
                cumpdf[idx] += add
        return cumpdf

    _NUMBA_MINUTE_CHIP_AVAILABLE = True
except Exception:  # pragma: no cover - optional dep
    _NUMBA_MINUTE_CHIP_AVAILABLE = False
    _minute_chip_cumpdf_numba = None  # type: ignore


def _want_numba_minute_chip(use_numba: Optional[bool]) -> bool:
    if use_numba is True:
        return True
    if use_numba is False:
        return False
    backend = (os.environ.get("MINUTE_CHIP_BACKEND") or "python").strip().lower()
    return backend in {"numba", "jit"}


def _minute_chip_empty_series(stock_code: str, min_p: float, max_p: float) -> pd.Series:
    label = f"{stock_code} " if stock_code else ""
    reason = (
        f"{label}价格全部相同 (max={max_p} <= min={min_p})，"
        f"可能原因：停牌、一字板涨跌停、或数据异常"
    )
    logger.warning(reason)
    return pd.Series(dtype=float, name="cumpdf")


def minute_chip_distribution_python(
    arr: np.ndarray,
    step: float = 0.01,
    stock_code: str = "",
) -> pd.Series:
    """
    Python reference for minute-line chip distribution (semantic lock).

    用每分钟的实际 (close, volume) 构建直方图；跳过三角/均匀 PDF。
    """
    close = arr[:, 0]   # 分钟 close
    vol = arr[:, 3]     # 分钟 volume
    turnover = arr[:, 4]  # 分钟 turnover_rate（从日线按 volume 占比分配后）

    min_p = float(np.nanmin(close))
    max_p = float(np.nanmax(close))
    if np.isnan(min_p) or np.isnan(max_p) or max_p <= min_p:
        # P1-5 fix: 记录原因（停牌/一字板/数据异常），不再静默返回空
        return _minute_chip_empty_series(stock_code, min_p, max_p)

    price_bins = make_price_grid(min_p, max_p, step)
    cumpdf = np.zeros(len(price_bins), dtype=np.float64)

    # 按日期分组，每日内用 decay 模型累积
    # arr 按时间排序，每日的 decay 由该日的分钟 turnover_rate 计算
    decay = turnover.copy()
    diff = 1.0 - decay

    for i in range(len(close)):
        if np.isnan(close[i]) or vol[i] <= 0:
            continue
        # 找到该分钟的成交量归属的价格 bin
        idx = int((close[i] - min_p) / step)
        if idx < 0:
            idx = 0
        elif idx >= len(price_bins):
            idx = len(price_bins) - 1

        curpdf = np.zeros(len(price_bins), dtype=np.float64)
        curpdf[idx] = vol[i] * decay[i]

        if i == 0:
            cumpdf = curpdf
        else:
            cumpdf = cumpdf * diff[i] + curpdf

    # 归一化
    total = cumpdf.sum()
    if total > 0:
        cumpdf /= total

    return pd.Series(cumpdf, index=price_bins, name="cumpdf")


def _minute_chip_distribution_numba(
    arr: np.ndarray,
    step: float = 0.01,
    stock_code: str = "",
) -> pd.Series:
    """Numba-backed minute chip path; must bit-close match the Python reference."""
    close = np.ascontiguousarray(arr[:, 0], dtype=np.float64)
    vol = np.ascontiguousarray(arr[:, 3], dtype=np.float64)
    turnover = np.ascontiguousarray(arr[:, 4], dtype=np.float64)

    min_p = float(np.nanmin(close))
    max_p = float(np.nanmax(close))
    if np.isnan(min_p) or np.isnan(max_p) or max_p <= min_p:
        return _minute_chip_empty_series(stock_code, min_p, max_p)

    price_bins = make_price_grid(min_p, max_p, step)
    decay = turnover.copy()
    diff = 1.0 - decay
    cumpdf = _minute_chip_cumpdf_numba(
        close, vol, decay, diff, min_p, float(step), len(price_bins)
    )
    # Normalize in NumPy (same as Python reference) for bit-close parity.
    total = cumpdf.sum()
    if total > 0:
        cumpdf = cumpdf / total
    return pd.Series(cumpdf, index=price_bins, name="cumpdf")


def minute_chip_distribution(
    arr: np.ndarray,
    step: float = 0.01,
    stock_code: str = "",
    use_numba: Optional[bool] = None,
) -> pd.Series:
    """
    分钟线筹码分布：用每分钟的实际 (close, volume) 构建直方图。

    跳过三角/均匀 PDF 假设，直接用量价累积。
    但仍需假设分钟内成交价格代表值为 close。

    Default backend is the Python reference. Optional numba path is gated by
    ``use_numba=True`` or env ``MINUTE_CHIP_BACKEND=numba`` (or ``jit``).

    Args:
        arr: adapt_columns() 输出 (N, 5) 数组。
             N ≈ 80 天 × 240 分钟 = 19,200。
             columns: close, high, low, vol, turnover_rate
        step: 价格步长（元）
        stock_code: 标的代码（仅用于异常时的日志上下文）
        use_numba: None=env/default python; True=force numba if available;
            False=force Python reference

    Returns:
        pd.Series, index=price（以 step 为步长）, values=累计 chip volume
    """
    if (
        _want_numba_minute_chip(use_numba)
        and _NUMBA_MINUTE_CHIP_AVAILABLE
        and _minute_chip_cumpdf_numba is not None
    ):
        return _minute_chip_distribution_numba(arr, step=step, stock_code=stock_code)
    return minute_chip_distribution_python(arr, step=step, stock_code=stock_code)


# ---------------------------------------------------------------------------
# 方案 A：日线定框架 + 分钟线做日内偏移（§10.4.2）
# ---------------------------------------------------------------------------
def hybrid_chip_distribution(
    daily_arr: np.ndarray,
    minute_today_arr: np.ndarray,
    step: float = 0.01,
) -> pd.Series:
    """
    混合筹码分布：历史日线三角PDF + 当日分钟线量价累积。

    §10.4.2 方案 A — 日线定框架，分钟线只做当日新开仓成本的微调。
    与 pure minute (80天×240分钟) 相比，大幅降低计算量。

    Args:
        daily_arr: adapt_columns() 输出 (N, 5)，N 天日线，最后一行为当日
        minute_today_arr: adapt_columns() 输出 (M, 5)，当日分钟线
        step: 价格步长（元）

    Returns:
        pd.Series, index=price, values=累计 chip volume
    """
    # 价格网格：覆盖日线 + 分钟线的完整范围
    max_p = max(float(np.nanmax(daily_arr[:, 1])),
                float(np.nanmax(minute_today_arr[:, 0])))
    min_p = min(float(np.nanmin(daily_arr[:, 2])),
                float(np.nanmin(minute_today_arr[:, 0])))
    if max_p <= min_p:
        # P1-5 fix
        logger.warning(
            f"hybrid_chip_distribution: 日线+分钟线价格范围为空 "
            f"(max={max_p} <= min={min_p})，可能停牌或数据异常"
        )
        return pd.Series(dtype=float, name="cumpdf")

    xs = make_price_grid(min_p, max_p, step)
    n_days = len(daily_arr)
    curpdfs = np.zeros((n_days, len(xs)), dtype=np.float64)

    # 历史日（0 到 n_days-2）：三角 PDF
    for i in range(n_days - 1):
        curpdfs[i] = cyq.calc_curpdf(
            float(daily_arr[i, 0]), float(daily_arr[i, 1]),
            float(daily_arr[i, 2]), float(daily_arr[i, 3]),
            min_p, max_p, step, method="triang",
        )

    # 当日（最后一"天"）：分钟线量价直方图
    today_close = minute_today_arr[:, 0]
    today_vol = minute_today_arr[:, 3]
    today_pdf = np.zeros(len(xs), dtype=np.float64)
    for j in range(len(today_close)):
        if np.isnan(today_close[j]) or today_vol[j] <= 0:
            continue
        idx = int((today_close[j] - min_p) / step)
        if 0 <= idx < len(xs):
            today_pdf[idx] += today_vol[j]
    if today_pdf.sum() > 0:
        today_pdf /= today_pdf.sum()
    curpdfs[n_days - 1] = today_pdf

    # 换手率：历史日用日线值，当日用日线值（分钟 turnover 之和应与日线一致）
    turnover = daily_arr[:, 4].copy()

    cum_vol = cyq.calc_cumpdf(curpdfs, turnover)
    return pd.Series(cum_vol, index=xs, name="cumpdf")


def adj_minute_chip_distribution(
    arr: np.ndarray,
    stock_code: str,
    date,
    step: float = 0.01,
) -> pd.Series:
    """
    方案 B：复权因子校正后的分钟线筹码分布（§10.4.2）。

    流程：
    1. 用 get_adj_factor() 查询该标的首日的累积复权乘数
    2. 对价格列（close/high/low）乘上复权因子，量列（vol/turnover_rate）不变
    3. 调用 minute_chip_distribution() 计算筹码分布

    Args:
        arr: adapt_columns() 输出 (N, 5)，未复权分钟线
        stock_code: 标的代码
        date: 截面日期（用于查询复权因子）
        step: 价格步长

    Returns:
        pd.Series, index=price（等效前复权）, values=chip volume
    """
    factor = get_adj_factor(stock_code, date, strict=True)
    # P1-2: NaN 保护 — 复权因子不可用时不应进入筹码计算
    if pd.isna(factor):
        raise ValueError(
            f"adj_minute_chip_distribution: factor is NaN for {stock_code} @ {date}"
        )
    if factor == 1.0:
        # 无复权差异，直接走原始路径
        return minute_chip_distribution(arr, step=step)

    arr_adj = arr.copy()
    arr_adj[:, 0] = arr[:, 0] * factor  # close
    arr_adj[:, 1] = arr[:, 1] * factor  # high
    arr_adj[:, 2] = arr[:, 2] * factor  # low
    # vol (col 3) 和 turnover_rate (col 4) 保持不变

    return minute_chip_distribution(arr_adj, step=step)


# ---------------------------------------------------------------------------
# 便捷函数：从 DataFrame 一步计算 ChipFactor
# ---------------------------------------------------------------------------
def compute_chip_factors(
    df: pd.DataFrame,
    method: str = "triang",
    data_freq: str = "1d",
    stock_code: Optional[str] = None,
    daily_df: Optional[pd.DataFrame] = None,
) -> dict:
    """
    从 backtrader 风格的 DataFrame 计算 4 个筹码分布因子。

    Args:
        df: 包含 close, high, low, volume 列的 DataFrame（N 行窗口）
        method: 日线模式用 "triang" 或 "uniform"；分钟线模式忽略
        data_freq: "1d" 或 "1m"
        stock_code: 股票代码（如 "000001.SZ"），用于查找真实流通股本。
                    为 None 时抛 ValueError（P0-18 强制要求传入有效 stock_code）
        daily_df: 日线前复权 DataFrame（仅 data_freq="1m" 时需要）。
                  用于 hybrid_chip_distribution —— 历史日线定框架 + 当日分钟线微调，
                  解决 QMT 分钟线不支持复权导致的除权日筹码失真。

    Returns:
        dict with keys: cyqk_c, asr, ckdw, prp
    """
    as_of_date = None
    if isinstance(df.index, pd.DatetimeIndex) and len(df.index) > 0:
        as_of_date = cast(pd.Timestamp, pd.Timestamp(str(df.index[-1]))).normalize()  # pyright: ignore[reportAttributeAccessIssue]
    arr = adapt_columns(df, stock_code=stock_code, as_of_date=as_of_date)

    if data_freq == "1m":
        # P0-4 fix: 分钟线模式使用 hybrid 路径，日线 front 定框架 + 分钟线 none 微调
        if daily_df is not None and len(daily_df) > 0:
            daily_as_of = None
            if isinstance(daily_df.index, pd.DatetimeIndex) and len(daily_df.index) > 0:
                daily_as_of = cast(pd.Timestamp, pd.Timestamp(str(daily_df.index[-1]))).normalize()  # pyright: ignore[reportAttributeAccessIssue]
            daily_arr = adapt_columns(
                daily_df,
                stock_code=stock_code,
                as_of_date=daily_as_of,
            )
            dist = hybrid_chip_distribution(daily_arr, arr)
        else:
            raise ValueError(
                "data_freq='1m' 需要 daily_df 参数（日线前复权数据）。"
                "纯分钟线筹码分布在除权日前后存在价格断裂，已弃用。"
                "请调用方通过 StockDataReader(adjust_type='front') 加载日线数据后传入。"
            )
    else:
        dist = daily_chip_distribution(arr, method=method)

    close_price = float(arr[-1, 0])  # 最新 bar 的 close
    cf = cyq.ChipFactor(close_price, dist)

    return {
        "cyqk_c": cf.get_cyqk_c(),
        "asr": cf.get_asr(),
        "ckdw": cf.get_ckdw(),
        "prp": cf.get_prp(),
    }


# ---------------------------------------------------------------------------
# Phase 2: 换手率半衰期筹码分布因子（ARC/VRC/SRC/KRC）
# ---------------------------------------------------------------------------
def turnover_chip_factors(
    turnover_rate: np.ndarray,
    close: np.ndarray,
    window: int = 60,
) -> dict:
    """
    计算换手率衰减筹码分布因子（ARC/VRC/SRC/KRC）。

    基于广发证券多因子 alpha 系列报告 #27 的换手率半衰期模型。
    不需要 OHLC 分布假设，仅需换手率和收盘价。

    Args:
        turnover_rate: 换手率序列（比例，0-1），长度 ≥ window
        close: 收盘价序列，长度 ≥ window
        window: 滚动窗口（默认 60）

    Returns:
        dict with keys: arc, vrc, src, krc
    """
    if len(turnover_rate) < window or len(close) < window:
        return {"arc": np.nan, "vrc": np.nan, "src": np.nan, "krc": np.nan}

    # 截取最后 window 个值
    tr = np.asarray(turnover_rate[-window:], dtype=np.float64).flatten()
    cl = np.asarray(close[-window:], dtype=np.float64).flatten()

    chips = tco.calc_distribution_of_chips(tr, cl, window)
    return {
        "arc": float(chips[0]),
        "vrc": float(chips[1]),
        "src": float(chips[2]),
        "krc": float(chips[3]),
    }


# ---------------------------------------------------------------------------
# 跨日衍生 chip 因子
# ---------------------------------------------------------------------------
def derived_chip_factors(
    cyqk_today: float,
    cyqk_yesterday: float,
    turnover_today: float,
) -> dict:
    """
    跨日衍生 chip 因子。

    Args:
        cyqk_today: 当日获利筹码比例
        cyqk_yesterday: 上一日获利筹码比例
        turnover_today: 当日换手率（比例，0-1）

    Returns:
        dict with keys: profit_chip_diff, turnover_ratio, turnover_resistance
    """
    profit_chip_diff = cyqk_today - cyqk_yesterday
    if turnover_today > 0:
        turnover_resistance = profit_chip_diff / turnover_today
    else:
        turnover_resistance = 0.0

    return {
        "profit_chip_diff": round(profit_chip_diff, 6),
        "turnover_ratio": round(turnover_today, 6),
        "turnover_resistance": round(turnover_resistance, 4),
    }


def _fmt_cyqk(val: float):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return ""
    return round(float(val), 4)


def compute_crossday_turnover_resistance(
    df: pd.DataFrame,
    stock_code: str,
    window: int = 1000,
    method: str = "triang",
) -> dict:
    """
    截面日 T 的 canonical 换手阻力。

    今日窗口：最近 window 个交易日（含 T），默认 1000≈4 年；
    昨日窗口：再往前 window 日（含 T-1）。
    分母为今日窗口 adapt_columns 末行 turnover_rate（arr_t[-1, 4]），按 as_of_date 查股本。
    """
    if df is None or df.empty:
        raise ValueError("empty dataframe")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("df index must be DatetimeIndex")

    idx = cast(pd.DatetimeIndex, df.index)
    df = df.sort_index()
    unique_dates = idx.normalize().unique()  # pyright: ignore[reportAttributeAccessIssue]
    if len(unique_dates) < window:
        raise ValueError(f"need {window} trading days, got {len(unique_dates)}")

    as_of_t = cast(pd.Timestamp, pd.Timestamp(unique_dates[-1])).normalize()  # pyright: ignore[reportAttributeAccessIssue]
    mask_t = idx.normalize().isin(unique_dates[-window:])  # pyright: ignore[reportAttributeAccessIssue]
    df_t = df.loc[mask_t]

    arr_t = adapt_columns(df_t, stock_code=stock_code, as_of_date=as_of_t)
    dist_t = daily_chip_distribution(arr_t, method=method)
    cf_t = cyq.ChipFactor(float(arr_t[-1, 0]), dist_t)
    cyqk_today = cf_t.get_cyqk_c()
    turnover_today = float(arr_t[-1, 4])

    out = {
        "cyqk_c": _fmt_cyqk(cyqk_today),
        "cyqk_c_yesterday": "",
        "profit_chip_diff": "",
        "turnover_ratio": round(turnover_today, 6),
        "turnover_resistance": "",
        "window": int(window),
    }

    if len(unique_dates) < window + 1:
        return out

    prev_dates = unique_dates[-(window + 1):-1]
    as_of_y = cast(pd.Timestamp, pd.Timestamp(prev_dates[-1])).normalize()  # pyright: ignore[reportAttributeAccessIssue]
    mask_y = idx.normalize().isin(prev_dates)  # pyright: ignore[reportAttributeAccessIssue]
    df_y = df.loc[mask_y]
    arr_y = adapt_columns(df_y, stock_code=stock_code, as_of_date=as_of_y)
    dist_y = daily_chip_distribution(arr_y, method=method)
    cf_y = cyq.ChipFactor(float(arr_y[-1, 0]), dist_y)

    derived = derived_chip_factors(
        cyqk_today, cf_y.get_cyqk_c(), turnover_today,
    )
    out["cyqk_c_yesterday"] = _fmt_cyqk(cf_y.get_cyqk_c())
    out["profit_chip_diff"] = derived["profit_chip_diff"]
    out["turnover_ratio"] = derived["turnover_ratio"]
    out["turnover_resistance"] = derived["turnover_resistance"]
    return out


# ---------------------------------------------------------------------------
# 等权重筹码分布（市面常见指标对比实现）
# ---------------------------------------------------------------------------
def compute_equal_weight_cyqk(
    df: pd.DataFrame,
    stock_code: str,
    window: int = 1000,
    method: str = "triang",
) -> dict:
    """
    等权重筹码分布（无换手率衰减）—— 与市面常见筹码分布 APP 对齐的对比实现。

    与 canonical 路径 ``compute_crossday_turnover_resistance`` 的核心差异：
    1. **无衰减**：历史日筹码等权重累加，不使用 ``calc_cumpdf`` 的换手率衰减模型；
    2. **窗口**：默认 120 个交易日（市面常见指标通常用 100~130 日）；
    3. **无 turnover 估算**：本函数仅输出筹码分布因子，不计算换手率及阻力。

    Args:
        df: 日线 DataFrame（含 close/high/low/volume）
        stock_code: 标的代码
        window: 筹码分布窗口（交易日），默认 120
        method: PDF 方法，"triang" 或 "uniform"

    Returns:
        dict: cyqk_c, asr, ckdw, prp, cost_p05...cost_p95, close, window
    """
    if df is None or df.empty:
        raise ValueError("empty dataframe")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("df index must be DatetimeIndex")

    idx = cast(pd.DatetimeIndex, df.index)
    df = df.sort_index()
    unique_dates = idx.normalize().unique()  # pyright: ignore[reportAttributeAccessIssue]
    if len(unique_dates) < window:
        raise ValueError(f"need {window} trading days, got {len(unique_dates)}")

    as_of = cast(pd.Timestamp, pd.Timestamp(unique_dates[-1])).normalize()  # pyright: ignore[reportAttributeAccessIssue]
    win_dates = unique_dates[-window:]
    mask = idx.normalize().isin(win_dates)  # pyright: ignore[reportAttributeAccessIssue]
    df_w = df.loc[mask]

    arr = adapt_columns(df_w, stock_code=stock_code, as_of_date=as_of)
    close = float(arr[-1, 0])

    # 等权重累加：不用 calc_cumpdf，直接 sum(curpdf)
    max_p = float(np.nanmax(arr[:, 1]))
    min_p = float(np.nanmin(arr[:, 2]))
    step = 0.01
    if max_p <= min_p:
        return {
            "cyqk_c": float("nan"), "asr": float("nan"), "ckdw": float("nan"), "prp": float("nan"),
            "cost_p05": float("nan"), "cost_p10": float("nan"), "cost_p50": float("nan"),
            "cost_p90": float("nan"), "cost_p95": float("nan"),
            "close": close, "window": window, "method": method,
        }

    xs = make_price_grid(min_p, max_p, step)
    curpdfs = np.zeros((len(arr), len(xs)))
    for i in range(len(arr)):
        row = arr[i]
        pdf = calc_curpdf(row[0], row[1], row[2], row[3], min_p, max_p, step, method)
        curpdfs[i] = pdf

    cum_vol = np.sum(curpdfs, axis=0)
    dist = pd.Series(cum_vol, index=xs, name="cumpdf")

    cf = cyq.ChipFactor(close, dist)
    return {
        "cyqk_c": _fmt_cyqk(cf.get_cyqk_c()),
        "asr": _fmt_cyqk(cf.get_asr()),
        "ckdw": _fmt_cyqk(cf.get_ckdw()),
        "prp": _fmt_cyqk(cf.get_prp()),
        "cost_p05": round(float(cf.get_cost(0.05)), 2),
        "cost_p10": round(float(cf.get_cost(0.10)), 2),
        "cost_p50": round(float(cf.get_cost(0.50)), 2),
        "cost_p90": round(float(cf.get_cost(0.90)), 2),
        "cost_p95": round(float(cf.get_cost(0.95)), 2),
        "close": close,
        "window": window,
        "method": method,
    }
