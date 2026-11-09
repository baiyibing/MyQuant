#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify Python canonical vs research-ops turnover resistance alignment.

This is a lake-backed research-path check, not Rust Store acceptance.
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

from myquant_factors._runtime import resolve_source_parquet
from myquant_factors.chip.core import (
    adapt_columns,
    compute_crossday_turnover_resistance,
    daily_chip_distribution,
    derived_chip_factors,
)
from myquant_factors import cyq
from myquant_factors._runtime import StockDataReader

WINDOW = 80


def alignment_exit_code(
    valid_samples: int,
    turnover_passes: int,
    resistance_passes: int,
) -> int:
    """Return 0 only when a non-empty sample passes both alignment metrics."""
    if valid_samples <= 0:
        return 1
    if turnover_passes == valid_samples and resistance_passes == valid_samples:
        return 0
    return 2


def _canonical_inline(df: pd.DataFrame, stock_code: str, window: int) -> dict:
    unique_dates = df.index.normalize().unique()
    if len(unique_dates) < window + 1:
        raise ValueError("insufficient days")

    as_of_t = pd.Timestamp(unique_dates[-1]).normalize()
    mask_t = df.index.normalize().isin(unique_dates[-window:])
    df_t = df.loc[mask_t]
    arr_t = adapt_columns(cast(Any, df_t), stock_code=stock_code, as_of_date=as_of_t)
    dist_t = daily_chip_distribution(arr_t, method="triang")
    cf_t = cyq.ChipFactor(float(arr_t[-1, 0]), dist_t)

    prev_dates = unique_dates[-(window + 1):-1]
    as_of_y = pd.Timestamp(prev_dates[-1]).normalize()
    mask_y = df.index.normalize().isin(prev_dates)
    df_y = df.loc[mask_y]
    arr_y = adapt_columns(cast(Any, df_y), stock_code=stock_code, as_of_date=as_of_y)
    dist_y = daily_chip_distribution(arr_y, method="triang")
    cf_y = cyq.ChipFactor(float(arr_y[-1, 0]), dist_y)

    derived = derived_chip_factors(
        cf_t.get_cyqk_c(), cf_y.get_cyqk_c(), float(arr_t[-1, 4]),
    )
    return {
        "cyqk_today": cf_t.get_cyqk_c(),
        "cyqk_yesterday": cf_y.get_cyqk_c(),
        "turnover_ratio": derived["turnover_ratio"],
        "turnover_resistance": derived["turnover_resistance"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="turnover resistance alignment verify")
    parser.add_argument("--date", default="20260515")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--window", type=int, default=WINDOW)
    parser.add_argument("--tol-turnover", type=float, default=1e-4)
    parser.add_argument("--tol-resist", type=float, default=0.05)
    args = parser.parse_args()

    fs_path = resolve_source_parquet("float_shares.parquet")
    if not fs_path.exists():
        print(f"[FATAL] missing {fs_path}")
        return 1
    fs_df = pd.read_parquet(fs_path)
    codes = sorted(fs_df["stock_code"].tolist())
    random.seed(args.seed)
    sample = sorted(random.sample(codes, min(args.samples, len(codes))))

    target_date = args.date
    target_ts = pd.Timestamp(target_date)
    window = args.window

    reader = StockDataReader(mode="duckdb_persistent")
    rows = []
    errors = []

    for code in sample:
        ok, msg = reader.validate_freshness(
            code, target_date, period="1d", adjust_type="front", min_trading_days=window + 1,
        )
        if not ok:
            errors.append(msg)
            continue

        df = reader.read_stock(
            code,
            start_time=(target_ts - pd.Timedelta(days=window * 3)).strftime("%Y%m%d"),
            end_time=target_date,
            period="1d",
            adjust_type="front",
        )
        assert df is not None
        df = df.sort_index()
        try:
            a = _canonical_inline(df, code, window)
            cross = compute_crossday_turnover_resistance(df, code, window=window)
            b_turnover = float(cross["turnover_ratio"])
            b_resist = float(cross["turnover_resistance"]) if cross["turnover_resistance"] != "" else np.nan
            b_cyqk_t = float(cross["cyqk_c"]) if cross["cyqk_c"] != "" else np.nan
            b_cyqk_y = float(cross["cyqk_c_yesterday"]) if cross["cyqk_c_yesterday"] != "" else np.nan
        except Exception as exc:
            errors.append(f"{code}: {exc}")
            continue

        turnover_abs_diff = abs(a["turnover_ratio"] - b_turnover)
        resist_abs_diff = abs(a["turnover_resistance"] - b_resist)

        rows.append({
            "stock_code": code,
            "turnover_canonical": a["turnover_ratio"],
            "turnover_ops": b_turnover,
            "turnover_abs_diff": turnover_abs_diff,
            "resist_canonical": a["turnover_resistance"],
            "resist_ops": b_resist,
            "resist_abs_diff": resist_abs_diff,
            "cyqk_t_abs_diff": abs(a["cyqk_today"] - b_cyqk_t),
            "cyqk_y_abs_diff": abs(a["cyqk_yesterday"] - b_cyqk_y),
            "turnover_ok": turnover_abs_diff <= args.tol_turnover,
            "resist_ok": resist_abs_diff <= args.tol_resist,
        })

    reader.close()

    if not rows:
        print(f"[FATAL] no rows; errors={len(errors)}")
        return alignment_exit_code(0, 0, 0)

    out = pd.DataFrame(rows)
    n = len(out)
    t_ok = int(out["turnover_ok"].sum())
    r_ok = int(out["resist_ok"].sum())
    print(f"date={target_date} samples={n} window={window}")
    print(f"turnover aligned: {t_ok}/{n}  resist aligned: {r_ok}/{n}")

    out_path = REPO / "backtest_output" / f"verify_turnover_resist_align_{target_date}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"Saved: {out_path}")

    return alignment_exit_code(n, t_ok, r_ok)


if __name__ == "__main__":
    sys.exit(main())
