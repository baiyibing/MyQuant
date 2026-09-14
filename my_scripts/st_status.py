"""Read ST PIT from the F lake. This repo does not download.

Writers live in OSkhQuant1.3: ``python -m oskh_data.vendor_wind_st``.
"""

from __future__ import annotations

import json
from bisect import bisect_right
from datetime import date
from pathlib import Path

import pandas as pd


def to_wind_code(qlib_code: str) -> str:
    """SH600000 -> 600000.SH; SZ000001 -> 000001.SZ; BJ920000 -> 920000.BJ."""
    c = qlib_code.strip().upper()
    if c.startswith("SH"):
        return c[2:] + ".SH"
    if c.startswith("SZ"):
        return c[2:] + ".SZ"
    if c.startswith("BJ"):
        return c[2:] + ".BJ"
    return c


def to_qlib_code(wind_code: str) -> str:
    """600000.SH -> SH600000."""
    c = wind_code.strip().upper()
    if c.endswith(".SH"):
        return "SH" + c[:-3]
    if c.endswith(".SZ"):
        return "SZ" + c[:-3]
    if c.endswith(".BJ"):
        return "BJ" + c[:-3]
    return c


def coverage_fallback_qlib(coverage: dict, static_codes: set[str] | None = None) -> set[str]:
    """静态名单里需要 fallback 的代码：未采到的 + 有实施但不知摘帽日的。"""
    static = {c.upper() for c in (static_codes or set())}
    snapshot = {to_qlib_code(c) for c in (coverage or {}).get("snapshot_fallback_wind_codes", [])}
    if not coverage:
        return static | snapshot
    harvested = {to_qlib_code(c) for c in coverage.get("harvested_wind_codes", [])}
    unknown = {to_qlib_code(c) for c in coverage.get("unknown_end_wind_codes", [])}
    if not harvested and not unknown:
        return static | snapshot
    return (static - harvested) | (static & unknown) | snapshot


def load_st_daily_index(
    daily_path: str | Path,
    coverage_path: str | Path | None = None,
    fallback_static: set[str] | None = None,
) -> tuple[dict[date, set[str]], set[str]]:
    """st_daily.parquet → {date: {QLib代码}}，以及 fallback 集合。"""
    p = Path(daily_path)
    df = pd.read_parquet(p)
    by_date: dict[date, set[str]] = {}
    if not df.empty and "is_st" in df.columns:
        hit = df[df["is_st"] == True].copy()  # noqa: E712
        hit["trade_date"] = pd.to_datetime(hit["trade_date"])
        hit["qlib"] = hit["code"].map(to_qlib_code)
        for d, sub in hit.groupby(hit["trade_date"].dt.date):
            by_date[d] = set(sub["qlib"].astype(str).str.upper())
    cov_path = Path(coverage_path) if coverage_path else p.parent / "st_coverage.json"
    coverage = {}
    if cov_path.is_file():
        coverage = json.loads(cov_path.read_text(encoding="utf-8"))
    fallback = coverage_fallback_qlib(coverage, fallback_static)
    return by_date, fallback


def load_st_codes_asof(
    daily_path: str | Path,
    asof=None,
    coverage_path: str | Path | None = None,
    fallback_static: set[str] | None = None,
) -> set[str]:
    """取 as-of 日（默认矩阵最后一天）的 QLib ST 集合，并并上 fallback。"""
    by_date, fallback = load_st_daily_index(daily_path, coverage_path, fallback_static)
    if not by_date:
        return set(fallback)
    dates = sorted(by_date)
    if asof is None:
        chosen = dates[-1]
    else:
        target = pd.Timestamp(asof).date()
        idx = bisect_right(dates, target) - 1
        if idx < 0:
            return set(fallback)
        chosen = dates[idx]
    return set(by_date[chosen]) | set(fallback)
