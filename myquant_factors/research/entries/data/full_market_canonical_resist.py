from typing import Any, cast


from myquant_factors._runtime import research_root, resolve_source_parquet
# -*- coding: utf-8 -*-
"""
全市场 canonical 换手阻力计算（1000 日窗口 + 换手率衰减，step=0.01）。

三种算法模式（--method）：
  - batch（默认）：numba 批量三角分布，curpdf 只算 1 次，最快
  - original：原始 4 次 _canonical_cyqk，最慢但作为对照基准

输出双口径换手阻力：
  - turnover_resistance：流通股本 (circulating_capital) 口径
  - turnover_resistance_free：自由流通股本 (freeFloatCapital) 口径
"""

import argparse
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
from pathlib import Path

REPO = str(research_root())
sys.path.append(REPO)  # append (not insert(0)) keeps stdlib precedence; gate-clean

import numpy as np
import pandas as pd
from numba import jit

import myquant_factors._runtime as reader
from myquant_factors.chip.core import adapt_columns
from myquant_factors import cyq
from myquant_factors.distribution_of_chips import make_price_grid


# ===========================================================================
# Method A: numba batch triang PDF (fastest)
# ===========================================================================

@jit(nopython=True)
def _batch_triang_curpdf(
    close: np.ndarray, high: np.ndarray, low: np.ndarray,
    vol: np.ndarray, x: np.ndarray,
) -> np.ndarray:
    """Compute triang PDF for all days in a single numba call.
    Eliminates 1000x np.arange + Python function call overhead.
    Returns: curpdfs, shape (n_days, len(x))"""
    n_days = len(close)
    n_bins = len(x)
    pdfs = np.zeros((n_days, n_bins), dtype=np.float64)
    step = x[1] - x[0] if n_bins > 1 else 0.01

    for d in range(n_days):
        h, l, c_val, v = high[d], low[d], close[d], vol[d]

        if h == l:  # 涨跌停日
            idx = int(round((c_val - x[0]) / step))
            if 0 <= idx < n_bins:
                pdfs[d, idx] = v
            continue

        scale = h - l
        c_param = (c_val - l) / scale
        loc = l
        peak = loc + scale * c_param
        upper = loc + scale
        sq_scale = scale * scale

        if c_param <= 0.0:
            for i in range(n_bins):
                xi = x[i]
                if loc <= xi <= upper:
                    pdfs[d, i] = 2.0 * (upper - xi) / sq_scale
        elif c_param >= 1.0:
            for i in range(n_bins):
                xi = x[i]
                if loc <= xi <= upper:
                    pdfs[d, i] = 2.0 * (xi - loc) / sq_scale
        else:
            for i in range(n_bins):
                xi = x[i]
                if loc <= xi <= peak:
                    pdfs[d, i] = 2.0 * (xi - loc) / (c_param * sq_scale)
                elif peak < xi <= upper:
                    pdfs[d, i] = 2.0 * (upper - xi) / (sq_scale * (1.0 - c_param))

        # Normalize
        total = 0.0
        for i in range(n_bins):
            total += pdfs[d, i]
        if total > 0.0:
            for i in range(n_bins):
                pdfs[d, i] = pdfs[d, i] / total * v

    return pdfs


@jit(nopython=True)
def _batch_cumpdf_4way(
    curpdf_t: np.ndarray, curpdf_prev: np.ndarray,
    t_circ_t: np.ndarray, t_circ_p: np.ndarray,
    t_free_t: np.ndarray, t_free_p: np.ndarray,
) -> tuple:
    """Compute 4 cumpdf results in a single numba call.
    Eliminates 3 Python↔numba transitions vs 4 separate calc_cumpdf calls."""
    # T window circ
    n_days = len(t_circ_t)
    n_bins = curpdf_t.shape[1]
    decay = t_circ_t.copy()
    diff = 1.0 - decay
    mul = (curpdf_t.T * decay).T
    c1 = np.empty(n_bins, dtype=np.float64)
    for i in range(n_days):
        c1 = c1 * diff[i] + mul[i] if i else curpdf_t[i] * decay[i]

    # T-1 window circ
    decay = t_circ_p.copy()
    diff = 1.0 - decay
    mul = (curpdf_prev.T * decay).T
    c2 = np.empty(n_bins, dtype=np.float64)
    for i in range(n_days):
        c2 = c2 * diff[i] + mul[i] if i else curpdf_prev[i] * decay[i]

    # T window free
    decay = t_free_t.copy()
    diff = 1.0 - decay
    mul = (curpdf_t.T * decay).T
    c3 = np.empty(n_bins, dtype=np.float64)
    for i in range(n_days):
        c3 = c3 * diff[i] + mul[i] if i else curpdf_t[i] * decay[i]

    # T-1 window free
    decay = t_free_p.copy()
    diff = 1.0 - decay
    mul = (curpdf_prev.T * decay).T
    c4 = np.empty(n_bins, dtype=np.float64)
    for i in range(n_days):
        c4 = c4 * diff[i] + mul[i] if i else curpdf_prev[i] * decay[i]

    return c1, c2, c3, c4


# ===========================================================================
# Method B: original _canonical_cyqk (reference, 4 independent calls)
# ===========================================================================

def _canonical_cyqk(
    df: pd.DataFrame, stock_code: str, window: int,
    step: float = 0.01, use_free_float: bool = False,
    capital_override: float | None = None,
) -> float:
    """Original canonical (turnover-weighted decay) cyqk — reference implementation.
    If capital_override is provided, skip adapt_columns capital lookup (O(1) vs pandas filter)."""
    if df is None or df.empty:
        return float("nan")

    df = df.sort_index()
    unique_dates = df.index.normalize().unique()
    if len(unique_dates) < 20:
        return float("nan")

    as_of = pd.Timestamp(unique_dates[-1]).normalize()
    win_dates = unique_dates[-window:]
    mask = df.index.normalize().isin(win_dates)
    df_w = df.loc[mask]

    try:
        if capital_override is not None and capital_override > 0:
            # Fast path: compute turnover_rate directly, skip pandas filter
            arr = df_w.rename(columns={"volume": "vol"})[["close", "high", "low", "vol"]].values
            vol_arr = arr[:, 3].astype(np.float64)
            turnover = vol_arr * 100.0 / capital_override
            arr = np.column_stack([arr, turnover])
        else:
            arr = adapt_columns(df_w, stock_code=stock_code, as_of_date=as_of,
                                use_free_float=use_free_float)
    except Exception:
        return float("nan")

    try:
        dist = cyq.calc_dist_chips(arr, method="triang", step=step)
    except Exception:
        return float("nan")

    cf = cyq.ChipFactor(float(arr[-1, 0]), dist)
    return cf.get_cyqk_c()


# ===========================================================================
# Shared computation: Steps 2-7 (identical for batch and original)
# ===========================================================================

def _compute_derived_and_output(
    code, target, df_t, arr_raw, xs, curpdfs,
    turnover_circ_t_arr, turnover_circ_prev_arr,
    turnover_free_t_arr, turnover_free_prev_arr,
    circ_cap_t, free_cap_t,
    free_missing: bool = False,
):
    """Steps 4-7: cumpdf → cyqk → derived → bollinger → output dict.
    Shared between batch and original methods."""
    n_days = len(arr_raw)
    curpdf_t = curpdfs[1:, :]
    curpdf_prev = curpdfs[:-1, :]

    # Step 4: 4 × cumpdf in a single numba call (was 4 separate calls)
    try:
        cumpdf_circ_t, cumpdf_circ_prev, cumpdf_free_t, cumpdf_free_prev = \
            _batch_cumpdf_4way(curpdf_t, curpdf_prev,
                               turnover_circ_t_arr[1:], turnover_circ_prev_arr[:-1],
                               turnover_free_t_arr[1:], turnover_free_prev_arr[:-1])
    except Exception:
        return None

    # Step 5: Extract cyqk
    close_t = float(arr_raw[-1, 0])
    try:
        cyqk_circ_t = cyq.ChipFactor(close_t, pd.Series(cumpdf_circ_t, index=xs, name="cumpdf")).get_cyqk_c()
        cyqk_circ_prev = cyq.ChipFactor(float(arr_raw[-2, 0]), pd.Series(cumpdf_circ_prev, index=xs, name="cumpdf")).get_cyqk_c()
        cyqk_free_t = cyq.ChipFactor(close_t, pd.Series(cumpdf_free_t, index=xs, name="cumpdf")).get_cyqk_c()
        cyqk_free_prev = cyq.ChipFactor(float(arr_raw[-2, 0]), pd.Series(cumpdf_free_prev, index=xs, name="cumpdf")).get_cyqk_c()
    except Exception:
        return None

    if any(np.isnan(x) for x in [cyqk_circ_t, cyqk_circ_prev, cyqk_free_t, cyqk_free_prev]):
        return None

    # Step 6: Derived values
    profit_chip_diff_circ = cyqk_circ_t - cyqk_circ_prev
    turnover_circ_t = float(turnover_circ_t_arr[-1])
    turnover_resistance_circ = profit_chip_diff_circ / turnover_circ_t if turnover_circ_t > 0 else 0.0

    # Warn-zero fallback: when free float capital is missing, align with Rust:
    # use circ cumpdf for free (passed in via turnover_free_*_arr = circ), but
    # report turnover_free = 0 and turnover_resistance_free = 0.
    if free_missing:
        profit_chip_diff_free = 0.0
        turnover_free_t = 0.0
        turnover_resistance_free = 0.0
    else:
        profit_chip_diff_free = cyqk_free_t - cyqk_free_prev
        turnover_free_t = float(turnover_free_t_arr[-1])
        turnover_resistance_free = profit_chip_diff_free / turnover_free_t if turnover_free_t > 0 else 0.0

    # Step 7: Bollinger Bands
    close_series = df_t["close"]
    if len(close_series) >= 20:
        bb_mid = float(close_series.rolling(20).mean().iloc[-1])
        bb_std = float(close_series.rolling(20).std().iloc[-1])
    else:
        bb_mid = float(close_series.mean())
        bb_std = float(close_series.std())
    bb_upper = bb_mid + 2.0 * bb_std
    bb_lower = bb_mid - 2.0 * bb_std
    bb_pos = (close_t - bb_lower) / (bb_upper - bb_lower) if bb_upper > bb_lower else 0.5
    bb_w = (bb_upper - bb_lower) / bb_mid if bb_mid > 0 else 0.0

    return {
        "close": round(close_t, 2),
        "cyqk_T": round(cyqk_circ_t, 4),
        "cyqk_T_1": round(cyqk_circ_prev, 4),
        "profit_chip_diff": round(profit_chip_diff_circ, 6),
        "turnover": round(turnover_circ_t, 6),
        "turnover_resistance": round(turnover_resistance_circ, 4),
        "turnover_free": round(turnover_free_t, 6),
        "turnover_resistance_free": round(turnover_resistance_free, 4),
        "circulating_capital": circ_cap_t,
        "freeFloatCapital": free_cap_t,
        "bb_upper": round(bb_upper, 2),
        "bb_middle": round(bb_mid, 2),
        "bb_lower": round(bb_lower, 2),
        "bb_position": round(bb_pos, 4),
        "bb_width": round(bb_w, 4),
    }


# ===========================================================================
# Single-stock entry points (called by ProcessPoolExecutor)
# ===========================================================================

def _process_stock_batch(code: str, df: pd.DataFrame, target: pd.Timestamp, window: int, step: float,
                          cap_t=None, cap_tp=None, free_t=None, free_tp=None,
                          target_date_policy: str = "strict"):
    """Method 'batch': numba batch triang → 1x curpdf → 4x cumpdf. Fastest.
    df and capital maps are pre-loaded by caller."""
    if df is None or df.empty:
        return None

    df = df.sort_index()

    df_t = df[df.index.normalize() <= target]
    unique_dates = df_t.index.normalize().unique()
    if len(unique_dates) == 0:
        return None

    # Target date policy: strict requires target date exists
    if target_date_policy == "strict" and unique_dates[-1] != target:
        return None

    # Minimum bars to compute stable cyqk (align with Rust)
    if len(unique_dates) < 20:
        return None

    # Dynamic window: use all available dates if not enough for window+1
    # Need at least window+1 unique dates to compute T and T-1 windows of length window
    # If fewer dates available, use all of them (T and T-1 will be shorter but consistent)
    extended_dates = unique_dates[-(window + 1):]
    mask_ext = df_t.index.normalize().isin(extended_dates)
    df_w = df_t.loc[mask_ext]
    n_days = len(df_w)
    if n_days < 2:
        return None

    # Step 1: curpdf via numba batch
    arr_raw = (df_w.rename(columns={"volume": "vol"})
               [["close", "high", "low", "vol"]].values.astype(np.float64))
    max_p = float(np.nanmax(arr_raw[:, 1]))
    min_p = float(np.nanmin(arr_raw[:, 2]))
    if max_p <= min_p:
        return None
    xs = make_price_grid(min_p, max_p, step)
    curpdfs = _batch_triang_curpdf(arr_raw[:, 0], arr_raw[:, 1], arr_raw[:, 2], arr_raw[:, 3], xs)

    # Steps 2-7
    return _steps_2_7(code, target, df_t, arr_raw, xs, curpdfs,
                      cap_t, cap_tp, free_t, free_tp)


def _process_stock_original(code: str, df: pd.DataFrame, target: pd.Timestamp, window: int, step: float,
                             cap_t=None, cap_tp=None, free_t=None, free_tp=None,
                             target_date_policy: str = "strict"):
    """Method 'original': 4 independent _canonical_cyqk calls. Reference.
    df and capital maps are pre-loaded by caller for speed (algorithm unchanged)."""
    target_prev = target - pd.Timedelta(days=1)

    df = df.sort_index()

    df_t = df[df.index.normalize() <= target]
    df_prev = df[df.index.normalize() <= target_prev]
    if df_t.empty or df_prev.empty:
        return None

    # Target date policy: strict requires target date exists
    if target_date_policy == "strict":
        last_date = df_t.index.normalize()[-1]
        if last_date != target:
            return None

    # Capital values from pre-built maps (save 22000 pandas filter calls)
    circ_cap_t_val = cap_t.get(code, 0) if cap_t else 0
    circ_cap_prev_val = cap_tp.get(code, 0) if cap_tp else 0
    free_cap_t_val = free_t.get(code, 0) if free_t else 0
    free_cap_prev_val = free_tp.get(code, 0) if free_tp else 0

    # 4 independent cyqk calls — algorithm unchanged, only capital source changed
    cyqk_circ_t = _canonical_cyqk(cast(Any, df_t), code, window=window, step=step, use_free_float=False,
                                   capital_override=circ_cap_t_val)
    cyqk_circ_prev = _canonical_cyqk(cast(Any, df_prev), code, window=window, step=step, use_free_float=False,
                                      capital_override=circ_cap_prev_val)

    # Warn-zero fallback: when free float capital is missing, align with Rust
    # by reusing circ cyqk for free and reporting free turnover/resistance as 0.
    free_missing = free_cap_t_val <= 0 or free_cap_prev_val <= 0
    if free_missing:
        cyqk_free_t = cyqk_circ_t
        cyqk_free_prev = cyqk_circ_prev
    else:
        cyqk_free_t = _canonical_cyqk(cast(Any, df_t), code, window=window, step=step, use_free_float=True,
                                       capital_override=free_cap_t_val)
        cyqk_free_prev = _canonical_cyqk(cast(Any, df_prev), code, window=window, step=step, use_free_float=True,
                                          capital_override=free_cap_prev_val)

    if any(np.isnan(x) for x in [cyqk_circ_t, cyqk_circ_prev, cyqk_free_t, cyqk_free_prev]):
        return None

    # Derived values — use pre-loaded capital (O(1) dict lookup)
    vol_t = float(df_t["volume"].iloc[-1])
    turnover_circ_t = vol_t * 100.0 / circ_cap_t_val if circ_cap_t_val > 0 else float("nan")

    profit_chip_diff_circ = cyqk_circ_t - cyqk_circ_prev
    turnover_resistance_circ = profit_chip_diff_circ / turnover_circ_t if turnover_circ_t > 0 else 0.0

    if free_missing:
        profit_chip_diff_free = 0.0
        turnover_free_t = 0.0
        turnover_resistance_free = 0.0
    else:
        profit_chip_diff_free = cyqk_free_t - cyqk_free_prev
        turnover_free_t = vol_t * 100.0 / free_cap_t_val
        turnover_resistance_free = profit_chip_diff_free / turnover_free_t if turnover_free_t > 0 else 0.0

    close_t = float(df_t["close"].iloc[-1])

    # Bollinger Bands
    close_series = df_t["close"]
    if len(close_series) >= 20:
        bb_mid = float(close_series.rolling(20).mean().iloc[-1])
        bb_std = float(close_series.rolling(20).std().iloc[-1])
    else:
        bb_mid = float(close_series.mean())
        bb_std = float(close_series.std())
    bb_upper = bb_mid + 2.0 * bb_std
    bb_lower = bb_mid - 2.0 * bb_std
    bb_pos = (close_t - bb_lower) / (bb_upper - bb_lower) if bb_upper > bb_lower else 0.5
    bb_w = (bb_upper - bb_lower) / bb_mid if bb_mid > 0 else 0.0

    return {
        "close": round(close_t, 2),
        "cyqk_T": round(cyqk_circ_t, 4),
        "cyqk_T_1": round(cyqk_circ_prev, 4),
        "profit_chip_diff": round(profit_chip_diff_circ, 6),
        "turnover": round(turnover_circ_t, 6),
        "turnover_resistance": round(turnover_resistance_circ, 4),
        "turnover_free": round(turnover_free_t, 6),
        "turnover_resistance_free": round(turnover_resistance_free, 4),
        "circulating_capital": circ_cap_t_val,
        "freeFloatCapital": free_cap_t_val,
        "bb_upper": round(bb_upper, 2),
        "bb_middle": round(bb_mid, 2),
        "bb_lower": round(bb_lower, 2),
        "bb_position": round(bb_pos, 4),
        "bb_width": round(bb_w, 4),
    }


def _steps_2_7(code, target, df_t, arr_raw, xs, curpdfs,
               cap_t_map=None, cap_tp_map=None, free_t_map=None, free_tp_map=None):
    """Steps 2-7: capital → turnover → cumpdf → cyqk → output.
    Capital values from pre-built dicts (O(1) lookup vs pandas filter)."""
    circ_cap_t = cap_t_map.get(code, 0) if cap_t_map else 0
    circ_cap_prev = cap_tp_map.get(code, 0) if cap_tp_map else 0
    free_cap_t = free_t_map.get(code, 0) if free_t_map else 0
    free_cap_prev = free_tp_map.get(code, 0) if free_tp_map else 0
    if circ_cap_t <= 0 or circ_cap_prev <= 0:
        return None

    free_missing = free_cap_t <= 0 or free_cap_prev <= 0

    vol_arr = arr_raw[:, 3]
    turnover_circ_t_arr = vol_arr * 100.0 / circ_cap_t
    turnover_circ_prev_arr = vol_arr * 100.0 / circ_cap_prev
    if free_missing:
        # Align with Rust WarnZero: reuse circ decay for free cumpdf,
        # but output turnover_free/resistance_free as 0.
        turnover_free_t_arr = turnover_circ_t_arr.copy()
        turnover_free_prev_arr = turnover_circ_prev_arr.copy()
        free_cap_t = 0
    else:
        turnover_free_t_arr = vol_arr * 100.0 / free_cap_t
        turnover_free_prev_arr = vol_arr * 100.0 / free_cap_prev

    return _compute_derived_and_output(
        code, target, df_t, arr_raw, xs, curpdfs,
        turnover_circ_t_arr, turnover_circ_prev_arr,
        turnover_free_t_arr, turnover_free_prev_arr,
        circ_cap_t, free_cap_t,
        free_missing=free_missing,
    )


# ===========================================================================
# Main run loop
# ===========================================================================

def run(date_str, output, window=1000, step=0.01,
        batch_start=0, batch_end=None, sort_by="free",
        workers=None, method="batch",
        free_float_policy="warn-zero",
        target_date_policy="strict"):
    target = pd.Timestamp(date_str)

    fs_path = resolve_source_parquet('float_shares.parquet')
    if not fs_path.exists():
        raise FileNotFoundError(f"{fs_path} not found")

    fs_df = pd.read_parquet(fs_path)
    name_map = (dict(zip(fs_df["stock_code"], fs_df["name"]))
                if "name" in fs_df.columns else {})
    codes = fs_df["stock_code"].dropna().unique().tolist()
    batch_end = batch_end or len(codes)
    codes = codes[batch_start:batch_end]

    n_workers = workers or max(1, cpu_count() - 1)
    process_fn = _process_stock_batch if method == "batch" else _process_stock_original
    fn_name = "batch (numba)" if method == "batch" else "original (4×cyqk)"
    print(f"Stocks: {len(codes)}  date: {date_str}  window: {window}"
          f"  step: {step}  method: {fn_name}  workers: {n_workers}")

    # ---- Phase 0: Build capital maps (replace 22000 pandas filter calls) ----
    import duckdb
    t_cap = time.perf_counter()
    target_prev = target - pd.Timedelta(days=1)
    target_ts = target.strftime('%Y-%m-%d')
    target_prev_ts = target_prev.strftime('%Y-%m-%d')

    con = duckdb.connect()
    cap_path = str(resolve_source_parquet('free_float_shares.parquet').resolve())
    cap_df = con.execute(f"""
        SELECT * FROM (
          SELECT stock_code, 'T' as which, freeFloatCapital, circulating_capital,
            ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY m_timetag DESC) AS rn
          FROM read_parquet('{cap_path}')
          WHERE m_timetag <= '{target_ts}'
        ) WHERE rn = 1
        UNION ALL
        SELECT * FROM (
          SELECT stock_code, 'T_prev' as which, freeFloatCapital, circulating_capital,
            ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY m_timetag DESC) AS rn
          FROM read_parquet('{cap_path}')
          WHERE m_timetag <= '{target_prev_ts}'
        ) WHERE rn = 1
    """).df()
    con.close()

    cap_t = {}; cap_tp = {}; free_t = {}; free_tp = {}
    for _, row in cap_df.iterrows():
        circ = row['circulating_capital']
        free = row['freeFloatCapital']
        circ_val = float(circ) if circ is not None and float(circ) > 0 else 0.0
        free_val = float(free) if free is not None and float(free) > 0 else 0.0
        if row['which'] == 'T':
            cap_t[row['stock_code']] = circ_val
            free_t[row['stock_code']] = free_val
        else:
            cap_tp[row['stock_code']] = circ_val
            free_tp[row['stock_code']] = free_val

    # Fallback: float_shares.parquet for missing circulating_capital
    fs_df = pd.read_parquet('stock_data/float_shares.parquet')
    fs_map = dict(zip(fs_df['stock_code'], fs_df['FloatVolume']))
    for code in codes:
        if cap_t.get(code, 0) <= 0:
            cap_t[code] = fs_map.get(code, 0)
        if cap_tp.get(code, 0) <= 0:
            cap_tp[code] = fs_map.get(code, 0)
    # Apply free_float_policy: track missing stocks for skip/fail (v1.1, aligns Rust)
    missing_free_float: set[str] = set()
    for code in codes:
        free_t_val = free_t.get(code, 0)
        if free_t_val <= 0:
            if free_float_policy == "fail":
                raise RuntimeError(
                    f"free_float_policy=fail: stock {code} has no freeFloatCapital"
                )
            elif free_float_policy == "skip":
                missing_free_float.add(code)
    if missing_free_float:
        print(
            f"free_float_policy=skip: {len(missing_free_float)} stocks skipped"
            f" (missing freeFloatCapital)"
        )
    print(f"Capital maps built: {len(cap_t)} stocks, {time.perf_counter()-t_cap:.1f}s")

    # ---- Phase 1: Batch load stock data via StockDataReader.scan_stocks() ----
    t_load = time.perf_counter()
    start_date = (target - pd.Timedelta(days=window * 2)).strftime('%Y-%m-%d')
    end_date = target.strftime('%Y-%m-%d')
    batch_reader = reader.StockDataReader(mode='duckdb_persistent')
    df_all = batch_reader.scan_stocks(start_time=start_date, end_time=end_date,
                                       period='1d', adjust_type='front',
                                       columns=['symbol', 'time', 'close', 'high', 'low', 'volume'])
    if df_all is None:
        raise RuntimeError("scan_stocks returned no data")
    df_all.rename(columns={'symbol': 'stock_code'}, inplace=True)
    df_all['stock_code'] = df_all['stock_code'].str.replace('_', '.', regex=False)
    df_all['datetime'] = pd.to_datetime(df_all['time'], unit='ms')
    df_all.set_index('datetime', inplace=True)
    df_all = df_all.sort_index()
    stock_data = {code: group.drop(columns=['time'])
                  for code, group in df_all.groupby('stock_code')}
    print(f"Batch loaded: {len(stock_data)} stocks, {len(df_all):,} rows, {time.perf_counter()-t_load:.1f}s")

    t0 = time.perf_counter()
    results, skipped = [], 0
    n_total = len(codes)

    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        futures = {}
        for code in codes:
            if free_float_policy == "skip" and code in missing_free_float:
                skipped += 1
                continue
            df = stock_data.get(code)
            if df is None:
                skipped += 1
                continue
            futures[executor.submit(process_fn, code, df, cast(Any, target), window, step,
                                     cap_t, cap_tp, free_t, free_tp,
                                     target_date_policy)] = code
        for i, future in enumerate(as_completed(futures)):
            code = futures[future]
            try:
                result = future.result()
                if result is not None:
                    result["stock_name"] = name_map.get(code, "")
                    result["date"] = date_str
                    result["stock_code"] = code
                    results.append(result)
                else:
                    skipped += 1
            except Exception:
                skipped += 1
            if (i + 1) % 500 == 0:
                print(f"  {i+1}/{n_total} done, valid={len(results)}, skipped={skipped}")

    elapsed = time.perf_counter() - t0
    if not results:
        print("No valid results")
        return

    out_df = pd.DataFrame(results)
    sort_col = "turnover_resistance_free" if sort_by == "free" else "turnover_resistance"
    out_df["abs_resist"] = out_df[sort_col].abs()
    out_df = out_df.sort_values("abs_resist", ascending=False)
    out_df = out_df.drop(columns=["abs_resist"])
    col_order = [
        "stock_code", "stock_name", "date", "close",
        "cyqk_T", "cyqk_T_1", "profit_chip_diff", "turnover",
        "turnover_resistance", "turnover_free", "turnover_resistance_free",
        "circulating_capital", "freeFloatCapital",
        "bb_upper", "bb_middle", "bb_lower", "bb_position", "bb_width",
    ]
    out_df = out_df[col_order]

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nOutput: {out_path}  rows={len(out_df)}  skipped={skipped}")
    print(f"Elapsed: {elapsed:.1f}s ({elapsed/60:.1f}m)")
    print(f"\nTop 20 by |{sort_col}|:")
    print(out_df.head(20).to_string(index=False))


# ===========================================================================
# CLI
# ===========================================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="20260522", help="截面日 YYYYMMDD")
    parser.add_argument("--window", type=int, default=1000)
    parser.add_argument("--step", type=float, default=0.01)
    parser.add_argument("--output", default=None)
    parser.add_argument("--sort-by", choices=["free", "circulating"], default="free")
    parser.add_argument("--workers", type=int, default=None,
                        help="并行进程数（默认 CPU-1）")
    parser.add_argument("--method", choices=["batch", "original"], default="batch",
                        help="batch=numba批量三角分布(快), original=4次独立cyqk(慢/对照)")
    parser.add_argument("--batch-start", type=int, default=0)
    parser.add_argument("--batch-end", type=int, default=None)
    parser.add_argument("--free-float-policy", choices=["warn-zero", "skip", "fail"],
                        default="warn-zero",
                        help="warn-zero=缺自由流通股本时填0继续; skip=跳过该股票; fail=报错退出")
    parser.add_argument("--target-date-policy", choices=["strict", "last-available"],
                        default="strict",
                        help="strict=目标日期不存在则跳过; last-available=使用最新可用日期")
    args = parser.parse_args()

    if args.output is None:
        suffix = "batch" if args.method == "batch" else "orig"
        args.output = f"backtest_output/canonical_resist_{suffix}_{args.date}.csv"

    warnings.filterwarnings("ignore", category=RuntimeWarning,
                            message="invalid value encountered in divide")
    run(args.date, args.output, args.window, args.step,
        args.batch_start, args.batch_end, args.sort_by,
        args.workers, args.method, args.free_float_policy,
        args.target_date_policy)


if __name__ == "__main__":
    raise SystemExit(main())
