"""Read ST PIT through the optional infra pin. This repo does not download.

Writers live in OSkhQuant1.3: ``python -m oskh_data.vendor_wind_st``.
MQ keeps its last-hit-day default and opt-in static coverage fallback locally.
Public imports work without infra; shared feature use reports an install hint.
"""

from __future__ import annotations

import json
from bisect import bisect_right
from datetime import date
from importlib import import_module
from pathlib import Path

_PACKAGE = "myquant_infra.reference_data.st.readers"
_PIN = "3c377e9718e811112993579b6d91a603395db699"


def _infra():
    try:
        return import_module(_PACKAGE)
    except ModuleNotFoundError as exc:
        if exc.name and (_PACKAGE == exc.name or _PACKAGE.startswith(exc.name + ".")):
            raise ModuleNotFoundError(
                f"ST readers require the optional myquant-infra pin {_PIN}; "
                "install it with python -m pip install -r requirements-infra.txt",
                name=exc.name,
            ) from exc
        raise


def to_wind_code(qlib_code: str) -> str:
    """SH600000 -> 600000.SH; SZ000001 -> 000001.SZ; BJ920000 -> 920000.BJ."""
    return _infra().to_wind_code(qlib_code)


def to_qlib_code(wind_code: str) -> str:
    """600000.SH -> SH600000."""
    return _infra().to_qlib_code(wind_code)


def _coverage_qlib_code(wind_code: str) -> str:
    """Legacy conversion for the wholly host-local coverage branch."""
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
    snapshot = {_coverage_qlib_code(c) for c in (coverage or {}).get("snapshot_fallback_wind_codes", [])}
    if not coverage:
        return static | snapshot
    harvested = {_coverage_qlib_code(c) for c in coverage.get("harvested_wind_codes", [])}
    unknown = {_coverage_qlib_code(c) for c in coverage.get("unknown_end_wind_codes", [])}
    if not harvested and not unknown:
        return static | snapshot
    return (static - harvested) | (static & unknown) | snapshot


def load_st_daily_index(
    daily_path: str | Path,
    coverage_path: str | Path | None = None,
    fallback_static: set[str] | None = None,
    *,
    use_coverage: bool = False,
) -> tuple[dict[date, set[str]], set[str]]:
    """st_daily.parquet → {date: {QLib代码}}。默认只认 ``is_st``，不读 coverage。"""
    if not use_coverage:
        by_date, _fallback = _infra().load_st_daily_index(daily_path)
        # MQ historically indexes only dates with hits. Keep that observation
        # rule for eligibility/asof; infra also retains dense all-False days.
        return {day: codes for day, codes in by_date.items() if codes}, set()
    import pandas as pd

    p = Path(daily_path)
    df = pd.read_parquet(p)
    by_date: dict[date, set[str]] = {}
    if not df.empty and "is_st" in df.columns:
        hit = df[df["is_st"] == True].copy()  # noqa: E712
        hit["trade_date"] = pd.to_datetime(hit["trade_date"])
        hit["qlib"] = hit["code"].map(_coverage_qlib_code)
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
    """取 as-of 日（默认 host 索引最后一天）的 QLib ST 集合；不读 coverage。

    Infra requires an explicit date. MQ resolves None and its legacy hit-only
    observation dates here, then delegates using that explicit chosen date.
    """
    del coverage_path, fallback_static
    by_date, _fallback = load_st_daily_index(daily_path, use_coverage=False)
    if not by_date:
        return set()
    dates = sorted(by_date)
    if asof is None:
        chosen = dates[-1]
    else:
        import pandas as pd

        target = pd.Timestamp(asof).date()
        idx = bisect_right(dates, target) - 1
        if idx < 0:
            return set()
        chosen = dates[idx]
    return _infra().load_st_codes_asof(daily_path, chosen)
