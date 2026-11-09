# -*- coding: utf-8 -*-
"""
全市场等权重筹码分布阻力计算（招商算法风格）。

分子 cyqk_T / cyqk_T-1：等权重无衰减，窗口 120 个交易日
分母 turnover：canonical（vol×100 / float_shares_history as_of=T）
阻力 = (cyqk_T − cyqk_T−1) / turnover_T

输出：按 |turnover_resistance| 降序排列的 CSV
"""

from myquant_factors._runtime import research_root, resolve_source_parquet

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(research_root()))

import numpy as np
import pandas as pd

from myquant_factors._runtime import resolve_source_parquet
import myquant_factors._runtime as reader
from myquant_factors.compat_chip import adapt_columns, _get_float_shares
from myquant_factors import cyq
from myquant_factors.distribution_of_chips import make_price_grid


def _calc_equal_weight_cyqk(df: pd.DataFrame, stock_code: str, window: int = 120) -> float:
    """内联等权重 cyqk 计算。"""
    if df is None or df.empty:
        return float("nan")

    df = df.sort_index()
    unique_dates = df.index.normalize().unique()
    if len(unique_dates) < window:
        return float("nan")

    as_of = pd.Timestamp(unique_dates[-1]).normalize()
    win_dates = unique_dates[-window:]
    mask = df.index.normalize().isin(win_dates)
    df_w = df.loc[mask]

    try:
        arr = adapt_columns(df_w, stock_code=stock_code, as_of_date=as_of)
    except Exception:
        return float("nan")

    close = float(arr[-1, 0])
    max_p = float(np.nanmax(arr[:, 1]))
    min_p = float(np.nanmin(arr[:, 2]))
    step = 0.01
    if max_p <= min_p:
        return float("nan")

    xs = make_price_grid(min_p, max_p, step)
    curpdfs = np.zeros((len(arr), len(xs)))
    for i in range(len(arr)):
        row = arr[i]
        pdf = cyq.calc_curpdf(row[0], row[1], row[2], row[3], min_p, max_p, step, "triang")
        curpdfs[i] = pdf

    cum_vol = np.sum(curpdfs, axis=0)
    dist = pd.Series(cum_vol, index=xs, name="cumpdf")
    cf = cyq.ChipFactor(close, dist)
    return cf.get_cyqk_c()


def _process_one(args):
    """多进程 worker：处理单只股票。"""
    code, target, target_prev, window = args
    try:
        r = reader.StockDataReader()
        df = r.read_stock(code, period="1d", adjust_type="front")
        if df is None or df.empty:
            return None

        df = df.rename(columns={"time": "datetime"})
        df["datetime"] = pd.to_datetime(df["datetime"], unit="ms")
        df.set_index("datetime", inplace=True)
        df = df.sort_index()

        df_t = df[df.index.normalize() <= target]
        df_prev = df[df.index.normalize() <= target_prev]
        if df_t.empty or df_prev.empty:
            return None

        cyqk_t = _calc_equal_weight_cyqk(df_t, code, window=window)
        cyqk_prev = _calc_equal_weight_cyqk(df_prev, code, window=window)

        if np.isnan(cyqk_t) or np.isnan(cyqk_prev):
            return None

        profit_chip_diff = cyqk_t - cyqk_prev

        try:
            arr_t = adapt_columns(df_t.tail(window), stock_code=code, as_of_date=target)
            turnover_t = float(arr_t[-1, 4])
        except Exception:
            return None

        if turnover_t > 0:
            turnover_resistance = profit_chip_diff / turnover_t
        else:
            turnover_resistance = 0.0

        close_t = float(df_t["close"].iloc[-1])

        return {
            "stock_code": code,
            "date": target.strftime("%Y%m%d"),
            "close": close_t,
            "cyqk_T": round(cyqk_t, 4),
            "cyqk_T_1": round(cyqk_prev, 4),
            "profit_chip_diff": round(profit_chip_diff, 6),
            "turnover": round(turnover_t, 6),
            "turnover_resistance": round(turnover_resistance, 4),
        }
    except Exception:
        return None


def run(date_str: str, output: str, window: int = 120, workers: int = 6):
    from multiprocessing import Pool

    target = pd.Timestamp(date_str)
    target_prev = target - pd.Timedelta(days=1)

    fs_path = resolve_source_parquet("float_shares.parquet")
    if not fs_path.exists():
        raise FileNotFoundError(f"{fs_path} not found")

    fs_df = pd.read_parquet(fs_path)
    codes = fs_df["stock_code"].dropna().unique().tolist()
    print(f"Total stocks: {len(codes)}  target: {date_str}  window: {window}  workers: {workers}")

    task_args = [(c, target, target_prev, window) for c in codes]

    results = []
    with Pool(processes=workers) as pool:
        for i, res in enumerate(pool.imap_unordered(_process_one, task_args, chunksize=20)):
            if i % 500 == 0 and i > 0:
                print(f"  processed {i}/{len(codes)}  valid={len(results)}")
            if res is not None:
                results.append(res)

    if not results:
        print("No valid results")
        return

    out_df = pd.DataFrame(results)
    out_df["abs_resist"] = out_df["turnover_resistance"].abs()
    out_df = out_df.sort_values("abs_resist", ascending=False)
    out_df = out_df.drop(columns=["abs_resist"])

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nOutput: {out_path}  rows={len(out_df)}  skipped={len(codes)-len(out_df)}")
    print(f"\nTop 20 by |resistance|:")
    print(out_df.head(20).to_string(index=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="20260522", help="截面日 YYYYMMDD")
    parser.add_argument("--window", type=int, default=120, help="等权重筹码窗口（交易日）")
    parser.add_argument("--workers", type=int, default=6, help="并行进程数")
    parser.add_argument("--output", default="backtest_output/equal_weight_resist_20260522.csv")
    args = parser.parse_args()
    run(args.date, args.output, args.window, args.workers)


if __name__ == "__main__":
    raise SystemExit(main())
