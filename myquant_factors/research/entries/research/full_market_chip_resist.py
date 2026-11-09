#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全市场换手阻力 + 布林带输出。

用法：
    D:/anaconda3/envs/vanna312/python.exe scripts/research/full_market_chip_resist.py
    D:/anaconda3/envs/vanna312/python.exe scripts/research/full_market_chip_resist.py --date 20260515 --output full_market.csv
"""
from __future__ import annotations

from myquant_factors._runtime import research_root, resolve_source_parquet

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = research_root()
sys.path.insert(0, str(REPO))

from myquant_factors._runtime import resolve_source_parquet
from myquant_factors._runtime import StockDataReader
from myquant_factors.compat_chip import (
    adapt_columns,
    compute_crossday_turnover_resistance,
    daily_chip_distribution,
)


def _cost_at_ratio(cumpdf: pd.Series, ratio: float) -> float:
    total = cumpdf.sum()
    if total <= 0:
        return float("nan")
    acc = (cumpdf / total).cumsum()
    mask = acc >= ratio
    if not mask.any():
        return float(cumpdf.index[-1])
    return float(cumpdf.index[mask].min())


def compute_bollinger(close_series: np.ndarray, window: int = 20, num_std: float = 2.0) -> dict:
    """计算布林带。"""
    if len(close_series) < window:
        return {"boll_mid": "", "boll_upper": "", "boll_lower": "", "boll_width": "", "boll_pct_b": ""}
    roll = pd.Series(close_series).rolling(window=window)
    mid = roll.mean().iloc[-1]
    std = roll.std(ddof=0).iloc[-1]
    upper = mid + num_std * std
    lower = mid - num_std * std
    width = (upper - lower) / mid if mid > 0 else float("nan")
    last_close = close_series[-1]
    pct_b = (last_close - lower) / (upper - lower) if (upper - lower) > 0 else float("nan")
    return {
        "boll_mid": round(mid, 2),
        "boll_upper": round(upper, 2),
        "boll_lower": round(lower, 2),
        "boll_width": round(width, 4),
        "boll_pct_b": round(pct_b, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="全市场换手阻力 + 布林带")
    parser.add_argument("--date", default="20260515", help="目标日期 YYYYMMDD")
    parser.add_argument("--output", type=str, default=None, help="输出 CSV 路径")
    parser.add_argument("--window", type=int, default=80, help="筹码窗口（交易日）")
    args = parser.parse_args()

    target_date = args.date
    target_ts = pd.Timestamp(target_date)
    window = args.window

    fs_path = resolve_source_parquet("float_shares.parquet")
    if not fs_path.exists():
        print("[FATAL] float_shares.parquet 不存在")
        return 1
    fs_df = pd.read_parquet(fs_path)

    all_stocks = sorted(fs_df["stock_code"].tolist())
    total = len(all_stocks)
    print(f"全市场: {total} 只, 目标日期: {target_date}, 窗口: {window} 天")

    reader = StockDataReader(mode="duckdb_persistent")
    rows = []
    errors = []
    checked = 0

    for s in all_stocks:
        checked += 1
        if checked % 500 == 0:
            print(f"  {checked}/{total} ({checked*100//total}%)")

        ok, msg = reader.validate_freshness(s, target_date, period="1d", adjust_type="front", min_trading_days=window + 1)
        if not ok:
            errors.append(msg)
            continue

        fs_row = fs_df[fs_df["stock_code"] == s]
        float_s = fs_row["float_shares"].values[0]

        df = reader.read_stock(
            s,
            start_time=(target_ts - pd.Timedelta(days=window * 3)).strftime("%Y%m%d"),
            end_time=target_date, period="1d", adjust_type="front",
        )
        df = df.sort_index()
        unique_dates = df.index.normalize().unique()

        if len(unique_dates) < window + 1:
            errors.append(f"{s}: 仅 {len(unique_dates)} 交易日, 需要 {window + 1}")
            continue

        mask = df.index.normalize().isin(unique_dates[-window:])
        df_w = df.loc[mask]

        vol_1d = df_w["volume"].iloc[-1]
        vol_5d = df_w["volume"].tail(5).mean()
        close_now = df_w["close"].iloc[-1]
        boll = compute_bollinger(df_w["close"].values)

        try:
            cross = compute_crossday_turnover_resistance(df, s, window=window)
            as_of_t = pd.Timestamp(unique_dates[-1]).normalize()
            arr = adapt_columns(df_w, stock_code=s, as_of_date=as_of_t)
            cumpdf = daily_chip_distribution(arr, method="triang")
        except Exception:
            errors.append(f"{s}: chip computation failed")
            continue

        if cumpdf.empty or cumpdf.sum() <= 0:
            errors.append(f"{s}: empty cumpdf")
            continue

        p90 = _cost_at_ratio(cumpdf, 0.90)
        p10 = _cost_at_ratio(cumpdf, 0.10)
        resist_abs = round(p90 - close_now, 2) if not np.isnan(p90) else ""
        support_abs = round(close_now - p10, 2) if not np.isnan(p10) else ""

        rows.append({
            "stock_code": s,
            "close": round(close_now, 2),
            "volume_1d_手": int(vol_1d),
            "volume_5d_avg_手": int(vol_5d),
            "turnover_1d": cross["turnover_ratio"],
            "float_shares_亿": round(float_s / 1e8, 2),
            "cyqk_c_today": cross["cyqk_c"],
            "cyqk_c_yesterday": cross["cyqk_c_yesterday"],
            "cyqk_c_diff": cross["profit_chip_diff"],
            "turnover_resist": cross["turnover_resistance"],
            "resist_abs": resist_abs,
            "support_abs": support_abs,
            **boll,
        })

    reader.close()

    print(f"\n有效: {len(rows)}, 跳过/错误: {len(errors)}")
    if not rows:
        print("[FATAL] 无有效数据")
        return 1

    out_df = pd.DataFrame(rows)
    out_path = args.output or str(REPO / "backtest_output" / f"full_market_chip_resist_{target_date}.csv")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"Saved: {out_path} ({len(out_df)} rows, {len(out_df.columns)} cols)")

    valid_resist = pd.to_numeric(out_df["turnover_resist"], errors="coerce").dropna()
    print(f"\nturnover_resist: mean={valid_resist.mean():.4f} median={valid_resist.median():.4f} "
          f"min={valid_resist.min():.4f} max={valid_resist.max():.4f}")
    valid_pct_b = pd.to_numeric(out_df["boll_pct_b"], errors="coerce").dropna()
    print(f"boll_pct_b: mean={valid_pct_b.mean():.4f} median={valid_pct_b.median():.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
