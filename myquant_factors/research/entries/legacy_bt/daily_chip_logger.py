#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
daily_chip_logger.py — 每日 chip 因子截面日志（纸盘观测用）

读取当日 stock_pool + 日线 parquet 缓存，计算每只标的的 8 个 chip 因子（CYQ + 换手率半衰期），
输出截面 CSV 到 backtest_output/。不改动任何交易策略代码。

用法：
    # 默认使用最新 stock_pool CSV
    python backtest/research/daily_chip_logger.py

    # 指定日期
    python backtest/research/daily_chip_logger.py --date 20260513

    # 分钟线模式
    python backtest/research/daily_chip_logger.py --date 20260513 --freq 1m

    # 自动定时：每天 15:30 执行一次
    python backtest/research/daily_chip_logger.py --schedule

输出：
    backtest_output/chip_daily_{date}.csv  — 当日截面（含 cyqk、turnover_ratio、turnover_resistance 等）

可以配合定时任务（cron / Windows Task Scheduler / Claude scheduled tasks）
在每天收盘后自动生成，供盘后复盘和次日选股参考。
"""

from myquant_factors._runtime import research_root, resolve_source_parquet

import argparse
import os
import sys
import time
from datetime import datetime, date

import numpy as np
import pandas as pd

REPO = str(research_root())
sys.path.insert(0, REPO)

from myquant_factors.compat_chip import (
    adapt_columns,
    daily_chip_distribution,
    minute_chip_distribution,
    turnover_chip_factors,
    derived_chip_factors,
    cyq,
)
from myquant_factors._runtime import parse_pool_csv
from myquant_factors._runtime import StockDataReader

OUTPUT_DIR = os.path.join(REPO, "backtest_output")
STOCK_POOL_DIR = os.path.join(REPO, "stock_pool")
WINDOW_DAYS = 80

_reader = None

def _get_reader():
    global _reader
    if _reader is None:
        _reader = StockDataReader()
    return _reader


def load_stock_pool(date_str: str) -> list:
    """从 stock_pool CSV 读取标的列表。"""
    path = os.path.join(STOCK_POOL_DIR, f"{date_str}.csv")
    if not os.path.exists(path):
        return []
    return parse_pool_csv(path)


def compute_factors(code: str, freq: str = "1d", reader=None) -> dict:
    """计算单只标的的 chip 因子。"""
    if reader is None:
        reader = _get_reader()
    df = reader.read_stock(code, period=freq, adjust_type='none')
    if df is None or len(df) < WINDOW_DAYS:
        return None

    if freq == "1m":
        df["dt"] = pd.to_datetime(df["time"], unit="ms")
        dates = sorted(df["dt"].dt.date.unique())
        if len(dates) < WINDOW_DAYS:
            return None
        df = df[df["dt"].dt.date >= dates[-WINDOW_DAYS]]

    # 多取 1 根 bar 用于昨日因子计算
    df_w = df.tail(WINDOW_DAYS + 1) if freq == "1d" else df
    if len(df_w) < WINDOW_DAYS:
        return None

    try:
        # 今日因子：最近 WINDOW_DAYS 根
        df_today = df_w.tail(WINDOW_DAYS)
        as_of_t = pd.Timestamp(df_today.index[-1]).normalize()
        arr_today = adapt_columns(df_today, stock_code=code, as_of_date=as_of_t)
        if freq == "1m":
            dist_today = minute_chip_distribution(arr_today)
        else:
            dist_today = daily_chip_distribution(arr_today, method="triang")

        close_price = float(arr_today[-1, 0])
        cf = cyq.ChipFactor(close_price, dist_today)
        # Phase 2: 换手率半衰期因子
        tr_arr = arr_today[:, 4]
        cl_arr = arr_today[:, 0]
        tcf = turnover_chip_factors(tr_arr, cl_arr, window=min(60, len(tr_arr)))

        # 昨日因子：前 WINDOW_DAYS 根
        cyqk_yesterday = np.nan
        try:
            df_yesterday = df_w.head(WINDOW_DAYS)
            as_of_y = pd.Timestamp(df_yesterday.index[-1]).normalize()
            arr_y = adapt_columns(df_yesterday, stock_code=code, as_of_date=as_of_y)
            dist_y = daily_chip_distribution(arr_y, method="triang")
            ct_y = float(arr_y[-1, 0])
            cf_y = cyq.ChipFactor(ct_y, dist_y)
            cyqk_yesterday = cf_y.get_cyqk_c()
        except Exception:
            pass

        turnover_today = float(arr_today[-1, 4])
        derived = derived_chip_factors(
            cf.get_cyqk_c(), cyqk_yesterday, turnover_today,
        )

        return {
            "stock_code": code,
            "close": close_price,
            "cyqk_c": cf.get_cyqk_c(),
            "asr": cf.get_asr(),
            "ckdw": cf.get_ckdw(),
            "prp": cf.get_prp(),
            "arc": tcf["arc"],
            "vrc": tcf["vrc"],
            "src": tcf["src"],
            "krc": tcf["krc"],
            "profit_chip_diff": derived["profit_chip_diff"],
            "turnover_ratio": derived["turnover_ratio"],
            "turnover_resistance": derived["turnover_resistance"],
            "turnover_mean": float(arr_today[:, 4].mean()),
        }
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="每日 chip 因子截面日志")
    parser.add_argument("--date", help="stock_pool 日期 YYYYMMDD，默认最新")
    parser.add_argument("--freq", default="1d", choices=["1d", "1m"])
    parser.add_argument("--schedule", action="store_true", help="每 10 分钟检查一次，15:30 执行后退出")
    args = parser.parse_args()

    if args.schedule:
        print(f"[{datetime.now():%H:%M:%S}] daily_chip_logger --schedule started, "
              f"waiting for 15:30 ...")
        while True:
            now = datetime.now()
            if now.hour >= 15 and now.minute >= 30:
                break
            time.sleep(60)
        print(f"[{now:%H:%M:%S}] Triggering daily chip factor log ...")

    # 确定 stock pool 日期
    if args.date:
        date_str = args.date
    else:
        csv_files = sorted(
            [f for f in os.listdir(STOCK_POOL_DIR) if f.endswith(".csv")],
            reverse=True,
        )
        date_str = csv_files[0].replace(".csv", "") if csv_files else datetime.now().strftime("%Y%m%d")

    stock_list = load_stock_pool(date_str)
    if not stock_list:
        print(f"[WARN] No stocks in stock_pool for {date_str}")
        return

    print(f"[{datetime.now():%H:%M:%S}] Computing chip factors for {len(stock_list)} stocks "
          f"({args.freq}, pool={date_str}) ...")

    reader = _get_reader()
    results = []
    ok = 0
    skip = 0
    for code in stock_list:
        r = compute_factors(code, freq=args.freq, reader=reader)
        if r:
            results.append(r)
            ok += 1
        else:
            skip += 1

    if not results:
        print("[WARN] No chip factors computed")
        return

    df = pd.DataFrame(results).sort_values("cyqk_c", ascending=False)

    # 标记高低位
    df["signal"] = df["cyqk_c"].apply(
        lambda x: "HIGH" if x > 0.8 else ("LOW" if x < 0.2 else "")
    )

    # 输出
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    freq_suffix = f"_{args.freq}" if args.freq != "1d" else ""
    out_path = os.path.join(OUTPUT_DIR, f"chip_daily_{date_str}{freq_suffix}.csv")
    df.to_csv(out_path, index=False)

    # 摘要
    high_count = (df["cyqk_c"] > 0.8).sum()
    low_count = (df["cyqk_c"] < 0.2).sum()
    reader.close()

    print(f"  Done: {ok} OK, {skip} skipped → {out_path}")
    print(f"  cyqk_c: median={df['cyqk_c'].median():.3f}  "
          f"HIGH(>0.8)={high_count}  LOW(<0.2)={low_count}")
    print(f"  arc: median={df['arc'].median():+.4f}  vrc: median={df['vrc'].median():.4f}  "
          f"src: median={df['src'].median():+.3f}  krc: median={df['krc'].median():.2f}")

    if high_count > 0:
        print(f"  HIGH stocks: {', '.join(df[df.cyqk_c > 0.8].stock_code.head(10))}")
    if low_count > 0:
        print(f"  LOW  stocks: {', '.join(df[df.cyqk_c < 0.2].stock_code.head(10))}")


if __name__ == "__main__":
    main()
