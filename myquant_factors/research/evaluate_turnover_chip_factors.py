#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false
r"""
evaluate_turnover_chip_factors.py — ARC/VRC/SRC/KRC 因子评估

基于 float_shares 全市场标的，评估换手率半衰期筹码因子的选股能力。

用法：
    python backtest/evaluate_turnover_chip_factors.py
    python backtest/evaluate_turnover_chip_factors.py --stocks 200 --horizon 20

输出：backtest_output/turnover_chip_eval.csv（每个 stock×date 的因子值 + 前向收益）
"""

import argparse
import os

from myquant_factors._runtime import resolve_source_parquet
import sys
from typing import Any, Optional, cast
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from myquant_factors._runtime import research_root
REPO = str(research_root())
sys.path.insert(0, REPO)

from myquant_factors.chip.shares import _estimate_turnover, _get_float_shares
from myquant_factors.chip.core import turnover_chip_factors
from myquant_factors._runtime import StockDataReader

_reader = None

def _get_reader():
    global _reader
    if _reader is None:
        _reader = StockDataReader()
    return _reader
def _float_shares_path() -> str:
    return str(resolve_source_parquet("float_shares.parquet"))
OUTPUT_DIR = os.path.join(REPO, "backtest_output")
WINDOW = 60


def _load_stock_data(reader, code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """加载标的日线数据，返回含 close/volume/turnover_rate 的 DataFrame。"""
    df = reader.read_stock(code, period='1d', adjust_type='front')
    if df is None:
        return None

    df["dt"] = pd.to_datetime(df["time"], unit="ms")
    df = df[(df["dt"] >= pd.Timestamp(start_date)) & (df["dt"] <= pd.Timestamp(end_date))]
    df = df.sort_values("dt").reset_index(drop=True)

    if len(df) < WINDOW + 20:  # need window + max forward horizon
        return None

    # date 化流通股本：按每个交易日查询 float_shares。
    # 若 history 不存在或日期未命中，_get_float_shares 自动回退到最新快照，兼容旧行为。
    date_key = df["dt"].dt.normalize().dt.strftime("%Y-%m-%d")
    unique_keys = sorted(date_key.unique())
    fs_by_date = {k: _get_float_shares(code, k) for k in unique_keys}
    fs_series = date_key.map(fs_by_date).astype(np.float64)
    df["turnover_rate"] = _estimate_turnover(
        cast(Any, df["volume"].values), cast(Any, fs_series.values)
    )
    return df


def main():
    parser = argparse.ArgumentParser(description="ARC/VRC/SRC/KRC 因子评估")
    parser.add_argument("--stocks", type=int, default=200,
                        help="抽样标的数（默认 200）")
    parser.add_argument("--start", default="2025-01-02",
                        help="数据起始日（需早于评估起始日以构建窗口）")
    parser.add_argument("--eval-start", default="2025-06-01",
                        help="评估起始日（保证至少 60 日窗口）")
    parser.add_argument("--eval-end", default="2026-05-14")
    parser.add_argument("--horizon", type=int, default=20,
                        help="最大前向收益窗口（天），默认 20")
    args = parser.parse_args()

    reader = StockDataReader()

    # ── 标的抽样 ──
    fs_all = pd.read_parquet(_float_shares_path())
    rng = np.random.RandomState(42)
    codes = list(rng.choice(fs_all["stock_code"].tolist(),
                            size=min(args.stocks, len(fs_all)), replace=False))
    print(f"评估标的: {len(codes)}")

    # ── 交易日历 ──
    cal = pd.date_range(args.eval_start, args.eval_end, freq="B")
    eval_dates = [d.strftime("%Y-%m-%d") for d in cal]
    print(f"评估日期: {eval_dates[0]} ~ {eval_dates[-1]} ({len(eval_dates)} 个交易日)")

    # ── 主循环 ──
    records = []
    skipped = 0
    done = 0
    total = len(codes)

    for code in codes:
        done += 1
        if done % 50 == 0:
            print(f"  progress: {done}/{total} stocks ({len(records)} records, {skipped} skipped)")

        df = _load_stock_data(reader, code, args.start, args.eval_end)
        if df is None:
            skipped += 1
            continue

        for eval_date in eval_dates:
            end_idx = df[df["dt"] <= pd.Timestamp(eval_date)].index
            if len(end_idx) == 0:
                continue
            pos = int(len(end_idx) - 1)

            if pos < WINDOW - 1:
                continue

            # 因子窗口
            close_win = cast(Any, df["close"].values[: pos + 1])
            tr_win = cast(Any, df["turnover_rate"].values[: pos + 1])

            try:
                factors = turnover_chip_factors(tr_win, close_win, window=WINDOW)
            except Exception:
                continue

            if any(np.isnan(v) for v in factors.values()):
                continue

            # 前向收益
            current_close = float(df["close"].values[pos])
            fwd = {}
            for h in [1, 5, 10, 20]:
                fwd_idx = pos + h
                if fwd_idx < len(df):
                    fwd[f"fwd_{h}d"] = float(df["close"].values[fwd_idx]) / current_close - 1.0
                else:
                    fwd[f"fwd_{h}d"] = np.nan

            records.append({
                "date": eval_date,
                "code": code,
                "arc": factors["arc"],
                "vrc": factors["vrc"],
                "src": factors["src"],
                "krc": factors["krc"],
                **fwd,
            })

    if not records:
        print("No valid records")
        reader.close()
        return

    df = pd.DataFrame(records)
    print(f"\n总记录: {len(df)}, 覆盖 {df['date'].nunique()} 个交易日, "
          f"{df['code'].nunique()} 只标的")

    # ── RankIC 分析 ──
    factors = ["arc", "vrc", "src", "krc"]
    horizons = [1, 5, 10, 20]

    print(f"\n{'='*70}")
    print("RankIC 分析（截面因子排名 vs 前向收益）")
    print(f"{'='*70}")
    print(f"{'因子':<8} {'窗口':>6} {'RankIC':>10} {'p-value':>10} {'ICIR':>8} {'>0%':>8}")
    print("-" * 55)

    for f in factors:
        for h in horizons:
            fwd_col = f"fwd_{h}d"
            sub = df[[f, fwd_col, "date"]].dropna()
            if len(sub) < 10:
                continue

            # 逐截面 RankIC
            ic_list = []
            for date, grp in sub.groupby("date"):
                if len(grp) < 5:
                    continue
                valid = grp[[f, fwd_col]].dropna()
                if len(valid) < 5:
                    continue
                ic, _ = spearmanr(valid[f].rank(), valid[fwd_col].rank())
                ic_list.append(ic)

            if not ic_list:
                continue
            ic_arr = np.array(ic_list)
            ic_mean = np.mean(ic_arr)
            ic_std = np.std(ic_arr)
            icir = ic_mean / ic_std if ic_std > 0 else 0
            pct_pos = np.mean(ic_arr > 0) * 100

            print(f"{f:<8} {h:>5}d {ic_mean:10.4f} {'N/A':>10} "
                  f"{icir:8.2f} {pct_pos:7.1f}%")

    # ── 分位数收益 ──
    print(f"\n{'='*70}")
    print("分位数收益（Q1=低因子值, Q5=高因子值）")
    print(f"{'='*70}")
    for h in [1, 5, 20]:
        print(f"\n--- Forward {h}d ---")
        print(f"{'因子':<8} {'Q1':>10} {'Q2':>10} {'Q3':>10} {'Q4':>10} {'Q5':>10} {'Q5-Q1':>10}")
        print("-" * 72)
        for f in factors:
            fwd_col = f"fwd_{h}d"
            sub = df[[f, fwd_col]].dropna()
            if len(sub) < 20:
                continue
            sub["q"] = pd.qcut(sub[f].rank(method="first"), 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"])
            q_ret = cast(Any, sub.groupby("q")[fwd_col].mean()) * 100
            vals = [f"{q_ret.get(q, 0):+.2f}%" for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]]
            spread = q_ret.get("Q5", 0) - q_ret.get("Q1", 0)
            print(f"{f:<8} {vals[0]:>10} {vals[1]:>10} {vals[2]:>10} {vals[3]:>10} {vals[4]:>10} {spread:+9.2f}%")

    # ── 截面相关性 ──
    print(f"\n{'='*70}")
    print("因子间截面相关性（Spearman）")
    print(f"{'='*70}")
    print(f"{'':>8} {'arc':>10} {'vrc':>10} {'src':>10} {'krc':>10}")
    for f1 in factors:
        vals = []
        for f2 in factors:
            valid = df[[f1, f2]].dropna()
            if f1 == f2:
                r_val = 1.0
            else:
                ic, _ = spearmanr(valid[f1], valid[f2])
                r_val = float(np.asarray(ic).ravel()[0])
            vals.append(f"{r_val:.3f}" if not np.isnan(r_val) else "N/A")
        print(f"{f1:>8} {vals[0]:>10} {vals[1]:>10} {vals[2]:>10} {vals[3]:>10}")

    # 保存
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out = os.path.join(OUTPUT_DIR, "turnover_chip_eval.csv")
    df.to_csv(out, index=False)
    print(f"\nSaved: {out}")

    reader.close()


if __name__ == "__main__":
    main()
