# -*- coding: utf-8 -*-
r"""Daily chip factor cross-section log (legacy TR_80 · paper observation).

Reads stock_pool + parquet cache, computes CYQ + turnover half-life factors,
writes ``backtest_output/chip_daily_{date}.csv``. No backtrader dependency.

Usage::

    python scripts/data/daily_chip_logger.py
    python scripts/data/daily_chip_logger.py --date 20260513
    python scripts/data/daily_chip_logger.py --date 20260513 --freq 1m
    python scripts/data/daily_chip_logger.py --schedule
"""

from __future__ import annotations

from myquant_factors._runtime import research_root, resolve_source_parquet

from typing import Any, cast

#!/usr/bin/env python3


from myquant_factors._runtime import ensure_repo_on_syspath
ensure_repo_on_syspath(__file__)
import argparse
import time
from datetime import datetime

import numpy as np
import pandas as pd

from myquant_factors._runtime import ensure_repo_on_syspath

REPO = research_root()

from myquant_factors._runtime import parse_pool_csv  # noqa: E402
from myquant_factors._runtime import StockDataReader  # noqa: E402
from myquant_factors.chip.core import (  # noqa: E402
    adapt_columns,
    daily_chip_distribution,
    derived_chip_factors,
    minute_chip_distribution,
    turnover_chip_factors,
)
from myquant_factors import cyq  # noqa: E402

OUTPUT_DIR = REPO / "backtest_output"
STOCK_POOL_DIR = REPO / "stock_pool"
WINDOW_DAYS = 80

_reader: StockDataReader | None = None


def _get_reader() -> StockDataReader:
    global _reader
    if _reader is None:
        _reader = StockDataReader()
    return _reader


def load_stock_pool(date_str: str) -> list[str]:
    """Load symbols from ``stock_pool/{date}.csv``."""
    path = STOCK_POOL_DIR / f"{date_str}.csv"
    if not path.is_file():
        return []
    return parse_pool_csv(path)


def compute_factors(code: str, freq: str = "1d", reader: StockDataReader | None = None) -> dict | None:
    """Compute chip factors for one symbol."""
    if reader is None:
        reader = _get_reader()
    df = reader.read_stock(code, period=freq, adjust_type="none")
    if df is None or len(df) < WINDOW_DAYS:
        return None

    if freq == "1m":
        df["dt"] = pd.to_datetime(df["time"], unit="ms")
        dates = sorted(df["dt"].dt.date.unique())
        if len(dates) < WINDOW_DAYS:
            return None
        df = df[df["dt"].dt.date >= dates[-WINDOW_DAYS]]

    df_w = df.tail(WINDOW_DAYS + 1) if freq == "1d" else df
    if len(df_w) < WINDOW_DAYS:
        return None

    try:
        df_today = df_w.tail(WINDOW_DAYS)
        as_of_t = pd.Timestamp(cast(Any, df_today.index[-1])).normalize()
        arr_today = adapt_columns(cast(Any, df_today), stock_code=code, as_of_date=as_of_t)
        if freq == "1m":
            dist_today = minute_chip_distribution(arr_today)
        else:
            dist_today = daily_chip_distribution(arr_today, method="triang")

        close_price = float(arr_today[-1, 0])
        cf = cyq.ChipFactor(close_price, dist_today)
        tr_arr = arr_today[:, 4]
        cl_arr = arr_today[:, 0]
        tcf = turnover_chip_factors(cast(Any, tr_arr), cl_arr, window=min(60, len(tr_arr)))

        cyqk_yesterday = np.nan
        try:
            df_yesterday = df_w.head(WINDOW_DAYS)
            as_of_y = pd.Timestamp(cast(Any, df_yesterday.index[-1])).normalize()
            arr_y = adapt_columns(cast(Any, df_yesterday), stock_code=code, as_of_date=as_of_y)
            dist_y = daily_chip_distribution(arr_y, method="triang")
            ct_y = float(arr_y[-1, 0])
            cf_y = cyq.ChipFactor(ct_y, dist_y)
            cyqk_yesterday = cf_y.get_cyqk_c()
        except Exception:
            pass

        turnover_today = float(arr_today[-1, 4])
        derived = derived_chip_factors(
            cf.get_cyqk_c(),
            cyqk_yesterday,
            turnover_today,
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily chip factor cross-section log (TR_80 legacy)")
    parser.add_argument("--date", help="stock_pool date YYYYMMDD (default: latest csv)")
    parser.add_argument("--freq", default="1d", choices=["1d", "1m"])
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="poll until 15:30 then run once",
    )
    args = parser.parse_args()

    if args.schedule:
        print(
            f"[{datetime.now():%H:%M:%S}] daily_chip_logger --schedule started, waiting for 15:30 ..."
        )
        while True:
            now = datetime.now()
            if now.hour >= 15 and now.minute >= 30:
                break
            time.sleep(60)
        print(f"[{now:%H:%M:%S}] Triggering daily chip factor log ...")

    if args.date:
        date_str = args.date
    else:
        csv_files = sorted(
            (f.name for f in STOCK_POOL_DIR.glob("*.csv")),
            reverse=True,
        )
        date_str = csv_files[0].replace(".csv", "") if csv_files else datetime.now().strftime("%Y%m%d")

    stock_list = load_stock_pool(date_str)
    if not stock_list:
        print(f"[WARN] No stocks in stock_pool for {date_str}")
        return

    print(
        f"[{datetime.now():%H:%M:%S}] Computing chip factors for {len(stock_list)} stocks "
        f"({args.freq}, pool={date_str}) ..."
    )

    reader = _get_reader()
    results: list[dict] = []
    ok = 0
    skip = 0
    for code in stock_list:
        row = compute_factors(code, freq=args.freq, reader=reader)
        if row:
            results.append(row)
            ok += 1
        else:
            skip += 1

    if not results:
        print("[WARN] No chip factors computed")
        return

    df = pd.DataFrame(results).sort_values("cyqk_c", ascending=False)
    df["signal"] = df["cyqk_c"].apply(
        lambda x: "HIGH" if x > 0.8 else ("LOW" if x < 0.2 else "")
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    freq_suffix = f"_{args.freq}" if args.freq != "1d" else ""
    out_path = OUTPUT_DIR / f"chip_daily_{date_str}{freq_suffix}.csv"
    df.to_csv(out_path, index=False)

    high_count = int((df["cyqk_c"] > 0.8).sum())
    low_count = int((df["cyqk_c"] < 0.2).sum())
    reader.close()

    print(f"  Done: {ok} OK, {skip} skipped → {out_path}")
    print(
        f"  cyqk_c: median={df['cyqk_c'].median():.3f}  "
        f"HIGH(>0.8)={high_count}  LOW(<0.2)={low_count}"
    )
    print(
        f"  arc: median={df['arc'].median():+.4f}  vrc: median={df['vrc'].median():.4f}  "
        f"src: median={df['src'].median():+.3f}  krc: median={df['krc'].median():.2f}"
    )

    if high_count > 0:
        print(f"  HIGH stocks: {', '.join(df[df.cyqk_c > 0.8].stock_code.head(10))}")
    if low_count > 0:
        print(f"  LOW  stocks: {', '.join(df[df.cyqk_c < 0.2].stock_code.head(10))}")


if __name__ == "__main__":
    main()
