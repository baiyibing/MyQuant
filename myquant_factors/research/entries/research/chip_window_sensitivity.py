#!/usr/bin/env python3
"""赢筹率窗口长度敏感性分析。

选取配置规定的代表性样本，对 60/80/100/120 天窗口分别计算 cyqk_c，
输出窗口长度对赢筹值的影响幅度。

用法：
    D:/anaconda3/envs/vanna312/python.exe scripts/research/chip_window_sensitivity.py
    D:/anaconda3/envs/vanna312/python.exe scripts/research/chip_window_sensitivity.py --dates 3
"""
from __future__ import annotations

from myquant_factors._runtime import research_root, resolve_source_parquet

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm

_REPO = research_root()
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
from myquant_factors._runtime import ensure_repo_on_syspath

REPO = research_root()

from myquant_factors._runtime import StockDataReader
from myquant_factors.compat_chip import compute_chip_factors


# ── 样本选取（大盘/中盘/小盘/高波动/低波动）──
# 基于 float_shares 和常见认知选取
SAMPLE_STOCKS = {
    "large_cap": [
        "000001.SZ",  # 平安银行
        "600519.SH",  # 贵州茅台
        "000858.SZ",  # 五粮液
        "601318.SH",  # 中国平安
    ],
    "mid_cap": [
        "002475.SZ",  # 立讯精密
        "600809.SH",  # 山西汾酒
        "000725.SZ",  # 京东方A
        "601012.SH",  # 隆基绿能
    ],
    "small_cap": [
        "002759.SZ",  # 天际股份
        "300750.SZ",  # 宁德时代(小盘成长代表)
        "603259.SH",  # 药明康德
        "688111.SH",  # 金山办公
    ],
    "high_volatility": [
        "300803.SZ",  # 指南针
        "002432.SZ",  # 九安医疗
        "603083.SH",  # 剑桥科技
        "688256.SH",  # 寒武纪
    ],
    "low_volatility": [
        "600900.SH",  # 长江电力
        "601288.SH",  # 农业银行
        "600036.SH",  # 招商银行
        "601857.SH",  # 中国石油
    ],
}

WINDOWS = [60, 80, 100, 120]
DEFAULT_DATES = 3
DEFAULT_REF_WINDOW = 80  # 当前默认窗口，作为对比基线


def pick_dates(reader: StockDataReader, n: int) -> list[str]:
    """选取最近 n 个有数据的交易日。"""
    now_utc = pd.Timestamp.utcnow().tz_localize(None)
    # 用 000001.SZ 的近 N 天日线日期作为代表
    df = reader.read_stock(
        "000001.SZ",
        start_time=(now_utc - pd.Timedelta(days=30)).strftime("%Y%m%d"),
        end_time=now_utc.strftime("%Y%m%d"),
        period="1d",
        adjust_type="front",
    )
    if df is None or df.empty:
        return [now_utc.strftime("%Y%m%d")]

    dates = sorted(df.index.strftime("%Y%m%d").unique())[-n:]
    return dates


def compute_window_cyqk(
    reader: StockDataReader,
    symbol: str,
    end_date: str,
    window_days: int,
) -> float | None:
    """计算指定窗口长度下的 cyqk_c。"""
    # 往前读足够多的数据（窗口 × 1.5 余量）
    start_dt = pd.Timestamp(end_date) - pd.Timedelta(days=window_days * 2)
    df = reader.read_stock(
        symbol,
        start_time=start_dt.strftime("%Y%m%d"),
        end_time=end_date,
        period="1d",
        adjust_type="front",
    )
    if df is None or df.empty:
        return None

    # 取最后 window_days 个交易日
    df = df.sort_index()
    unique_dates = df.index.normalize().unique()
    if len(unique_dates) < window_days:
        return None

    last_n_dates = unique_dates[-window_days:]
    mask = df.index.normalize().isin(last_n_dates)
    df_window = df.loc[mask]

    if len(df_window) < window_days:
        return None

    result = compute_chip_factors(df_window, method="triang", data_freq="1d", stock_code=symbol)
    return float(result["cyqk_c"])


def main() -> int:
    parser = argparse.ArgumentParser(description="窗口长度敏感性分析")
    parser.add_argument("--dates", type=int, default=DEFAULT_DATES, help="测试日期数")
    parser.add_argument("--output", type=str, default=None, help="输出 CSV 路径")
    parser.add_argument(
        "--min-completeness",
        type=float,
        default=0.90,
        help="有效截面完整率下限（0-1）。低于该阈值则返回非零退出码。",
    )
    args = parser.parse_args()

    reader = StockDataReader(mode="duckdb_persistent")
    dates = pick_dates(reader, args.dates)
    print(f"测试日期: {dates}")
    print(f"窗口长度: {WINDOWS}")
    print(f"样本分组: {', '.join(f'{k}({len(v)}只)' for k, v in SAMPLE_STOCKS.items())}")
    print()

    all_stocks = [(grp, sym) for grp, syms in SAMPLE_STOCKS.items() for sym in syms]
    rows = []
    attempted = 0
    compute_errors = 0
    incomplete_rows = 0

    for group, symbol in tqdm(all_stocks, desc="计算中"):
        for date in dates:
            attempted += 1
            try:
                ref_val = compute_window_cyqk(reader, symbol, date, DEFAULT_REF_WINDOW)
            except Exception as exc:
                compute_errors += 1
                print(
                    f"[WARN] 基线窗口计算失败: {symbol} {date} {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                continue
            if ref_val is None:
                continue

            row = {"group": group, "symbol": symbol, "date": date, f"win_{DEFAULT_REF_WINDOW}d": ref_val}
            row_complete = True
            for w in WINDOWS:
                if w == DEFAULT_REF_WINDOW:
                    continue
                try:
                    val = compute_window_cyqk(reader, symbol, date, w)
                except Exception as exc:
                    compute_errors += 1
                    row_complete = False
                    print(
                        f"[WARN] 窗口计算失败: {symbol} {date} w={w} {type(exc).__name__}: {exc}",
                        file=sys.stderr,
                    )
                    val = None
                row[f"win_{w}d"] = val
                if val is not None:
                    row[f"delta_{w}d"] = val - ref_val
                else:
                    row_complete = False

            if row_complete:
                rows.append(row)
            else:
                incomplete_rows += 1

    if not rows:
        print("无有效计算结果")
        return 1

    effective_total = len(rows) + incomplete_rows
    completeness = (len(rows) / effective_total) if effective_total > 0 else 0.0
    print(
        f"完整率: {completeness:.1%}（有效 {len(rows)} / 总截面 {effective_total}, "
        f"计算异常 {compute_errors}）"
    )
    if completeness < float(args.min_completeness):
        print(
            f"[FAIL] 完整率 {completeness:.1%} < --min-completeness {float(args.min_completeness):.1%}",
            file=sys.stderr,
        )
        return 2

    df_out = pd.DataFrame(rows)
    print(f"\n=== 窗口长度敏感性分析（共 {len(df_out)} 个截面点）===")
    print(f"基线窗口: {DEFAULT_REF_WINDOW} 天")
    print()

    # 汇总统计
    for w in WINDOWS:
        if w == DEFAULT_REF_WINDOW:
            continue
        col = f"delta_{w}d"
        if col not in df_out.columns:
            continue
        deltas = df_out[col].dropna()
        if deltas.empty:
            continue
        abs_deltas = deltas.abs()
        mean_abs = abs_deltas.mean()
        median_abs = abs_deltas.median()
        p95_abs = np.percentile(abs_deltas, 95)

        # 敏感样本占比（|delta| > 0.05）
        sensitive = (abs_deltas > 0.05).sum()
        sensitive_pct = sensitive / len(deltas)

        print(f"  {w}d vs {DEFAULT_REF_WINDOW}d:")
        print(f"    中位绝对变化: {median_abs:.4f}  均值绝对变化: {mean_abs:.4f}  P95: {p95_abs:.4f}")
        print(f"    敏感样本: {sensitive}/{len(deltas)} = {sensitive_pct:.1%}")

        # 按分组
        for grp in SAMPLE_STOCKS:
            grp_deltas = df_out[df_out["group"] == grp][col].dropna()
            if grp_deltas.empty:
                continue
            grp_sensitive = (grp_deltas.abs() > 0.05).sum()
            if grp_sensitive > 0:
                print(f"      {grp}: {grp_sensitive}/{len(grp_deltas)} 敏感")

        print()

    # 决策建议
    total_sensitive = sum(
        (df_out[f"delta_{w}d"].dropna().abs() > 0.05).sum()
        for w in WINDOWS if w != DEFAULT_REF_WINDOW and f"delta_{w}d" in df_out.columns
    )
    total_all = sum(
        df_out[f"delta_{w}d"].dropna().shape[0]
        for w in WINDOWS if w != DEFAULT_REF_WINDOW and f"delta_{w}d" in df_out.columns
    )
    overall_pct = total_sensitive / total_all if total_all > 0 else 0

    print(f"总体敏感占比: {overall_pct:.1%}")
    if overall_pct > 0.20:
        print("结论: 敏感股票占比 > 20%，建议投入参数调优")
    else:
        print("结论: 敏感股票占比 <= 20%，接受当前 80 天默认窗口，记录差异即可")

    # 保存
    out_path = args.output or str(REPO / "backtest_output" / "chip_window_sensitivity.csv")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n结果已保存: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
