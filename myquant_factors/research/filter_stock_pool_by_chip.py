#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false
r"""
filter_stock_pool_by_chip.py — chip 因子增强选股过滤（生产对接层）

在现有 stock_pool 基础上叠加 chip 因子过滤，输出精选标的列表。

用法：
    # 对最新 stock_pool 应用趋势过滤（cyqk_c >= 0.5）
    python backtest/filter_stock_pool_by_chip.py --rule trend

    # 指定日期 + 排除短期反转风险（排除 cyqk_c > 0.8）
    python backtest/filter_stock_pool_by_chip.py --date 20260515 --rule no-overbought

    # 组合规则：趋势做多 + 排除获利抛压
    python backtest/filter_stock_pool_by_chip.py --rule trend --no-arc-positive

    # 仅输出因子值，不做过滤（用于人工筛选）
    python backtest/filter_stock_pool_by_chip.py --rule none

规则（基于多轮回测验证）：
    trend:       cyqk_c ∈ [0.5, 1.0] — 中期趋势做多（超额 +17.0%，Sharpe 3.70）
    no-lows:     cyqk_c >= 0.2 — 排除深度套牢盘（超额 +11.3%）
    no-overbought: cyqk_c <= 0.8 — 排除短期获利抛压
    组合: trend + no-overbought → [0.5, 0.8]
"""

import argparse
import os
import sys
from typing import Any, Optional, cast
import numpy as np
import pandas as pd

from myquant_factors._runtime import research_root
REPO = str(research_root())
sys.path.insert(0, REPO)

from myquant_factors.chip.core import (
    adapt_columns,
    daily_chip_distribution,
    turnover_chip_factors,
)
from myquant_factors.chip.shares import _estimate_turnover, _get_float_shares
from myquant_factors import cyq
from myquant_factors._runtime import parse_pool_csv_entries
from myquant_factors._runtime import StockDataReader

STOCK_POOL_DIR = os.path.join(REPO, "stock_pool")
OUTPUT_DIR = os.path.join(REPO, "backtest_output")
WINDOW = 80

_reader = None

def _get_reader():
    global _reader
    if _reader is None:
        _reader = StockDataReader()
    return _reader


def load_stock_pool(date_str: str) -> list:
    """读取 stock_pool CSV，返回 [(code, name), ...]"""
    path = os.path.join(STOCK_POOL_DIR, f"{date_str}.csv")
    if not os.path.exists(path):
        return []
    return parse_pool_csv_entries(path)


def compute_all_factors(code: str, reader=None) -> Optional[dict]:
    """计算单只标的的全部 chip 因子（CYQ 4 + turnover 4 + 阻力）。"""
    if reader is None:
        reader = _get_reader()
    df = reader.read_stock(code, period='1d', adjust_type='front')
    if df is None:
        return None

    df["dt"] = pd.to_datetime(df["time"], unit="ms")
    df = df.sort_values("dt").tail(WINDOW)
    if len(df) < WINDOW:
        return None

    # date 化流通股本：按窗口内每个交易日查询 float_shares。
    # 若 history 缺失或日期未命中，_get_float_shares 自动回退到最新快照。
    date_key = df["dt"].dt.normalize().dt.strftime("%Y-%m-%d")
    unique_keys = sorted(date_key.unique())
    fs_by_date = {k: _get_float_shares(code, k) for k in unique_keys}
    fs_series = date_key.map(fs_by_date).astype(np.float64)
    df["turnover_rate"] = _estimate_turnover(
        cast(Any, df["volume"].values), cast(Any, fs_series.values)
    )

    arr = adapt_columns(cast(Any, df), stock_code=code)
    try:
        dist = daily_chip_distribution(arr, method="triang")
        cf = cyq.ChipFactor(float(arr[-1, 0]), dist)
    except Exception:
        return None

    # 换手率半衰期因子
    close_all = df["close"].values
    tr_all = df["turnover_rate"].values
    try:
        tcf = turnover_chip_factors(
            cast(Any, tr_all), cast(Any, close_all), window=60
        )
    except Exception:
        tcf = {"arc": np.nan, "vrc": np.nan, "src": np.nan, "krc": np.nan}

    # 阻力（跨日衍生因子）
    today_cyqk = cf.get_cyqk_c()
    today_close = float(arr[-1, 0])
    today_turn = float(arr[-1, 4])
    if len(df) >= 2:
        # 上一日：重新计算前一天的 cyqk_c
        df_y = df.iloc[:-1].tail(WINDOW)
        if len(df_y) >= WINDOW:
            arr_y = adapt_columns(df_y, stock_code=code)
            try:
                dist_y = daily_chip_distribution(arr_y, method="triang")
                cf_y = cyq.ChipFactor(float(arr_y[-1, 0]), dist_y)
                yest_cyqk = cf_y.get_cyqk_c()
            except Exception:
                yest_cyqk = today_cyqk
        else:
            yest_cyqk = today_cyqk
    else:
        yest_cyqk = today_cyqk

    profit_chip_diff = today_cyqk - yest_cyqk
    if today_turn > 0:
        resistance = profit_chip_diff / today_turn
    else:
        resistance = 0.0

    return {
        "code": code,
        "close": today_close,
        "turnover": today_turn,
        "cyqk_c": today_cyqk,
        "asr": cf.get_asr(),
        "ckdw": cf.get_ckdw(),
        "prp": cf.get_prp(),
        "arc": tcf["arc"],
        "vrc": tcf["vrc"],
        "src": tcf["src"],
        "krc": tcf["krc"],
        "resistance": round(resistance, 1),
    }


def apply_rules(df: pd.DataFrame, rule: str, no_arc_positive: bool) -> pd.DataFrame:
    """应用 chip 因子过滤规则。"""
    result = df.copy()
    conditions = []

    if rule == "trend":
        conditions.append((result["cyqk_c"] >= 0.5) & (result["cyqk_c"] <= 1.0))
        label = "趋势做多 [0.5,1.0]"
    elif rule == "no-lows":
        conditions.append(result["cyqk_c"] >= 0.2)
        label = "排除套牢盘 <0.2"
    elif rule == "no-overbought":
        conditions.append(result["cyqk_c"] <= 0.8)
        label = "排除获利抛压 >0.8"
    elif rule == "trend-safe":
        conditions.append((result["cyqk_c"] >= 0.5) & (result["cyqk_c"] <= 0.8))
        label = "趋势安全 [0.5,0.8]"
    elif rule == "none":
        label = "无过滤（仅因子值）"
    else:
        print(f"[WARN] Unknown rule '{rule}', using 'none'")
        label = "无过滤"

    if rule != "none" and conditions:
        mask = conditions[0]
        for c in conditions[1:]:
            mask = mask & c
        result = result[mask]
    else:
        mask = pd.Series(True, index=result.index)

    if no_arc_positive:
        result = result[result["arc"] <= 0]
        label += " + 排除ARC>0"

    print(f"  规则: {label}")
    print(f"  输入: {len(df)}, 输出: {len(result)} (-{len(df)-len(result)})")
    return cast(pd.DataFrame, result)


def main():
    parser = argparse.ArgumentParser(description="chip 因子增强选股过滤")
    parser.add_argument("--date", default=None,
                        help="stock_pool 日期 YYYYMMDD，默认最新")
    parser.add_argument("--rule", default="trend",
                        choices=["trend", "no-lows", "no-overbought", "trend-safe", "none"],
                        help="过滤规则（默认 trend）")
    parser.add_argument("--no-arc-positive", action="store_true",
                        help="排除 ARC>0（股东平均盈利→获利抛压）")
    parser.add_argument("--top", type=int, default=0,
                        help="按 cyqk_c 排序取前 N 只（0=不截断）")
    args = parser.parse_args()

    # ── 确定日期 ──
    if args.date:
        date_str = args.date
    else:
        pool_files = sorted([f for f in os.listdir(STOCK_POOL_DIR) if f.endswith(".csv")])
        if not pool_files:
            print("[ERROR] No stock_pool files found")
            return
        date_str = pool_files[-1].replace(".csv", "")

    print(f"日期: {date_str}")
    print(f"规则: {args.rule}")

    # ── 读取 stock_pool ──
    entries = load_stock_pool(date_str)
    if not entries:
        print(f"[ERROR] No stocks in stock_pool for {date_str}")
        return
    print(f"stock_pool 标的: {len(entries)}")

    # ── 计算 chip 因子 ──
    reader = _get_reader()
    records = []
    for i, (code, name) in enumerate(entries):
        if (i + 1) % 50 == 0:
            print(f"  ... {i + 1}/{len(entries)}")
        factors = compute_all_factors(code, reader=reader)
        if factors:
            factors["name"] = name
            records.append(factors)

    if not records:
        print("[ERROR] No valid factors computed")
        return

    df = pd.DataFrame(records)
    reader.close()
    print(f"  有效标的: {len(df)}")

    # ── 应用规则 ──
    result = apply_rules(df, args.rule, args.no_arc_positive)

    # ── Top N ──
    if args.top > 0 and len(result) > args.top:
        result = result.sort_values("cyqk_c", ascending=False).head(args.top)
        print(f"  Top {args.top}: {len(result)}")

    # ── 输出 ──
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 因子截面
    factor_out = os.path.join(OUTPUT_DIR, f"chip_pool_{date_str}.csv")
    cols = ["code", "name", "close", "turnover", "cyqk_c", "asr", "prp",
            "arc", "vrc", "resistance"]
    cast(Any, df[cols]).sort_values("cyqk_c", ascending=False).to_csv(factor_out, index=False)
    print(f"  因子截面: {factor_out}")

    # 过滤后的 stock_pool
    if args.rule != "none":
        pool_out = os.path.join(OUTPUT_DIR, f"stock_pool_chip_{date_str}.csv")
        with open(pool_out, "w", encoding="utf-8") as f:
            for _, row in result.iterrows():
                code_short = row["code"].replace(".SH", "").replace(".SZ", "")
                f.write(f"{code_short},{row.get('name', '')}\n")
        print(f"  精选池: {pool_out}")

    # ── 摘要 ──
    print(f"\n  因子分布 (n={len(df)}):")
    for col in ["cyqk_c", "asr", "prp", "arc", "vrc"]:
        vals = df[col].dropna()
        print(f"    {col:<10} median={vals.median():.3f}  "
              f"q25={vals.quantile(0.25):.3f}  q75={vals.quantile(0.75):.3f}")


if __name__ == "__main__":
    main()
