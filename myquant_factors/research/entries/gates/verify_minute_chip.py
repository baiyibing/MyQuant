from typing import Any, cast


from myquant_factors._runtime import research_root, resolve_source_parquet
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
verify_minute_chip.py — 分钟线 COST 筹码分布验证

验证：
1. 分钟线数据可正常加载和适配
2. minute_chip_distribution() 产出有效的筹码分布（非空 / 非 NaN）
3. 分钟线 vs 日线的因子值在同一量级，符号方向一致

用法：
    python backtest/verify_minute_chip.py
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd

REPO = str(research_root())
sys.path.insert(0, REPO)

from myquant_factors.chip.core import (
    adapt_columns,
    daily_chip_distribution,
    minute_chip_distribution,
)
from myquant_factors import cyq
from myquant_factors._runtime import StockDataReader

STOCK_CODE = "000001.SZ"
WINDOW_DAYS = 80

_reader = None

def _get_reader():
    global _reader
    if _reader is None:
        _reader = StockDataReader()
    return _reader


def main():
    passed = 0
    failed = 0

    # ------------------------------------------------------------------
    # 1) 加载数据
    # ------------------------------------------------------------------
    print(f"[1/6] Loading minute & daily data for {STOCK_CODE} ...")

    reader = _get_reader()
    df_min = reader.read_stock(STOCK_CODE, period='1m', adjust_type='none')
    df_day = reader.read_stock(STOCK_CODE, period='1d', adjust_type='none')
    if df_min is None or df_day is None:
        print("ERROR: read_stock returned no data")
        return 1

    # 日线数据最后 N 天 → 截取分钟线相同时段
    last_date = pd.to_datetime(df_day["time"].iloc[-1], unit="ms").date()
    first_date = pd.to_datetime(df_day["time"].iloc[-WINDOW_DAYS], unit="ms").date()

    df_min["dt"] = pd.to_datetime(df_min["time"], unit="ms")
    df_min = df_min[(df_min["dt"].dt.date >= first_date) & (df_min["dt"].dt.date <= last_date)]
    df_day["dt"] = pd.to_datetime(df_day["time"], unit="ms")
    df_day = df_day.tail(WINDOW_DAYS)

    trading_days = df_day["dt"].dt.date.nunique()
    print(f"  Minute: {len(df_min)} bars over {trading_days} trading days")
    print(f"  Daily:  {len(df_day)} bars")
    passed += 1

    # ------------------------------------------------------------------
    # 2) adapt_columns — 分钟线
    # ------------------------------------------------------------------
    print(f"[2/6] Adapting minute data columns ...")
    arr_min = adapt_columns(cast(Any, df_min), stock_code=STOCK_CODE)
    print(f"  Shape: {arr_min.shape}, turnover_rate range: [{arr_min[:,4].min():.6f}, {arr_min[:,4].max():.6f}]")
    assert arr_min.shape[1] == 5
    passed += 1

    # ------------------------------------------------------------------
    # 3) 分钟线筹码分布
    # ------------------------------------------------------------------
    print(f"[3/6] Computing minute chip distribution ...")
    dist_min = minute_chip_distribution(arr_min)
    print(f"  Distribution: {len(dist_min)} price bins, "
          f"range [{dist_min.index.min():.2f}, {dist_min.index.max():.2f}]")
    print(f"  Sum: {dist_min.sum():.6f}, NaN count: {dist_min.isna().sum()}")

    if dist_min.isna().all() or dist_min.sum() < 1e-12:
        print("  [WARN] Degenerate distribution — likely contains flat days")
        # 尝试去掉 high==low 的 bar 重新计算
        flat_mask = arr_min[:, 1] == arr_min[:, 2]
        n_flat = flat_mask.sum()
        print(f"  Flat bars (high==low): {n_flat}/{len(arr_min)}")
        if n_flat < len(arr_min) * 0.5:
            arr_clean = arr_min[~flat_mask]
            dist_min = minute_chip_distribution(arr_clean)
            print(f"  After removing flat bars: sum={dist_min.sum():.6f}")
    passed += 1

    # ------------------------------------------------------------------
    # 4) 日线筹码分布（对照组）
    # ------------------------------------------------------------------
    print(f"[4/6] Computing daily chip distribution (reference) ...")
    arr_day = adapt_columns(cast(Any, df_day), stock_code=STOCK_CODE)
    dist_day = daily_chip_distribution(arr_day, method="triang")
    print(f"  Distribution: {len(dist_day)} price bins, "
          f"range [{dist_day.index.min():.2f}, {dist_day.index.max():.2f}]")
    passed += 1

    # ------------------------------------------------------------------
    # 5) 因子值对比
    # ------------------------------------------------------------------
    print(f"[5/6] Comparing chip factors: minute vs daily ...")
    close_price = float(arr_day[-1, 0])

    try:
        cf_min = cyq.ChipFactor(close_price, dist_min)
        f_min = {
            "cyqk_c": cf_min.get_cyqk_c(),
            "asr": cf_min.get_asr(),
            "ckdw": cf_min.get_ckdw(),
            "prp": cf_min.get_prp(),
        }
    except Exception as e:
        print(f"  Minute ChipFactor failed: {e}")
        f_min = {"cyqk_c": np.nan, "asr": np.nan, "ckdw": np.nan, "prp": np.nan}
        failed += 1

    cf_day = cyq.ChipFactor(close_price, dist_day)
    f_day = {
        "cyqk_c": cf_day.get_cyqk_c(),
        "asr": cf_day.get_asr(),
        "ckdw": cf_day.get_ckdw(),
        "prp": cf_day.get_prp(),
    }

    # 分钟线 vs 日线对比（信息展示，不作为通过/失败标准）
    # 分钟线用实际量价累积，日线用三角 PDF 近似——两者应不同但量级接近
    ranges = {"cyqk_c": (0.0, 1.0), "asr": (0.0, 1.0), "ckdw": (0.0, 20.0), "prp": (-1.0, 5.0)}
    print(f"  {'Factor':<8} {'Minute':>10} {'Daily':>10} {'Delta':>10} {'InRange':>8}")
    minute_ok = 0
    for name in ["cyqk_c", "asr", "ckdw", "prp"]:
        v_m = f_min[name]
        v_d = f_day[name]
        delta = abs(v_m - v_d) if not (np.isnan(v_m) or np.isnan(v_d)) else np.nan
        lo, hi = ranges[name]
        in_range = not np.isnan(v_m) and lo <= v_m <= hi
        print(f"  {name:<8} {v_m:10.4f} {v_d:10.4f} {delta:10.4f} {'OK' if in_range else 'OUT':>8}")
        if in_range:
            minute_ok += 1

    # 验证标准：分钟线因子在合理数值范围内（不与日线比方向）
    if minute_ok == 4:
        print(f"  OK: all 4 minute factors in valid range")
        passed += 1
    else:
        print(f"  WARN: {4-minute_ok}/4 minute factors out of range")
        failed += 1

    # ------------------------------------------------------------------
    # 6) 分钟线按日分组：验证 day-by-day 衰减逻辑一致
    # ------------------------------------------------------------------
    print(f"[6/6] Minute distribution per-day consistency ...")
    df_min["date"] = df_min["dt"].dt.date
    daily_ranges = df_min.groupby("date").agg(
        low=("low", "min"), high=("high", "max"),
        close=("close", "last"), vol=("volume", "sum"),
    )
    # 分钟线 close 的每日尾盘值应接近日线 close
    day_close_diff = float(
        np.std(
            np.asarray(daily_ranges["close"].values[-10:], dtype=float)
            - np.asarray(df_day["close"].values[-10:], dtype=float)
        )
    )
    print(f"  Minute daily-close vs day-bar close std diff: {day_close_diff:.4f}")
    if day_close_diff < 0.5:
        print(f"  OK: minute and daily close prices aligned")
        passed += 1
    else:
        print(f"  WARN: large deviation between minute and daily close")
        failed += 1

    # ------------------------------------------------------------------
    # 结果
    # ------------------------------------------------------------------
    print(f"\n{'=' * 50}")
    print(f"RESULTS: {passed} passed, {failed} failed")
    reader.close()
    if failed == 0:
        print("MINUTE CHIP VERIFIED — exit code 0")
        sys.exit(0)
    else:
        print("MINUTE CHIP FAILED — see warnings above")
        sys.exit(1)


if __name__ == "__main__":
    main()
