#!/usr/bin/env python3
"""Synthetic microbench for minute/hybrid chip hot paths (H14/D1 + H15/D2).

No F-lake / market data required. Times:
  - oskh_factors.chip.core.minute_chip_distribution (python + numba when available)
  - oskh_factors.chip.core.hybrid_chip_distribution
  - qlib_cost.cyq.calc_curpdf (triang) + calc_cumpdf kernels

Optional --profile prints a short cProfile top-N for the hottest entry.

Usage:
    python scripts/research/bench_minute_chip_hotpath.py
    python scripts/research/bench_minute_chip_hotpath.py \\
        --days 80 --minutes 240 --reps 20 --profile
"""

from __future__ import annotations

from myquant_factors._runtime import research_root, resolve_source_parquet

import argparse
import cProfile
import io
import pstats
import sys
import time
from pathlib import Path

import numpy as np

REPO = research_root()
sys.path.insert(0, str(REPO))

from myquant_factors.chip.core import (  # noqa: E402
    _NUMBA_MINUTE_CHIP_AVAILABLE,
    hybrid_chip_distribution,
    minute_chip_distribution,
    minute_chip_distribution_python,
)
from myquant_factors import cyq  # noqa: E402
from myquant_factors.distribution_of_chips import make_price_grid  # noqa: E402


def _synth_minute_arr(n_days: int, minutes_per_day: int, seed: int = 0) -> np.ndarray:
    """(N, 5) close/high/low/vol/turnover_rate — minute bars over n_days."""
    rng = np.random.default_rng(seed)
    n = n_days * minutes_per_day
    # Mild random walk around 10.0 so grid stays modest (~few hundred bins).
    rets = rng.normal(0.0, 0.0015, size=n)
    close = 10.0 * np.cumprod(1.0 + rets)
    high = close * (1.0 + rng.uniform(0.0, 0.002, size=n))
    low = close * (1.0 - rng.uniform(0.0, 0.002, size=n))
    vol = rng.uniform(1e3, 5e4, size=n)
    # Per-minute turnover small; daily sum ~ few percent.
    turnover = rng.uniform(1e-5, 5e-4, size=n)
    return np.column_stack([close, high, low, vol, turnover]).astype(np.float64)


def _synth_daily_arr(n_days: int, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, 0.02, size=n_days)
    close = 10.0 * np.cumprod(1.0 + rets)
    high = close * (1.0 + rng.uniform(0.005, 0.03, size=n_days))
    low = close * (1.0 - rng.uniform(0.005, 0.03, size=n_days))
    vol = rng.uniform(1e5, 5e6, size=n_days)
    turnover = rng.uniform(0.01, 0.08, size=n_days)
    return np.column_stack([close, high, low, vol, turnover]).astype(np.float64)


def _time_call(fn, args, kwargs, reps: int) -> tuple[float, float]:
    """Return (total_s, per_call_ms) after one warm-up."""
    fn(*args, **kwargs)
    t0 = time.perf_counter()
    for _ in range(reps):
        fn(*args, **kwargs)
    total = time.perf_counter() - t0
    return total, (total / reps) * 1000.0


def _bench_curpdf_kernel(n_days: int, step: float, reps: int) -> tuple[float, float, int]:
    daily = _synth_daily_arr(n_days, seed=2)
    min_p = float(np.nanmin(daily[:, 2]))
    max_p = float(np.nanmax(daily[:, 1]))
    xs = make_price_grid(min_p, max_p, step)
    n_bins = len(xs)

    def _run():
        out = np.zeros((n_days, n_bins), dtype=np.float64)
        for i in range(n_days):
            out[i] = cyq.calc_curpdf(
                float(daily[i, 0]),
                float(daily[i, 1]),
                float(daily[i, 2]),
                float(daily[i, 3]),
                min_p,
                max_p,
                step,
                method="triang",
            )
        return out

    total, per = _time_call(_run, (), {}, reps)
    return total, per, n_bins


def _bench_cumpdf_kernel(n_days: int, n_bins: int, reps: int) -> tuple[float, float]:
    rng = np.random.default_rng(3)
    curpdf = rng.random((n_days, n_bins), dtype=np.float64)
    curpdf /= curpdf.sum(axis=1, keepdims=True).clip(min=1e-12)
    turnover = rng.uniform(0.01, 0.08, size=n_days).astype(np.float64)
    # Warm numba JIT once outside timed loop.
    _ = cyq.calc_cumpdf(curpdf, turnover)

    def _run():
        return cyq.calc_cumpdf(curpdf, turnover)

    total, per = _time_call(_run, (), {}, reps)
    return total, per


def _profile_fn(label: str, fn, args, kwargs, sort: str = "cumtime", top: int = 15) -> str:
    pr = cProfile.Profile()
    pr.enable()
    fn(*args, **kwargs)
    pr.disable()
    buf = io.StringIO()
    stats = pstats.Stats(pr, stream=buf).sort_stats(sort)
    stats.print_stats(top)
    return f"=== cProfile {label} (top {top} by {sort}) ===\n{buf.getvalue()}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=80, help="hybrid history days / minute window days")
    ap.add_argument("--minutes", type=int, default=240, help="minutes per day for pure-minute path")
    ap.add_argument("--step", type=float, default=0.01)
    ap.add_argument("--reps", type=int, default=25)
    ap.add_argument("--curpdf-reps", type=int, default=50)
    ap.add_argument("--cumpdf-reps", type=int, default=200)
    ap.add_argument("--profile", action="store_true", help="print short cProfile for minute + hybrid")
    ap.add_argument("--profile-top", type=int, default=12)
    args = ap.parse_args()

    minute_arr = _synth_minute_arr(args.days, args.minutes, seed=0)
    daily_arr = _synth_daily_arr(args.days, seed=1)
    minute_today = _synth_minute_arr(1, args.minutes, seed=4)

    # Sanity: functions return non-empty Series on synth data.
    m0 = minute_chip_distribution(minute_arr, step=args.step, stock_code="SYNTH")
    h0 = hybrid_chip_distribution(daily_arr, minute_today, step=args.step)
    if m0.empty or h0.empty:
        print("ERROR: empty distribution on synthetic input")
        return 1

    print("H14/D1+H15/D2 minute-chip hotpath microbench (synthetic; no lake)")
    print(
        f"  days={args.days} minutes/day={args.minutes} "
        f"minute_bars={len(minute_arr)} step={args.step} "
        f"reps={args.reps}"
    )
    print(f"  minute_chip bins≈{len(m0)}  hybrid bins≈{len(h0)}")
    print()

    rows: list[tuple[str, float, float, str]] = []

    tot, per = _time_call(
        minute_chip_distribution_python,
        (minute_arr,),
        {"step": args.step, "stock_code": "SYNTH"},
        args.reps,
    )
    rows.append(
        (
            "minute_chip_distribution (python)",
            tot,
            per,
            f"{args.days}d×{args.minutes}m bars",
        )
    )
    py_per = per

    if _NUMBA_MINUTE_CHIP_AVAILABLE:
        # Warm JIT once outside timed loop.
        minute_chip_distribution(
            minute_arr, step=args.step, stock_code="SYNTH", use_numba=True
        )
        tot, per = _time_call(
            minute_chip_distribution,
            (minute_arr,),
            {"step": args.step, "stock_code": "SYNTH", "use_numba": True},
            args.reps,
        )
        rows.append(
            (
                "minute_chip_distribution (numba)",
                tot,
                per,
                f"{args.days}d×{args.minutes}m bars; speedup≈{py_per / per:.2f}x",
            )
        )
    else:
        print("minute numba SKIP (numba not installed / import failed)")

    tot, per = _time_call(
        hybrid_chip_distribution,
        (daily_arr, minute_today),
        {"step": args.step},
        args.reps,
    )
    rows.append(
        (
            "hybrid_chip_distribution",
            tot,
            per,
            f"{args.days} daily + {args.minutes}m today",
        )
    )

    tot, per, n_bins = _bench_curpdf_kernel(args.days, args.step, args.curpdf_reps)
    rows.append(
        (
            "calc_curpdf×N (triang loop)",
            tot,
            per,
            f"N={args.days} days, bins≈{n_bins}, reps={args.curpdf_reps}",
        )
    )

    tot, per = _bench_cumpdf_kernel(args.days, n_bins, args.cumpdf_reps)
    rows.append(
        (
            "calc_cumpdf (numba)",
            tot,
            per,
            f"shape=({args.days},{n_bins}), reps={args.cumpdf_reps}",
        )
    )

    print(f"{'kernel':<32} {'total_s':>10} {'ms/call':>12}  notes")
    print("-" * 90)
    ranked = sorted(rows, key=lambda r: r[2], reverse=True)
    for name, tot, per, notes in ranked:
        print(f"{name:<32} {tot:10.4f} {per:12.3f}  {notes}")
    print()
    print("Ranked by ms/call (hottest first):")
    for i, (name, _, per, _) in enumerate(ranked, 1):
        print(f"  {i}. {name}: {per:.3f} ms/call")

    if args.profile:
        print()
        print(
            _profile_fn(
                "minute_chip_distribution_python",
                minute_chip_distribution_python,
                (minute_arr,),
                {"step": args.step, "stock_code": "SYNTH"},
                top=args.profile_top,
            )
        )
        print(
            _profile_fn(
                "hybrid_chip_distribution",
                hybrid_chip_distribution,
                (daily_arr, minute_today),
                {"step": args.step},
                top=args.profile_top,
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
