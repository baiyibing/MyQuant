#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
rolling_ic_chip_factors.py — chip 因子长历史滚动 IC 分析

从 2020-01-01 起的全量日线数据，每隔 N 个交易日计算一次截面 RankIC，
评估 chip 因子在完整牛熊周期中的选股稳定性。

用法：
    python backtest/research/rolling_ic_chip_factors.py
    python backtest/research/rolling_ic_chip_factors.py --stocks 200 --step 20

输出：backtest_output/rolling_ic_chip_factors.csv
"""

from myquant_factors._runtime import research_root, resolve_source_parquet

import argparse
import os
import sys
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO = str(research_root())
sys.path.insert(0, REPO)

from myquant_factors.compat_chip import (
    adapt_columns, daily_chip_distribution, cyq,
    turnover_chip_factors, _get_float_shares, _estimate_turnover,
)
from myquant_factors._runtime import resolve_source_parquet
from myquant_factors._runtime import StockDataReader

_reader = None

def _get_reader():
    global _reader
    if _reader is None:
        _reader = StockDataReader()
    return _reader
FLOAT_SHARES_PATH = str(resolve_source_parquet("float_shares.parquet"))
OUTPUT_DIR = os.path.join(REPO, "backtest_output")
WINDOW = 80
TURNOVER_WINDOW = 60


def _load_data(reader, code: str) -> pd.DataFrame:
    """加载标的全量日线数据。"""
    df = reader.read_stock(code, period='1d', adjust_type='front')
    if df is None:
        return None
    df["dt"] = pd.to_datetime(df["time"], unit="ms")
    df = df.sort_values("dt").reset_index(drop=True)
    if len(df) < WINDOW + 20:
        return None

    # 使用按日期查询的流通股本；未命中时 _get_float_shares 会自动回退到最新快照。
    date_norm = df["dt"].dt.normalize()
    date_key = date_norm.dt.strftime("%Y-%m-%d")
    unique_keys = sorted(date_key.unique())
    fs_by_date = {k: _get_float_shares(code, k) for k in unique_keys}
    fs_series = date_key.map(fs_by_date).astype(np.float64)
    df["turnover_rate"] = _estimate_turnover(df["volume"].values, fs_series.values)
    return df


def _compute_cross_section(codes, stock_data, eval_date_str, t):
    """在单个截面计算所有标的的因子值。"""
    eval_ts = pd.Timestamp(eval_date_str)
    records = []

    for code in codes:
        df = stock_data.get(code)
        if df is None:
            continue

        # 找到截面位置
        end_mask = df["dt"] <= eval_ts
        if not end_mask.any():
            continue
        idx = end_mask[end_mask].index[-1]
        if idx < WINDOW - 1:
            continue

        # 日线窗口
        daily_win = df.iloc[max(0, idx - WINDOW + 1):idx + 1]
        if len(daily_win) < WINDOW:
            continue
        arr = adapt_columns(daily_win, stock_code=code)
        try:
            dist = daily_chip_distribution(arr, method="triang")
            cf = cyq.ChipFactor(float(arr[-1, 0]), dist)
        except Exception:
            continue

        # 换手率因子
        close_all = df["close"].values[:idx + 1]
        tr_all = df["turnover_rate"].values[:idx + 1]
        try:
            tcf = turnover_chip_factors(tr_all, close_all, window=TURNOVER_WINDOW)
        except Exception:
            tcf = {"arc": np.nan, "vrc": np.nan, "src": np.nan, "krc": np.nan}

        # 前向收益
        current_close = float(df["close"].values[idx])
        fwd = {}
        for h in [1, 5, 10, 20]:
            fwd_idx = idx + h
            if fwd_idx < len(df):
                fwd[f"fwd_{h}d"] = float(df["close"].values[fwd_idx]) / current_close - 1.0
            else:
                fwd[f"fwd_{h}d"] = np.nan

        records.append({
            "date": eval_date_str,
            "code": code,
            "cyqk_c": cf.get_cyqk_c(),
            "asr": cf.get_asr(),
            "prp": cf.get_prp(),
            "arc": tcf["arc"],
            "vrc": tcf["vrc"],
            "src": tcf["src"],
            "krc": tcf["krc"],
            **fwd,
        })

    return records


def main():
    parser = argparse.ArgumentParser(description="chip 因子长历史滚动 IC")
    parser.add_argument("--stocks", type=int, default=200)
    parser.add_argument("--step", type=int, default=20,
                        help="截面间隔（交易日），默认 20")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-05-14")
    args = parser.parse_args()

    reader = StockDataReader()

    # ── 标的 ──
    fs_all = pd.read_parquet(FLOAT_SHARES_PATH)
    rng = np.random.RandomState(42)
    codes = list(rng.choice(fs_all["stock_code"].tolist(),
                            size=min(args.stocks, len(fs_all)), replace=False))
    print(f"Stocks: {len(codes)}")

    # ── 加载全量数据 ──
    print("Loading data...")
    stock_data = {}
    for code in codes:
        df = _load_data(reader, code)
        if df is not None:
            stock_data[code] = df
    print(f"  Loaded: {len(stock_data)} stocks")

    # ── 截面日期 ──
    first_dates = []
    for code in stock_data:
        df = stock_data[code]
        first_dates.append(df[df["dt"] >= pd.Timestamp("2020-04-01")]["dt"].min())
    common_start = pd.Timestamp(args.start)
    if first_dates:
        common_start = max(common_start, min(first_dates))

    cal_dates = pd.date_range(common_start, args.end, freq="B")
    # 间隔取样
    cross_dates = [d.strftime("%Y-%m-%d") for i, d in enumerate(cal_dates)
                   if i % args.step == 0]
    print(f"Cross-sections: {len(cross_dates)} ({cross_dates[0]} ~ {cross_dates[-1]})")

    # ── 逐截面计算 ──
    all_records = []
    for i, date_str in enumerate(cross_dates):
        if (i + 1) % 20 == 0:
            print(f"  ... {i + 1}/{len(cross_dates)} sections, {len(all_records)} records")

        records = _compute_cross_section(codes, stock_data, date_str, i)
        all_records.extend(records)

    if not all_records:
        print("No records")
        reader.close()
        return

    df = pd.DataFrame(all_records)
    print(f"\nTotal: {len(df)} records, {df['date'].nunique()} sections, "
          f"{df['code'].nunique()} stocks")

    # ── 滚动 IC 分析 ──
    factors = ["cyqk_c", "asr", "prp", "arc", "vrc", "src", "krc"]
    horizons = [5, 10, 20]

    print(f"\n{'='*80}")
    print("长历史滚动 IC（逐截面 RankIC 统计）")
    print(f"{'='*80}")
    print(f"{'因子':<10} {'窗口':>6} {'IC均值':>10} {'IC Std':>10} {'ICIR':>8} {'>0%':>8} {'|IC|>0.05%':>12}")
    print("-" * 70)

    for f in factors:
        for h in horizons:
            fwd_col = f"fwd_{h}d"
            sub = df[[f, fwd_col, "date"]].dropna()
            ic_list = []
            for date, grp in sub.groupby("date"):
                if len(grp) < 10:
                    continue
                valid = grp[[f, fwd_col]].dropna()
                if len(valid) < 10:
                    continue
                ic, _ = spearmanr(valid[f].rank(), valid[fwd_col].rank())
                ic_list.append(float(ic))

            if not ic_list:
                continue
            ic_arr = np.array(ic_list)
            ic_mean = np.mean(ic_arr)
            ic_std = np.std(ic_arr)
            icir = ic_mean / ic_std if ic_std > 0 else 0
            pct_pos = np.mean(ic_arr > 0) * 100
            pct_sig = np.mean(np.abs(ic_arr) > 0.05) * 100

            print(f"{f:<10} {h:>5}d {ic_mean:10.4f} {ic_std:10.4f} "
                  f"{icir:8.2f} {pct_pos:7.1f}% {pct_sig:11.1f}%")

    # ── 时间序列摘要 ──
    print(f"\n--- cyqk_c 20d IC 时间序列（部分）---")
    ic_ts = []
    for date, grp in df.groupby("date"):
        valid = grp[["cyqk_c", "fwd_20d"]].dropna()
        if len(valid) < 10:
            continue
        ic, _ = spearmanr(valid["cyqk_c"].rank(), valid["fwd_20d"].rank())
        ic_ts.append((date, float(ic), len(valid)))

    ic_ts.sort(key=lambda x: x[0])
    # 每 10 个截面打印一次
    for i in range(0, len(ic_ts), max(1, len(ic_ts) // 10)):
        d, ic_val, n = ic_ts[i]
        bar = "+" if ic_val > 0 else "-"
        print(f"  {d}: IC={ic_val:+.4f} n={n} {bar * int(abs(ic_val) * 100)}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out = os.path.join(OUTPUT_DIR, "rolling_ic_chip_factors.csv")
    df.to_csv(out, index=False)
    print(f"\nSaved: {out}")

    reader.close()


if __name__ == "__main__":
    main()
