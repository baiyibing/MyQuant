# -*- coding: utf-8 -*-
"""
全市场等权重筹码分布阻力计算 v2（优化版）。

相对 v1 的改进：
  - chip 分布走 canonical 路径（daily_chip_distribution + ChipFactor）
    消除内联 curpdf/cumpdf 重复实现
  - 增加 asr/ckdw/prp/bb_position 输出列
  - 多进程共享 StockDataReader（每进程一份），减少 DuckDB 连接开销
  - 对齐回测 WINDOW_DAYS=80（与 chip_factor_analysis 同口径）

分子 cyqk_T / cyqk_T-1：等权重无衰减，窗口 80 个交易日
分母 turnover：canonical（adapt_columns → arr[-1,4]，含 float_shares_history）
阻力 = (cyqk_T − cyqk_T−1) / turnover_T

用法：
  python scripts/research/full_market_equal_weight_resist_v2.py --date 20260515
  python scripts/research/full_market_equal_weight_resist_v2.py --date 20260515 --window 120
"""

from myquant_factors._runtime import research_root, resolve_source_parquet

import argparse
import os
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any

sys.path.insert(0, str(research_root()))

import numpy as np
import pandas as pd

from myquant_factors._runtime import resolve_source_parquet
from myquant_factors.compat_chip import (
    adapt_columns, bb_position, daily_chip_distribution, _get_float_shares, cyq,
)
from myquant_factors._runtime import StockDataReader

# 默认参数
WINDOW_DAYS: int = 120
OUTPUT_DIR: str = "backtest_output"


def _calc_one(args) -> Optional[Dict[str, Any]]:
    """单只股票截面计算（canonical 路径：adapt_columns → daily_chip_distribution → ChipFactor → derived）。"""
    code, target, target_prev, window = args
    reader = StockDataReader()
    try:
        df = reader.read_stock(code, period="1d", adjust_type="front")
    except Exception:
        return None
    if df is None or df.empty:
        return None

    df = df.rename(columns={"time": "datetime"})
    df["datetime"] = pd.to_datetime(df["datetime"], unit="ms")
    df.set_index("datetime", inplace=True)
    df = df.sort_index()

    as_of_t = pd.Timestamp(target).normalize()
    as_of_y = pd.Timestamp(target_prev).normalize()

    df_t = df[df.index.normalize() <= as_of_t]
    df_prev = df[df.index.normalize() <= as_of_y]
    if len(df_t) < window or len(df_prev) < window:
        return None

    win_t = df_t.tail(window)
    win_y = df_prev.tail(window)

    # ── canonical 路径 ──
    try:
        arr_t = adapt_columns(win_t.copy(), stock_code=code, as_of_date=as_of_t)
        arr_y = adapt_columns(win_y.copy(), stock_code=code, as_of_date=as_of_y)
    except Exception:
        return None

    dist_t = daily_chip_distribution(arr_t, method="triang")
    dist_y = daily_chip_distribution(arr_y, method="triang")

    close_t = float(arr_t[-1, 0])
    cf_t = cyq.ChipFactor(close_t, dist_t)
    cf_y = cyq.ChipFactor(float(arr_y[-1, 0]), dist_y)

    cyqk_t = cf_t.get_cyqk_c()
    cyqk_y = cf_y.get_cyqk_c()
    if np.isnan(cyqk_t) or np.isnan(cyqk_y):
        return None

    profit_chip_diff = cyqk_t - cyqk_y
    turnover_t = float(arr_t[-1, 4])

    if turnover_t > 0:
        turnover_resistance = profit_chip_diff / turnover_t
    else:
        turnover_resistance = 0.0

    bb = bb_position(win_t["close"].values)

    return {
        "stock_code": code,
        "date": target.strftime("%Y%m%d"),
        "close": round(close_t, 2),
        "cyqk_T": round(cyqk_t, 4),
        "cyqk_T_1": round(cyqk_y, 4),
        "profit_chip_diff": round(profit_chip_diff, 6),
        "turnover": round(turnover_t, 6),
        "turnover_resistance": round(turnover_resistance, 4),
        "abs_resist": round(abs(turnover_resistance), 4),
        "bb_position": round(bb, 4),
        "asr": round(cf_t.get_asr(), 4),
        "ckdw": round(cf_t.get_ckdw(), 4),
        "prp": round(cf_t.get_prp(), 4),
    }


def run(date_str: str, output: str, window: int = WINDOW_DAYS, workers: int = 6,
        stocks: Optional[List[str]] = None):
    target = pd.Timestamp(date_str)
    target_prev = target - pd.Timedelta(days=1)

    if stocks:
        codes = stocks
        use_pool = len(codes) > 10
    else:
        fs_path = resolve_source_parquet("float_shares.parquet")
        if not fs_path.exists():
            raise FileNotFoundError(f"{fs_path} not found; supply float_shares data through MyQuant-infra first")
        fs_df = pd.read_parquet(fs_path)
        codes = sorted(fs_df["stock_code"].dropna().unique().tolist())
        use_pool = True

    n_total = len(codes)
    print(f"Total stocks: {n_total}  date: {date_str}  window: {window}  workers: {workers}")
    if stocks:
        print(f"  stocks: {stocks}")

    task_args = [(c, target, target_prev, window) for c in codes]
    results: List[Dict[str, Any]] = []
    n_done = 0

    if use_pool:
        from multiprocessing import Pool
        with Pool(processes=min(workers, n_total)) as pool:
            for res in pool.imap_unordered(_calc_one, task_args, chunksize=max(1, n_total // workers)):
                n_done += 1
                if n_done % max(1, n_total // 10) == 0:
                    print(f"  processed {n_done}/{n_total}\tvalid={len(results)}"
                          f"\t({n_done * 100 // n_total}%)")
                if res is not None:
                    results.append(res)
    else:
        for args_tuple in task_args:
            n_done += 1
            res = _calc_one(args_tuple)
            print(f"  {args_tuple[0]}: {'OK' if res else 'SKIP'}"
                  f"\tcyqk_T={res['cyqk_T'] if res else 'N/A'}")
            if res is not None:
                results.append(res)

    if not results:
        print("WARNING: No valid results.")
        return

    out_df = pd.DataFrame(results)
    out_df = out_df.sort_values("abs_resist", ascending=False)

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")

    skipped = n_total - len(out_df)
    n_positive = int((out_df["turnover_resistance"] > 0).sum())
    n_negative = int((out_df["turnover_resistance"] < 0).sum())
    print(f"\nOutput: {out_path}  rows={len(out_df)}  skipped={skipped}")
    print(f"  positive={n_positive}  negative={n_negative}  zero={len(out_df) - n_positive - n_negative}")
    print(f"\nTop 20 by |resistance|:")
    cols_show = ["stock_code", "close", "cyqk_T", "cyqk_T_1",
                 "profit_chip_diff", "turnover", "turnover_resistance",
                 "abs_resist", "bb_position", "asr"]
    print(out_df[cols_show].head(20).to_string(index=False))


def main():
    parser = argparse.ArgumentParser(description="全市场等权重筹码阻力 v2")
    parser.add_argument("--date", default="20260515", help="截面日 YYYYMMDD")
    parser.add_argument("--window", type=int, default=WINDOW_DAYS, help="筹码窗口（交易日）")
    parser.add_argument("--workers", type=int, default=6, help="并行进程数")
    parser.add_argument("--output", default=None, help="输出 CSV 路径（默认 backtest_output/equal_weight_resist_v2_{date}.csv）")
    parser.add_argument("--stocks", default=None, help="指定股票代码，逗号分隔（如 300834.SZ,600000.SH）")
    args = parser.parse_args()

    stock_list = None
    if args.stocks:
        stock_list = [s.strip() for s in args.stocks.split(",") if s.strip()]

    if args.output is None:
        tag = f"_{stock_list[0]}" if stock_list and len(stock_list) == 1 else ""
        args.output = f"{OUTPUT_DIR}/equal_weight_resist_v2_{args.date}{tag}.csv"

    run(args.date, args.output, args.window, args.workers, stocks=stock_list)


if __name__ == "__main__":
    raise SystemExit(main())
