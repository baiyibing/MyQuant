#!/usr/bin/env python3
"""筹码因子抽样检查 — 输出流通股本、换手率、赢筹率及阻力因子供人工复核。

用法：
    python scripts/data/spot_check_chip_factors.py
    python scripts/data/spot_check_chip_factors.py --date 20260515 --samples 100 --seed 42
"""
from __future__ import annotations

from myquant_factors._runtime import research_root, resolve_source_parquet

from typing import Any, cast

import argparse
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = research_root()
sys.path.insert(0, str(REPO))

from myquant_factors._runtime import StockDataReader
from myquant_factors.chip.core import (
    adapt_columns,
    compute_chip_factors,
    compute_crossday_turnover_resistance,
    daily_chip_distribution,
)
from myquant_factors._runtime import resolve_source_parquet


def _cost_at_ratio(cumpdf: pd.Series, ratio: float) -> float:
    """从累计筹码分布中获取给定比例对应的价格。

    cumpdf: index=price, values=累计筹码量
    ratio: 0~1，如 0.9 表示 90% 筹码成本低于该价格
    """
    total = cumpdf.sum()
    if total <= 0:
        return float("nan")
    acc = (cumpdf / total).cumsum()
    # 找到第一个累计占比 >= ratio 的价格
    mask = acc >= ratio
    if not mask.any():
        return float(cast(Any, cumpdf.index[-1]))
    return float(cast(Any, cumpdf.index[mask].min()))


def compute_all_factors(
    df: pd.DataFrame,
    stock_code: str,
) -> dict:
    """计算筹码因子 + 阻力位/支撑位/集中度。

    从 daily_chip_distribution 获取 cumpdf，自行计算所有衍生指标。
    """
    as_of = pd.Timestamp(cast(Any, df.index[-1])).normalize()
    arr = adapt_columns(cast(Any, df), stock_code=stock_code, as_of_date=as_of)
    cumpdf = daily_chip_distribution(arr, method="triang")
    close_price = float(arr[-1, 0])

    if cumpdf.empty or cumpdf.sum() <= 0:
        return {"cyqk_c": "", "asr": "", "ckdw": "", "prp": ""}

    total = float(cumpdf.sum())

    # ── 基础四因子（复用 compute_chip_factors 保证一致性）──
    base = compute_chip_factors(df, method="triang", data_freq="1d", stock_code=stock_code)
    result = {
        "cyqk_c": round(base["cyqk_c"], 4),
        "asr": round(base["asr"], 4),
        "ckdw": round(base["ckdw"], 2),
        "prp": round(base["prp"], 4),
    }

    # ── 筹码分位价格（阻力/支撑位）──
    try:
        p95 = _cost_at_ratio(cumpdf, 0.95)
        p90 = _cost_at_ratio(cumpdf, 0.90)
        p70 = _cost_at_ratio(cumpdf, 0.70)
        p50 = _cost_at_ratio(cumpdf, 0.50)
        p30 = _cost_at_ratio(cumpdf, 0.30)
        p10 = _cost_at_ratio(cumpdf, 0.10)
        p05 = _cost_at_ratio(cumpdf, 0.05)

        result.update({
            "cost_p95": round(p95, 2) if not np.isnan(p95) else "",
            "cost_p90": round(p90, 2) if not np.isnan(p90) else "",
            "cost_p70": round(p70, 2) if not np.isnan(p70) else "",
            "cost_p50": round(p50, 2) if not np.isnan(p50) else "",
            "cost_p30": round(p30, 2) if not np.isnan(p30) else "",
            "cost_p10": round(p10, 2) if not np.isnan(p10) else "",
            "cost_p05": round(p05, 2) if not np.isnan(p05) else "",
        })

        # ── 阻力/支撑距离（close 距离各分位的百分比）──
        if close_price > 0:
            result["resist_dist_p90_pct"] = round((p90 - close_price) / close_price * 100, 2) if not np.isnan(p90) else ""
            result["resist_dist_p95_pct"] = round((p95 - close_price) / close_price * 100, 2) if not np.isnan(p95) else ""
            result["support_dist_p10_pct"] = round((close_price - p10) / close_price * 100, 2) if not np.isnan(p10) else ""
        else:
            result["resist_dist_p90_pct"] = result["resist_dist_p95_pct"] = result["support_dist_p10_pct"] = ""

        # ── 集中度 ──
        if p50 > 0 and not np.isnan(p50):
            result["concentration_90"] = round((p90 - p10) / p50, 4) if not (np.isnan(p90) or np.isnan(p10)) else ""
            result["concentration_70"] = round((p70 - p30) / p50, 4) if not (np.isnan(p70) or np.isnan(p30)) else ""
        else:
            result["concentration_90"] = result["concentration_70"] = ""

        # ── 获利/套牢 ──
        acc = (cumpdf / total).cumsum()
        below_mask = cumpdf.index <= close_price
        winner = float(acc[below_mask].iloc[-1]) if below_mask.any() else 0.0
        result["winner_ratio"] = round(winner, 4)
        result["loser_ratio"] = round(1 - winner, 4)

    except Exception:
        pass

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="筹码因子抽样检查")
    parser.add_argument("--date", default="20260515", help="目标日期 YYYYMMDD")
    parser.add_argument("--samples", type=int, default=100, help="随机抽样数量")
    parser.add_argument("--seed", type=int, default=42, help="随机种子（固定可复现）")
    parser.add_argument("--output", type=str, default=None, help="输出 CSV 路径")
    parser.add_argument("--window", type=int, default=80, help="筹码计算窗口（交易日）")
    args = parser.parse_args()

    target_date = args.date
    target_ts = pd.Timestamp(target_date)
    window = args.window

    # ── 加载 float_shares ──
    fs_path = resolve_source_parquet("float_shares.parquet")
    if not fs_path.exists():
        print(f"[FATAL] float_shares.parquet 不存在: {fs_path}")
        return 1
    fs_df = pd.read_parquet(fs_path)

    # ── 抽样 ──
    all_stocks = sorted(fs_df["stock_code"].tolist())
    random.seed(args.seed)
    sample = sorted(random.sample(all_stocks, min(args.samples, len(all_stocks))))
    print(f"目标日期: {target_date}  窗口: {window}天  抽样: {len(sample)}只  seed: {args.seed}")

    reader = StockDataReader(mode="duckdb_persistent")
    rows = []
    errors = []

    for s in sample:
        # ── 数据新鲜度校验 ──
        ok, msg = reader.validate_freshness(
            s, target_date, period="1d", adjust_type="front", min_trading_days=window + 1
        )
        if not ok:
            errors.append(msg)
            continue

        fs_row = fs_df[fs_df["stock_code"] == s]
        float_s = fs_row["float_shares"].values[0]
        total_s = fs_row["total_shares"].values[0]
        name = fs_row["name"].values[0]

        df = reader.read_stock(
            s,
            start_time=(target_ts - pd.Timedelta(days=window * 3)).strftime("%Y%m%d"),
            end_time=target_date,
            period="1d",
            adjust_type="front",
        )

        assert df is not None
        df = df.sort_index()
        unique_dates = df.index.normalize().unique()
        mask = df.index.normalize().isin(unique_dates[-window:])
        df_w = df.loc[mask]

        # ── 换手率 ──
        vol_1d = df_w["volume"].iloc[-1]
        vol_5d = df_w["volume"].tail(5).mean()
        vol_20d = df_w["volume"].tail(20).mean()

        t5 = round(vol_5d * 100 / float_s, 4)
        t20 = round(vol_20d * 100 / float_s, 4)

        # ── 价格 ──
        close_now = df_w["close"].iloc[-1]
        high_w = df_w["high"].max()
        low_w = df_w["low"].min()

        close_5d_ago = df_w["close"].iloc[-6] if len(df_w) >= 6 else np.nan
        close_20d_ago = df_w["close"].iloc[-21] if len(df_w) >= 21 else np.nan
        close_80d_ago = df_w["close"].iloc[0]

        # ── 筹码因子 + 阻力因子（当日）──
        try:
            factors = compute_all_factors(df_w, s)
        except Exception as e:
            errors.append(f"{s}: compute_all_factors failed: {e}")
            continue

        try:
            cross = compute_crossday_turnover_resistance(df, s, window=window)
        except (ValueError, Exception) as e:
            errors.append(f"{s}: crossday resistance failed: {e}")
            continue

        t1 = cross["turnover_ratio"]
        yesterday_cyqk = cross["cyqk_c_yesterday"]
        cyqk_diff = cross["profit_chip_diff"]
        turnover_resist = cross["turnover_resistance"]

        # ── 阻力/支撑绝对值（元）──
        resist_abs = round(factors["cost_p90"] - close_now, 2) if factors.get("cost_p90") and factors["cost_p90"] != "" else ""
        support_abs = round(close_now - factors["cost_p10"], 2) if factors.get("cost_p10") and factors["cost_p10"] != "" else ""

        row = {
            "stock_code": s,
            "name": str(name),
            "total_shares_亿": round(total_s / 1e8, 2),
            "float_shares_亿": round(float_s / 1e8, 2),
            "close": round(close_now, 2),
            "high_80d": round(high_w, 2),
            "low_80d": round(low_w, 2),
            "volume_1d_手": int(vol_1d),
            "volume_5d_avg_手": int(vol_5d),
            "volume_20d_avg_手": int(vol_20d),
            "turnover_1d": t1,
            "turnover_5d_avg": t5,
            "turnover_20d_avg": t20,
            "close_chg_5d_pct": round((close_now - close_5d_ago) / close_5d_ago * 100, 2)
                if not (isinstance(close_5d_ago, float) and np.isnan(close_5d_ago)) and close_5d_ago > 0 else "",
            "close_chg_20d_pct": round((close_now - close_20d_ago) / close_20d_ago * 100, 2)
                if not (isinstance(close_20d_ago, float) and np.isnan(close_20d_ago)) and close_20d_ago > 0 else "",
            "close_chg_80d_pct": round((close_now - close_80d_ago) / close_80d_ago * 100, 2),
            **factors,
            # 阻力/支撑绝对值
            "resist_abs": resist_abs,
            "support_abs": support_abs,
            # 换手阻力
            "cyqk_c_yesterday": yesterday_cyqk,
            "cyqk_c_diff": cyqk_diff,          # 当日盈筹差
            "turnover_resist": turnover_resist,  # 当日换手阻力
        }
        rows.append(row)

    reader.close()

    # ── 输出 ──
    print(f"有效: {len(rows)}  跳过: {len(errors)}")
    if errors:
        for e in errors:
            print(f"  {e}")

    if not rows:
        print("[FATAL] 无有效数据")
        return 1

    out_df = pd.DataFrame(rows)
    out_path = args.output or str(
        REPO / "backtest_output" / f"spot_check_{len(rows)}_stocks_{target_date}.csv"
    )
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"Saved: {out_path} ({len(out_df)} rows, {len(out_df.columns)} cols)")

    # ── 快速摘要 ──
    print(f"\n=== 分布摘要 ===")
    print(f"close: {out_df['close'].min():.2f} ~ {out_df['close'].max():.2f}")
    print(f"float_shares: {out_df['float_shares_亿'].min():.1f}亿 ~ {out_df['float_shares_亿'].max():.1f}亿")
    print(f"cyqk_c: {out_df['cyqk_c'].min():.4f} ~ {out_df['cyqk_c'].max():.4f}  median={out_df['cyqk_c'].median():.4f}")
    for col in ["concentration_90", "concentration_70"]:
        vals = pd.to_numeric(out_df[col], errors="coerce").dropna()
        if len(vals) > 0:
            print(f"{col}: {vals.min():.4f} ~ {vals.max():.4f}  median={vals.median():.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
