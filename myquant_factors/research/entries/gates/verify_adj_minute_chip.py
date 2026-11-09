from typing import Any, cast


from myquant_factors._runtime import research_root, resolve_source_parquet
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
verify_adj_minute_chip.py — 验证方案 B 复权校正分钟线筹码分布

对比三条路径的芯片因子输出：
- 日线前复权（ground truth）
- 分钟线未复权（方案 A）
- 分钟线复权校正（方案 B，新增）

预期：方案 B 应比方案 A 更接近日线前复权。

用法：
    python backtest/verify_adj_minute_chip.py
"""

import os
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from scipy.stats import pearsonr

REPO = str(research_root())
sys.path.insert(0, REPO)

from myquant_factors.chip.core import (
    adapt_columns,
    daily_chip_distribution,
    adj_minute_chip_distribution,
    minute_chip_distribution,
)
from myquant_factors import cyq
from myquant_factors._runtime import StockDataReader
from myquant_factors._runtime import resolve_period_root

from myquant_factors._runtime import resolve_parquet_container, resolve_period_root

MINUTE_DIR = str(resolve_period_root("1m") / "dividend_type=none")
WINDOW = 80

_reader = None

def _get_reader():
    global _reader
    if _reader is None:
        _reader = StockDataReader()
    return _reader
DATE_STR = "2026-05-13"


def _pick_stocks(n: int) -> list:
    """一次查询 adj_factor 表，找偏离最大的 stock + 验证因子可用。"""
    from myquant_factors._runtime import resolve_source_parquet

    af = pd.read_parquet(resolve_source_parquet("adj_factor.parquet"))
    # P1-2: NaN 因子行统计
    nan_count = int(af["cumulative_adj_factor"].isna().sum())
    total_count = len(af)
    if nan_count > 0:
        nan_stocks = af[af["cumulative_adj_factor"].isna()]["stock_code"].nunique()
        print(f"[WARN] adj_factor 表中 {nan_count}/{total_count} 行因子为 NaN, 涉及 {nan_stocks} 只标的")

    day = af[af["date"] == DATE_STR].copy()
    day["deviation"] = abs(day["cumulative_adj_factor"] - 1.0)
    top = cast(Any, day).nlargest(min(n * 3, len(day)), "deviation")

    # 验证分钟数据存在
    candidates = []
    for _, row in top.iterrows():
        code = row["stock_code"]
        sym = code.replace(".", "_")
        if os.path.exists(os.path.join(MINUTE_DIR, f"symbol={sym}", "data.parquet")):
            candidates.append((code, row["cumulative_adj_factor"]))
            if len(candidates) >= n:
                break
    return candidates


def main():
    print(f"截面日期: {DATE_STR}")
    stocks = _pick_stocks(10)
    print(f"选取 adj_factor 偏离最大的 {len(stocks)} 只标的\n")

    reader = _get_reader()
    records = []
    for code, adj_factor in stocks:
        df_d = reader.read_stock(code, period='1d', adjust_type='front')
        if df_d is None:
            continue
        df_d["dt"] = pd.to_datetime(df_d["time"], unit="ms")
        df_d = df_d[df_d["dt"].dt.normalize() <= pd.Timestamp(DATE_STR)]
        df_d = cast(Any, df_d).sort_values("dt").tail(WINDOW)
        if len(df_d) < WINDOW:
            continue

        df_m = reader.read_stock(code, period='1m', adjust_type='none')
        if df_m is None:
            continue
        df_m["dt"] = pd.to_datetime(df_m["time"], unit="ms")
        tdates = sorted(df_d["dt"].dt.normalize().unique())
        if len(tdates) < WINDOW:
            continue
        df_m_win = df_m[df_m["dt"].dt.normalize().isin(tdates[-WINDOW:])]
        if len(df_m_win) < 100:
            continue

        try:
            arr_d = adapt_columns(cast(Any, df_d), stock_code=code)
            dist_d = daily_chip_distribution(arr_d, method="triang")
            cf_d = cyq.ChipFactor(float(arr_d[-1, 0]), dist_d)

            arr_m = adapt_columns(cast(Any, df_m_win), stock_code=code)
            dist_a = minute_chip_distribution(arr_m)
            cf_a = cyq.ChipFactor(float(arr_m[-1, 0]), dist_a)

            dist_b = adj_minute_chip_distribution(arr_m, code, DATE_STR)
            cf_b = cyq.ChipFactor(float(arr_m[-1, 0]) * adj_factor, dist_b)
        except Exception as e:
            print(f"  {code}: ERROR {e}")
            continue

        print(f"  {code}: adj={adj_factor:.4f}, "
              f"cyqk_d={cf_d.get_cyqk_c():.3f}, "
              f"cyqk_a={cf_a.get_cyqk_c():.3f}, "
              f"cyqk_b={cf_b.get_cyqk_c():.3f}")

        records.append({
            "code": code, "adj_factor": round(adj_factor, 4),
            "d_cyqk_c": cf_d.get_cyqk_c(), "a_cyqk_c": cf_a.get_cyqk_c(), "b_cyqk_c": cf_b.get_cyqk_c(),
            "d_asr": cf_d.get_asr(), "a_asr": cf_a.get_asr(), "b_asr": cf_b.get_asr(),
            "d_prp": cf_d.get_prp(), "a_prp": cf_a.get_prp(), "b_prp": cf_b.get_prp(),
        })

    if len(records) < 3:
        print("\n数据不足")
        return

    df = pd.DataFrame(records)
    print(f"\n有效标的: {len(df)}")
    print(f"adj_factor 范围: [{df['adj_factor'].min():.4f}, {df['adj_factor'].max():.4f}]\n")

    print(f"{'='*75}")
    print("日线前复权 vs 方案A(分钟未复权) vs 方案B(分钟复权校正)")
    print(f"{'='*75}")
    print(f"{'因子':<10} {'日线vsA r':>10} {'日线vsA MAE':>12} "
          f"{'日线vsB r':>10} {'日线vsB MAE':>12} {'B更优?':>8}")
    print("-" * 65)

    for f in ["cyqk_c", "asr", "prp"]:
        d_col, a_col, b_col = f"d_{f}", f"a_{f}", f"b_{f}"
        valid = df[[d_col, a_col, b_col]].dropna()

        r_da, _ = pearsonr(valid[d_col], valid[a_col])
        r_db, _ = pearsonr(valid[d_col], valid[b_col])
        mae_da = np.mean(cast(Any, np.abs(valid[d_col] - valid[a_col])))
        mae_db = np.mean(cast(Any, np.abs(valid[d_col] - valid[b_col])))
        better = "✅" if (mae_db < mae_da) else "—"
        print(f"{f:<10} {r_da:10.4f} {mae_da:12.4f} "
              f"{r_db:10.4f} {mae_db:12.4f} {better:>8}")

    reader.close()


if __name__ == "__main__":
    main()
