from typing import Any, cast


from myquant_factors._runtime import research_root, resolve_source_parquet
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
verify_chip_pool_enhancement.py — chip 过滤层收益增量验证

对历史 stock_pool 逐日计算 chip 因子，对比"原始池" vs "chip 过滤池"的前向收益。

用法：
    python backtest/verify_chip_pool_enhancement.py
    python backtest/verify_chip_pool_enhancement.py --rule trend-safe

规则：
    trend:       cyqk_c ∈ [0.5, 1.0]
    trend-safe:  cyqk_c ∈ [0.5, 0.8]
    no-overbought: cyqk_c <= 0.8
"""

import argparse
import os
from pathlib import Path
import sys
import numpy as np
import pandas as pd

REPO = str(research_root())
sys.path.insert(0, REPO)

from myquant_factors.chip.core import adapt_columns, daily_chip_distribution
from myquant_factors.chip.shares import _estimate_turnover, _get_float_shares
from myquant_factors import cyq
from myquant_factors._runtime import parse_pool_csv
from myquant_factors._runtime import StockDataReader

STOCK_POOL_DIR = os.path.join(REPO, "stock_pool")
WINDOW = 80

_reader = None

def _get_reader():
    global _reader
    if _reader is None:
        _reader = StockDataReader()
    return _reader


def load_pool_dates() -> list:
    """获取所有 stock_pool 日期。"""
    files = sorted([f for f in os.listdir(STOCK_POOL_DIR) if f.endswith(".csv")])
    return [f.replace(".csv", "") for f in files]


def filter_pool_dates(
    pool_dates: list,
    start_date: str | None = None,
    end_date: str | None = None,
    max_dates: int = 0,
) -> list:
    """按日期区间与数量上限过滤 stock_pool 日期列表。"""
    dates = list(pool_dates)
    if start_date:
        dates = [d for d in dates if d >= start_date]
    if end_date:
        dates = [d for d in dates if d <= end_date]
    if max_dates and max_dates > 0 and len(dates) > max_dates:
        dates = dates[-max_dates:]
    return dates


def load_pool_stocks(date_str: str) -> list:
    """读取 stock_pool 标的列表。"""
    path = os.path.join(STOCK_POOL_DIR, f"{date_str}.csv")
    if not os.path.exists(path):
        return []
    return parse_pool_csv(path)


def compute_cyqk(code: str, reader=None) -> float:
    """计算单只标的的 cyqk_c。"""
    if reader is None:
        reader = _get_reader()
    df = reader.read_stock(code, period='1d', adjust_type='front')
    if df is None:
        return np.nan
    df["dt"] = pd.to_datetime(df["time"], unit="ms")
    df = cast(Any, df).sort_values("dt").tail(WINDOW)
    if len(df) < WINDOW:
        return np.nan
    # date 化流通股本：按窗口内每个交易日查询 float_shares。
    # 若 history 缺失或日期未命中，_get_float_shares 自动回退到最新快照。
    date_key = df["dt"].dt.normalize().dt.strftime("%Y-%m-%d")
    unique_keys = sorted(date_key.unique())
    fs_by_date = {k: _get_float_shares(code, k) for k in unique_keys}
    fs_series = date_key.map(fs_by_date).astype(np.float64)
    df["turnover_rate"] = _estimate_turnover(cast(Any, df["volume"].values), fs_series.values)
    arr = adapt_columns(cast(Any, df), stock_code=code)
    try:
        dist = daily_chip_distribution(arr, method="triang")
        cf = cyq.ChipFactor(float(arr[-1, 0]), dist)
        return cf.get_cyqk_c()
    except Exception:
        return np.nan


def forward_return(code: str, from_date: str, horizon: int, reader=None) -> float:
    """计算标的自 from_date 起 horizon 天的前向收益。"""
    if reader is None:
        reader = _get_reader()
    df = reader.read_stock(code, period='1d', adjust_type='front')
    if df is None:
        return np.nan
    df["dt"] = pd.to_datetime(df["time"], unit="ms")
    start_ts = pd.Timestamp(from_date)
    mask = df["dt"] >= start_ts
    if not mask.any():
        return np.nan
    pos = int(np.argmax(mask.values))
    end_pos = pos + horizon
    if end_pos >= len(df):
        return np.nan
    return float(df["close"].iloc[end_pos]) / float(df["close"].iloc[pos]) - 1.0


def main():
    parser = argparse.ArgumentParser(description="chip 过滤层收益增量验证")
    parser.add_argument("--rule", default="trend",
                        choices=["trend", "trend-safe", "no-overbought"])
    parser.add_argument("--horizon", type=int, default=10,
                        help="前向收益窗口（天），默认 10")
    parser.add_argument("--start-date", default=None,
                        help="起始日期（YYYYMMDD），默认不限制")
    parser.add_argument("--end-date", default=None,
                        help="结束日期（YYYYMMDD），默认不限制")
    parser.add_argument("--max-dates", type=int, default=0,
                        help="仅评估最近 N 个日期（0=不限制）")
    args = parser.parse_args()

    all_pool_dates = load_pool_dates()
    if not all_pool_dates:
        print("无 stock_pool 日期可用")
        return
    print(f"stock_pool 全量日期: {len(all_pool_dates)} ({all_pool_dates[0]} ~ {all_pool_dates[-1]})")
    pool_dates = filter_pool_dates(
        all_pool_dates,
        start_date=args.start_date,
        end_date=args.end_date,
        max_dates=args.max_dates,
    )
    if not pool_dates:
        print("按参数过滤后无可评估日期，请检查 --start-date/--end-date/--max-dates")
        return
    print(f"本次评估日期: {len(pool_dates)} ({pool_dates[0]} ~ {pool_dates[-1]})")

    if args.rule == "trend":
        def rule_fn(cyqk): return 0.5 <= cyqk <= 1.0
        rule_name = "趋势做多 [0.5, 1.0]"
    elif args.rule == "trend-safe":
        def rule_fn(cyqk): return 0.5 <= cyqk <= 0.8
        rule_name = "趋势安全 [0.5, 0.8]"
    else:
        def rule_fn(cyqk): return cyqk <= 0.8
        rule_name = "排除高位 >0.8"

    print(f"规则: {rule_name}")
    print(f"前向窗口: {args.horizon}d")

    reader = _get_reader()

    # ── 逐日评估 ──
    results = []
    for date_str in pool_dates:
        codes = load_pool_stocks(date_str)
        if len(codes) < 3:
            continue

        # 计算 cyqk_c
        cyqk_map = {}
        for code in codes:
            cyqk = compute_cyqk(code, reader=reader)
            if not np.isnan(cyqk):
                cyqk_map[code] = cyqk

        if len(cyqk_map) < 3:
            continue

        # 分组
        original = list(cyqk_map.keys())
        filtered = [c for c, v in cyqk_map.items() if rule_fn(v)]

        if len(filtered) < 2:
            continue

        # 前向收益
        orig_rets = []
        for c in original:
            r = forward_return(c, date_str, args.horizon, reader=reader)
            if not np.isnan(r):
                orig_rets.append(r)

        filt_rets = []
        for c in filtered:
            r = forward_return(c, date_str, args.horizon, reader=reader)
            if not np.isnan(r):
                filt_rets.append(r)

        if len(orig_rets) < 2 or len(filt_rets) < 2:
            continue

        results.append({
            "date": date_str,
            "orig_n": len(original),
            "filt_n": len(filtered),
            "orig_ret": np.mean(cast(Any, orig_rets)),
            "filt_ret": np.mean(cast(Any, filt_rets)),
            "orig_median": np.median(orig_rets),
            "filt_median": np.median(orig_rets),
            "enhancement": np.mean(cast(Any, filt_rets)) - np.mean(cast(Any, orig_rets)),
        })

    if not results:
        print("无有效数据")
        reader.close()
        return

    df = pd.DataFrame(results)
    print(f"\n有效截面: {len(df)}")

    # ── 汇总统计 ──
    orig_mean = df["orig_ret"].mean() * 100
    filt_mean = df["filt_ret"].mean() * 100
    enhancement = df["enhancement"].mean() * 100
    win_rate = (df["enhancement"] > 0).mean() * 100

    print(f"\n{'='*60}")
    print(f"  {args.horizon}d 前向收益对比")
    print(f"{'='*60}")
    print(f"  原始池平均收益:    {orig_mean:+.2f}%")
    print(f"  Chip过滤池平均收益: {filt_mean:+.2f}%")
    print(f"  超额收益:          {enhancement:+.2f}%")
    print(f"  胜率（超额>0）:    {win_rate:.1f}%")
    print(f"  日均过滤:          {df['orig_n'].mean():.0f} → {df['filt_n'].mean():.0f} 只")
    print(f"  原始池>0比例:      {(df['orig_ret'] > 0).mean() * 100:.1f}%")
    print(f"  过滤池>0比例:      {(df['filt_ret'] > 0).mean() * 100:.1f}%")

    # ── 逐月 ──
    df["month"] = df["date"].str[:6]
    monthly = pd.DataFrame(
        df.groupby("month").agg(
            orig_ret=("orig_ret", "mean"),
            filt_ret=("filt_ret", "mean"),
            n=("date", "count"),
        )
    )
    monthly["enhancement"] = monthly["filt_ret"] - monthly["orig_ret"]
    print(f"\n--- 按月度 ---")
    print(f"  {'month':<8} {'n':>5} {'原始':>10} {'过滤':>10} {'超额':>10}")
    for m, row in monthly.iterrows():
        print(f"  {m:<8} {int(row['n']):>5} {row['orig_ret']*100:+8.2f}% "
              f"{row['filt_ret']*100:+8.2f}% {row['enhancement']*100:+8.2f}%")

    # ── 累积收益（等权） ──
    df_sorted = cast(Any, df).sort_values("date")
    df_sorted["orig_cum"] = (1 + df_sorted["orig_ret"]).cumprod()
    df_sorted["filt_cum"] = (1 + df_sorted["filt_ret"]).cumprod()
    print(f"\n--- 累积收益 ---")
    print(f"  原始池: {(df_sorted['orig_cum'].iloc[-1] - 1) * 100:+.2f}%")
    print(f"  过滤池: {(df_sorted['filt_cum'].iloc[-1] - 1) * 100:+.2f}%")

    reader.close()


if __name__ == "__main__":
    main()
