from typing import Any, cast


from myquant_factors._runtime import research_root, resolve_source_parquet
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
verify_chip_factor_consistency.py — 筹码分布因子交叉验证（日线 vs 分钟线）

验证 §8.3 方案 A：
- 日线路径：前复权日线 → adapt_columns → calc_dist_chips(triang) → ChipFactor
- 分钟线路径：未复权分钟线 → adapt_columns → minute_chip_distribution → ChipFactor
- 对比 CYQK_C / ASR / CKDW / PRP 输出，计算 Pearson r / MAE / RankIC

预期（§8.3 第 7 条）：
- 日线 vs 分钟线 Pearson r > 0.80（分布不同但排序方向应一致）
- 日线 vs 日线 Pearson r = 1.00（同源算法，完全一致）

用法：
    python backtest/verify_chip_factor_consistency.py
    python backtest/verify_chip_factor_consistency.py --stocks 50 --dates 5
"""

import argparse
import os
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

REPO = str(research_root())
sys.path.insert(0, REPO)

from myquant_factors.chip.core import (
    adapt_columns,
    daily_chip_distribution,
    minute_chip_distribution,
)
from myquant_factors import cyq
from myquant_factors._runtime import StockDataReader
from myquant_factors._runtime import resolve_period_root, resolve_source_parquet  # noqa: E402

MINUTE_DIR = str(resolve_period_root("1m") / "dividend_type=none")
DAILY_DIR = str(resolve_period_root("1d") / "dividend_type=front")
FLOAT_SHARES_PATH = str(resolve_source_parquet("float_shares.parquet"))

_reader = None

def _get_reader():
    global _reader
    if _reader is None:
        _reader = StockDataReader()
    return _reader
OUTPUT_DIR = os.path.join(REPO, "backtest_output")
WINDOW_DAYS = 80


def _compute_factors(arr: np.ndarray, mode: str) -> dict | None:
    """从 adapt_columns 输出计算 4 因子。"""
    if mode == "1m":
        dist = minute_chip_distribution(arr)
    else:
        dist = daily_chip_distribution(arr, method="triang")

    if dist is None or len(dist) == 0:
        return None

    close_price = float(arr[-1, 0])
    cf = cyq.ChipFactor(close_price, dist)
    return {
        "cyqk_c": cf.get_cyqk_c(),
        "asr": cf.get_asr(),
        "ckdw": cf.get_ckdw(),
        "prp": cf.get_prp(),
    }


def _load_window(code: str, end_date: str, freq: str, reader=None) -> np.ndarray | None:
    """加载指定标的在 end_date 前 WINDOW_DAYS 个交易日的数据窗口。"""
    if reader is None:
        reader = _get_reader()
    if freq == "1m":
        df = reader.read_stock(code, period='1m', adjust_type='none')
    else:
        df = reader.read_stock(code, period='1d', adjust_type='front')
    if df is None:
        return None
    # 时间列：优先用 'time' 列，缺失时回退到 DatetimeIndex
    if "time" in df.columns:
        df["dt"] = pd.to_datetime(df["time"], unit="ms")
    elif isinstance(df.index, pd.DatetimeIndex):
        df["dt"] = df.index
    else:
        return None
    end_ts = pd.Timestamp(end_date)

    if freq == "1d":
        df = df[df["dt"].dt.normalize() <= end_ts]
        df = cast(Any, df).sort_values("dt").tail(WINDOW_DAYS)
        if len(df) < WINDOW_DAYS:
            return None
        arr = adapt_columns(cast(Any, df), stock_code=code)
    else:
        # 分钟线：取日线最后 WINDOW_DAYS 个交易日对应的分钟 bar
        daily_candidates = df[df["dt"].dt.normalize() <= end_ts]
        trading_dates = sorted(daily_candidates["dt"].dt.normalize().unique())
        if len(trading_dates) < WINDOW_DAYS:
            return None
        window_dates = trading_dates[-WINDOW_DAYS:]
        df_win = df[df["dt"].dt.normalize().isin(window_dates)]
        if len(df_win) < 100:
            return None
        arr = adapt_columns(cast(Any, df_win), stock_code=code)

    return arr


def _common_symbols():
    """找出日线前复权与分钟线共有的标的。"""
    daily_syms = set(
        d.replace("symbol=", "").replace("_SZ", ".SZ").replace("_SH", ".SH")
        for d in os.listdir(DAILY_DIR)
        if d.startswith("symbol=")
    )
    minute_syms = set(
        d.replace("symbol=", "").replace("_SZ", ".SZ").replace("_SH", ".SH")
        for d in os.listdir(MINUTE_DIR)
        if d.startswith("symbol=")
    )
    return sorted(daily_syms & minute_syms)


def main():
    parser = argparse.ArgumentParser(description="chip 因子日线 vs 分钟线交叉验证")
    parser.add_argument("--stocks", type=int, default=100,
                        help="抽样标的数（默认 100）")
    parser.add_argument("--dates", type=int, default=5,
                        help="抽样日期数（默认 5）")
    parser.add_argument("--start", default="2026-03-10")
    parser.add_argument("--end", default="2026-05-14")
    args = parser.parse_args()

    common = _common_symbols()
    print(f"共有标的: {len(common)}")

    # 抽样
    rng = np.random.RandomState(42)
    selected = list(rng.choice(common, size=min(args.stocks, len(common)), replace=False))
    print(f"抽样标的: {len(selected)}")

    # 生成交易日历
    cal_dates = pd.date_range(args.start, args.end, freq="B")
    step = max(1, len(cal_dates) // args.dates)
    sample_dates = [cal_dates[i].strftime("%Y-%m-%d") for i in range(step - 1, len(cal_dates), step)]
    if len(sample_dates) > args.dates:
        sample_dates = sample_dates[:args.dates]
    print(f"抽样日期: {sample_dates}")

    reader = _get_reader()
    records = []
    skipped = 0
    total = len(selected) * len(sample_dates)
    done = 0

    for date_str in sample_dates:
        for code in selected:
            done += 1
            if done % 100 == 0:
                print(f"  progress: {done}/{total} ({skipped} skipped)")

            arr_d = _load_window(code, str(date_str), "1d", reader=reader)
            arr_m = _load_window(code, str(date_str), "1m", reader=reader)
            if arr_d is None or arr_m is None:
                skipped += 1
                continue

            fd = _compute_factors(arr_d, "1d")
            fm = _compute_factors(arr_m, "1m")
            if fd is None or fm is None:
                skipped += 1
                continue

            records.append({
                "date": date_str,
                "code": code,
                "d_cyqk_c": fd["cyqk_c"], "m_cyqk_c": fm["cyqk_c"],
                "d_asr": fd["asr"], "m_asr": fm["asr"],
                "d_ckdw": fd["ckdw"], "m_ckdw": fm["ckdw"],
                "d_prp": fd["prp"], "m_prp": fm["prp"],
            })

    print(f"\n有效记录: {len(records)} / {total} (跳过 {skipped})")
    if len(records) < 10:
        print("数据不足，无法计算相关性")
        reader.close()
        return

    df = pd.DataFrame(records)

    # ── 日线 vs 分钟线 对比 ──
    print(f"\n{'='*70}")
    print("日线（前复权） vs 分钟线 因子一致性")
    print(f"{'='*70}")
    print(f"{'因子':<10} {'Pearson r':>10} {'p-value':>10} {'MAE':>10} {'RankIC':>10}")
    print("-" * 50)

    factors = ["cyqk_c", "asr", "ckdw", "prp"]
    for f in factors:
        d_col, m_col = f"d_{f}", f"m_{f}"
        valid = df[[d_col, m_col]].dropna()
        if len(valid) < 5:
            print(f"{f:<10} {'N/A':>10}")
            continue
        r, p = pearsonr(valid[d_col], valid[m_col])
        mae = np.mean(cast(Any, np.abs(valid[d_col] - valid[m_col])))
        rk, _ = spearmanr(valid[d_col].rank(), valid[m_col].rank())
        print(f"{f:<10} {r:10.4f} {p:10.4f} {mae:10.4f} {rk:10.4f}")

    # ── 按日期分组的 Pearson r ──
    print("\n--- 按日期 Pearson r (cyqk_c) ---")
    for date_str in sample_dates:
        sub = df[df["date"] == date_str]
        if len(sub) < 5:
            continue
        r, p = pearsonr(sub["d_cyqk_c"], sub["m_cyqk_c"])
        print(f"  {date_str}: r={r:.4f}, p={p:.4f}, n={len(sub)}")

    # ── 一致性判定 ──
    print(f"\n{'='*70}")
    print("判定（§8.3 第 7 条验收标准）")
    print(f"{'='*70}")
    for f in factors:
        d_col, m_col = f"d_{f}", f"m_{f}"
        valid = df[[d_col, m_col]].dropna()
        if len(valid) < 5:
            print(f"  {f}: 数据不足")
            continue
        r, _ = pearsonr(valid[d_col], valid[m_col])
        status = "✅ PASS" if abs(float(cast(Any, r))) > 0.80 else "⚠️  BELOW 0.80"
        print(f"  {f}: r={r:.4f}  {status}")

    reader.close()

    # 保存
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out = os.path.join(OUTPUT_DIR, "chip_cross_validation.csv")
    df.to_csv(out, index=False)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
