#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backfill canonical TR daily series + TR Bollinger Bands into Parquet."""

from __future__ import annotations

from myquant_factors._runtime import research_root, resolve_source_parquet

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = research_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from myquant_factors._runtime import ensure_repo_on_syspath

ensure_repo_on_syspath(__file__)

import duckdb

from myquant_factors._runtime import get_logger
from myquant_factors._runtime import shanghai_date_yyyymmdd
from myquant_factors.bridge.turnover_resist import compute_turnover_resist
from myquant_factors.chip.bands import compute_tr_bb_columns
from myquant_factors.research._inputs import (
    DEFAULT_FREE_FLOAT_POLICY,
    TurnoverResistanceStore,
    resolve_parquet_path,
)
from myquant_factors._runtime import resolve_turnover_resist_parquet_root

_log = get_logger(__name__)

CANONICAL_WINDOW = 1000
PROGRESS_FILE = Path("backtest_output/tr_backfill_progress.json")


def _daily_glob(data_dir: Path) -> str:
    # hive-split: <container>/stock/period=1d (OSKH_PERIOD_1D_ROOT wins).
    # Do not probe a legacy container/period=1d layout.
    from myquant_factors._runtime import resolve_period_root

    period_root = resolve_period_root("1d", base=data_dir / "stock")
    return str(
        period_root / "dividend_type=front" / "*" / "data.parquet"
    ).replace("\\", "/")


def list_trading_dates(
    data_dir: Path,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[str]:
    glob_pat = _daily_glob(data_dir)
    where = ""
    if start_date or end_date:
        parts = []
        if start_date:
            parts.append(f"d >= '{start_date}'")
        if end_date:
            parts.append(f"d <= '{end_date}'")
        where = "WHERE " + " AND ".join(parts)
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"""
            SELECT d FROM (
              SELECT
                strftime(to_timestamp(time/1000), '%Y%m%d') AS d,
                time AS t
              FROM read_parquet('{glob_pat}', hive_partitioning=true, union_by_name=true)
              GROUP BY time
            ) sub
            {where}
            ORDER BY t
            """
        ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


def _default_data_dir() -> str:
    return str(resolve_turnover_resist_parquet_root())


def _write_progress(payload: dict) -> None:
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill turnover resistance + TR BB history")
    parser.add_argument(
        "--year",
        type=int,
        default=0,
        help="Backfill one calendar year (YYYY0101-YYYY1231 trading days). Implies --all-trading-days.",
    )
    parser.add_argument(
        "--all-trading-days",
        action="store_true",
        help="Backfill all trading dates within --start-date/--end-date",
    )
    parser.add_argument(
        "--year-bands",
        action="store_true",
        help="Recompute TR BB only for trade dates in --year (requires --year)",
    )
    parser.add_argument(
        "--trading-days",
        type=int,
        default=0,
        help="If >0: backfill last N trading days ending at --end-date (not calendar days)",
    )
    parser.add_argument(
        "--start-date",
        default="",
        help="Inclusive YYYYMMDD lower bound (with --all-trading-days)",
    )
    parser.add_argument(
        "--end-date",
        default="",
        help="Inclusive YYYYMMDD upper bound (default: latest in daily parquet)",
    )
    parser.add_argument(
        "--data-dir",
        default="",
        help="Parquet root (default: resolve_turnover_resist_parquet_root)",
    )
    parser.add_argument("--parquet-path", default="", help="Override store Parquet path")
    parser.add_argument("--window", type=int, default=CANONICAL_WINDOW)
    parser.add_argument(
        "--free-float-policy",
        default=DEFAULT_FREE_FLOAT_POLICY,
        choices=("warn-zero", "skip", "fail"),
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip dates already present in store",
    )
    parser.add_argument(
        "--tr-only",
        action="store_true",
        help="Only upsert TR cross-sections; skip TR BB (use --recompute-bands after full TR)",
    )
    parser.add_argument(
        "--recompute-bands",
        action="store_true",
        help="Vectorized TR BB recompute on entire store, then exit",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=10,
        help="Write progress JSON every N processed days (default 10)",
    )
    return parser.parse_args(argv)


def _resolve_dates(args: argparse.Namespace, data_dir: Path) -> list[str]:
    if args.year and args.year > 0:
        args.all_trading_days = True
        if not args.start_date:
            args.start_date = f"{args.year}0101"
        if not args.end_date:
            args.end_date = f"{args.year}1231"

    end = args.end_date
    if not end:
        all_dates = list_trading_dates(data_dir)
        end = all_dates[-1] if all_dates else shanghai_date_yyyymmdd()

    dates = []
    if args.all_trading_days or args.year:
        dates = list_trading_dates(
            data_dir,
            start_date=args.start_date or None,
            end_date=end,
        )
    elif args.trading_days and args.trading_days > 0:
        all_dates = list_trading_dates(data_dir, end_date=end)
        dates = all_dates[-args.trading_days :]
    else:
        end_dt = datetime.strptime(end, "%Y%m%d")
        cal_start = (end_dt - timedelta(days=59)).strftime("%Y%m%d")
        dates = list_trading_dates(data_dir, start_date=cal_start, end_date=end)

    if args.year and args.year > 0 and dates:
        # Clamp to actual data availability (e.g. 2026 YTD ends at latest bar date)
        latest = list_trading_dates(data_dir)[-1]
        cap = min(args.end_date or f"{args.year}1231", latest)
        dates = [d for d in dates if d <= cap]
    return dates


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    data_dir = Path(args.data_dir or _default_data_dir())
    # Infra owns IO; this host supplies the unchanged numerical producer.
    store = TurnoverResistanceStore(
        args.parquet_path or None, bands_producer=compute_tr_bb_columns,
    )

    if args.recompute_bands:
        t0 = time.perf_counter()
        stats = store.compute_all_bands_vectorized(
            period=20,
            window=args.window,
        )
        elapsed = time.perf_counter() - t0
        print(
            f"[recompute-bands] updated={stats['updated_rows']} "
            f"total={stats['total_rows']} elapsed={elapsed:.1f}s"
        )
        return 0

    dates = _resolve_dates(args, data_dir)

    if args.year_bands:
        if not args.year:
            print("[error] --year-bands requires --year")
            return 1
        if not dates:
            print("[error] no trading dates for year-bands")
            return 1
        t0 = time.perf_counter()
        stats = store.compute_and_update_bands(
            trade_dates=dates,
            n_history=60,
            period=20,
            window=args.window,
        )
        print(
            f"[year-bands {args.year}] updated={stats['updated_rows']} "
            f"dates={stats['trade_dates']} elapsed={time.perf_counter()-t0:.1f}s"
        )
        return 0

    if not dates:
        print("[error] no trading dates resolved")
        return 1

    have = set(store.list_trade_dates(window=args.window)) if args.skip_existing else set()
    todo = [d for d in dates if d not in have]
    year_tag = f" year={args.year}" if args.year else ""
    print(
        f"plan{year_tag} total={len(dates)} todo={len(todo)} skip={len(dates)-len(todo)} "
        f"range={dates[0]}..{dates[-1]} data_dir={data_dir} "
        f"store={resolve_parquet_path(args.parquet_path or None)}"
    )
    sys.stdout.flush()

    ok = fail = skip = 0
    t_start = time.perf_counter()
    for i, trade_date in enumerate(dates, 1):
        if trade_date in have:
            skip += 1
            continue
        try:
            rows = compute_turnover_resist(
                trade_date,
                data_dir=str(data_dir),
                window=args.window,
                free_float_policy=args.free_float_policy,
            )
            if not rows:
                fail += 1
                print(f"[{i}/{len(dates)}] empty {trade_date}")
                sys.stdout.flush()
                continue
            stats = store.upsert_daily(
                trade_date,
                rows,
                window=args.window,
                source="canonical_rust",
                free_float_policy=args.free_float_policy,
            )
            ok += 1
            print(
                f"[{i}/{len(dates)}] ok {trade_date} rows={len(rows)} "
                f"total={stats['total_after']}"
            )
        except Exception as exc:
            fail += 1
            _log.warning(
                "compute_turnover_resist failed",
                context={"trade_date": trade_date, "error": str(exc)},
            )
            print(f"[{i}/{len(dates)}] fail {trade_date}: {exc}")

        if ok and ok % args.progress_every == 0:
            elapsed = time.perf_counter() - t_start
            _write_progress(
                {
                    "ok": ok,
                    "fail": fail,
                    "skip": skip,
                    "last_date": trade_date,
                    "elapsed_s": round(elapsed, 1),
                    "eta_days": round((len(todo) - ok - fail) * (elapsed / max(ok, 1)), 0),
                }
            )
        sys.stdout.flush()

    if not args.tr_only:
        t0 = time.perf_counter()
        band_stats = store.compute_all_bands_vectorized(period=20, window=args.window)
        print(
            f"[bands] updated={band_stats['updated_rows']} "
            f"total={band_stats['total_rows']} elapsed={time.perf_counter()-t0:.1f}s"
        )

    dist = store.distribution_stats(dates[-1], window=args.window)
    summary = {
        "ok": ok,
        "fail": fail,
        "skip": skip,
        "todo": len(todo),
        "latest": dates[-1],
        "year": args.year or None,
    }
    _write_progress(summary)
    print(f"summary {summary}")
    if dist:
        print(
            f"dist@{dates[-1]} count={int(dist['count'])} p50={dist['p50']:.4f} "
            f"p95={dist['p95']:.4f} |TR|>20={dist['abs_gt_20_pct']:.2f}%"
        )
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
