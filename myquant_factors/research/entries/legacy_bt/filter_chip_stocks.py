#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
filter_chip_stocks.py — 按 chip 因子条件筛选全市场股票

用法：
    # 单日筛选
    python backtest/research/filter_chip_stocks.py --date 2026-03-01

    # 日期区间（每个交易日输出一次）
    python backtest/research/filter_chip_stocks.py --start 2026-03-10 --end 2026-05-14

    # 自定义阈值 + 仅正值
    python backtest/research/filter_chip_stocks.py --start 2026-03-10 --end 2026-05-14 --resist 15 --positive

输出：
    屏幕打印 + backtest_output/chip_filter_{start}_{end}.csv
"""

from myquant_factors._runtime import research_root, resolve_source_parquet

import argparse
import os
import sys
import numpy as np
import pandas as pd

REPO = str(research_root())
sys.path.insert(0, REPO)

from myquant_factors.compat_chip import (
    adapt_columns, bb_position, daily_chip_distribution, derived_chip_factors, cyq,
)
from myquant_factors._runtime import resolve_period_root, resolve_source_parquet
from myquant_factors._runtime import StockDataReader

FLOAT_SHARES_PATH = str(resolve_source_parquet("float_shares.parquet"))
OUTPUT_DIR = os.path.join(REPO, "backtest_output")
WINDOW_DAYS = 80
FLOAT_SHARES_COVERAGE_THRESHOLD = 0.95


def _load_all_market_codes() -> list:
    """从日线 front 目录扫描全市场代码。"""
    front_dir = str(resolve_period_root("1d") / "dividend_type=front")
    codes = []
    if os.path.exists(front_dir):
        for d in os.listdir(front_dir):
            if d.startswith("symbol="):
                code = d[len("symbol="):].replace("_", ".")
                codes.append(code)
    return sorted(codes)

_reader = None

def _get_reader():
    global _reader
    if _reader is None:
        _reader = StockDataReader()
    return _reader


def _load_and_filter(code: str, tdays, date_str: str, min_abs_resist, min_bb, positive_only,
                     reader=None):
    """单只标的在指定日期的筛选计算。"""
    if reader is None:
        reader = _get_reader()
    start_ts = pd.Timestamp(date_str)
    df = reader.read_stock(code, start_time='20000101', end_time=date_str,
                           period='1d', adjust_type='front')
    if df is None or len(df) < WINDOW_DAYS + 2:
        return None
    df["dt"] = pd.to_datetime(df["time"], unit="ms")
    df = df[df["dt"].dt.normalize().isin(tdays.normalize())]
    df.set_index("dt", inplace=True)

    pre = df[df.index < start_ts]
    post = df[df.index >= start_ts]
    if len(pre) < WINDOW_DAYS or len(post) < 2:
        return None

    today_end = post.index[0]
    today_win = df[df.index <= today_end].tail(WINDOW_DAYS)
    as_of_t = pd.Timestamp(today_end).normalize()
    arr_t = adapt_columns(today_win, stock_code=code, as_of_date=as_of_t)
    dist_t = daily_chip_distribution(arr_t, method="triang")
    cf_t = cyq.ChipFactor(float(arr_t[-1, 0]), dist_t)

    yest_win = pre.tail(WINDOW_DAYS)
    as_of_y = pd.Timestamp(yest_win.index[-1]).normalize()
    arr_y = adapt_columns(yest_win, stock_code=code, as_of_date=as_of_y)
    dist_y = daily_chip_distribution(arr_y, method="triang")
    cf_y = cyq.ChipFactor(float(arr_y[-1, 0]), dist_y)

    derived = derived_chip_factors(
        cf_t.get_cyqk_c(), cf_y.get_cyqk_c(), float(arr_t[-1, 4]))
    bb = bb_position(today_win["close"].values)
    resist = derived["turnover_resistance"]

    if positive_only and resist <= 0:
        return None
    cyqk_today = round(cf_t.get_cyqk_c(), 4)
    cyqk_yesterday = round(cf_y.get_cyqk_c(), 4)
    turnover = round(float(arr_t[-1, 4]), 4)
    if abs(resist) > min_abs_resist and bb >= min_bb:
        return {
            "date": date_str,
            "code": code,
            "close": round(float(arr_t[-1, 0]), 2),
            "resist": round(resist, 1),
            "abs_resist": round(abs(resist), 1),
            "cyqk_today": cyqk_today,
            "cyqk_yesterday": cyqk_yesterday,
            "turnover_ratio": turnover,
            "bb_position": round(bb, 3),
            "cyqk_c": cyqk_today,
            "asr": round(cf_t.get_asr(), 4),
        }
    return None


def main():
    parser = argparse.ArgumentParser(description="chip 因子全市场筛选")
    parser.add_argument("--resist", type=float, default=20.0,
                        help="阻力绝对值阈值（默认 20）")
    parser.add_argument("--bb", type=float, default=0.5,
                        help="BB 中轨位置阈值（默认 0.5）")
    parser.add_argument("--date", default=None,
                        help="单日筛选日期 YYYY-MM-DD")
    parser.add_argument("--start", default=None,
                        help="区间起始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None,
                        help="区间结束日期 YYYY-MM-DD")
    parser.add_argument("--positive", action="store_true",
                        help="仅保留阻力 > 0（正值）")
    args = parser.parse_args()

    import pandas_market_calendars as mcal

    cal = mcal.get_calendar("SSE")
    tdays = cal.schedule(start_date="2024-01-01", end_date="2026-12-31").index

    # 确定日期范围
    if args.start and args.end:
        dates = tdays[(tdays >= pd.Timestamp(args.start))
                      & (tdays <= pd.Timestamp(args.end))]
        dates = [d.strftime("%Y-%m-%d") for d in dates]
    elif args.date:
        dates = [args.date]
    else:
        dates = ["2026-03-01"]

    print(f"筛选条件: |阻力|> {args.resist} & BB >= {args.bb}")
    if args.positive:
        print(f"  仅保留阻力 > 0")
    print(f"日期范围: {dates[0]} ~ {dates[-1]} ({len(dates)} 个交易日)")
    print()

    # P0-2 fix: 从全市场 front 目录扫描代码，而非仅 float_shares.parquet
    market_codes = _load_all_market_codes()
    if not market_codes:
        print("[ERROR] 无法从 front 目录扫描到任何股票代码")
        sys.exit(1)

    # float_shares 覆盖度检查
    if not os.path.exists(FLOAT_SHARES_PATH):
        print(f"[ERROR] float_shares 文件不存在: {FLOAT_SHARES_PATH}")
        print("请先运行: python oskh_data/float_shares.py")
        sys.exit(1)

    fs_df = pd.read_parquet(FLOAT_SHARES_PATH)
    valid_fs_codes = set(fs_df.loc[fs_df["float_shares"] > 0, "stock_code"].tolist())
    coverage = len(valid_fs_codes) / len(market_codes) if market_codes else 0
    print(f"float_shares 有效覆盖: {len(valid_fs_codes)}/{len(market_codes)} = {coverage:.2%}")

    if coverage < FLOAT_SHARES_COVERAGE_THRESHOLD:
        print(f"[ERROR] float_shares coverage {coverage:.2%} < {FLOAT_SHARES_COVERAGE_THRESHOLD:.0%}")
        print("请先运行: python oskh_data/float_shares.py")
        sys.exit(1)

    # 只遍历有有效 float_shares 且存在日线数据的股票
    fs_codes = sorted(valid_fs_codes & set(market_codes))
    print(f"实际筛选: {len(fs_codes)} 只（float_shares 有效 ∩ 有日线数据）")
    print()

    reader = _get_reader()
    all_results = []

    for date_str in dates:
        for code in fs_codes:
            r = _load_and_filter(
                code, tdays, date_str,
                min_abs_resist=args.resist,
                min_bb=args.bb,
                positive_only=args.positive,
                reader=reader,
            )
            if r:
                all_results.append(r)
    reader.close()

    if not all_results:
        print("无符合条件股票")
        return

    df = pd.DataFrame(all_results)
    # 同一天同一股票只保留一次
    df = df.drop_duplicates(subset=["date", "code"])
    df = df.sort_values(["date", "abs_resist"], ascending=[True, False])

    # 每日统计
    daily_counts = df.groupby("date").size()
    print(f"总记录: {len(df)}, 覆盖 {len(daily_counts)} 个交易日, "
          f"平均每日 {daily_counts.mean():.0f} 只")

    # 输出样例
    if len(dates) == 1:
        print()
        print(f"  {'code':<14} {'close':>8} {'|阻力|':>10} {'阻力':>10} {'BB':>8} "
              f"{'赢筹今':>8} {'赢筹昨':>8} {'换手率':>8}")
        for _, r in df.head(20).iterrows():
            print(f"  {r.code:<14} {r.close:8.2f} {r.abs_resist:10.1f} "
                  f"{r.resist:+10.1f} {r.bb_position:8.3f} "
                  f"{r.cyqk_today:8.4f} {r.cyqk_yesterday:8.4f} {r.turnover_ratio:8.4f}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    tag = dates[0].replace("-", "") + "_" + dates[-1].replace("-", "")
    out = os.path.join(OUTPUT_DIR, f"chip_filter_{tag}.csv")
    df.to_csv(out, index=False)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
