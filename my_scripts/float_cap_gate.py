# -*- coding: utf-8 -*-
"""M3-D-B: verification gate for the on-site derived float market cap.

There is no external market-cap source in this setup, so the cap used by the
size neutralization is derived from bin-16 fields:
``float_cap ≈ $close × $adfadfbasiccurhold`` (log taken for the regression).
A derived quantity may not be fed to the ranking side on trust, so
:func:`verify_float_cap` has to pass first:

1. **coverage** — NaN rate below 1%;
2. **rank sanity** — median daily Spearman correlation against ``$amount``
   above 0.5 (free-float cap and turnover are strongly related; that is the
   common-sense anchor, not a model claim);
3. **bellwethers** — known mega caps (600519 …) sit near the top of the cap
   ranking.

If the gate fails, the *size* method is blocked and stays blocked: the
industry method remains available and nothing gets force-fitted around a cap
we cannot trust.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from ranking_neutralize import as_panel_series, to_qlib_code  # noqa: E402

CLOSE_COLUMN = "$close"
FLOAT_SHARE_COLUMN = "$adfadfbasiccurhold"
AMOUNT_COLUMN = "$amount"

MAX_NAN_RATE = 0.01
MIN_MEDIAN_RANK_CORR = 0.5
#: Bellwethers must sit in the top decile of the daily cap ranking.
MIN_BELLWETHER_PERCENTILE = 0.9
MIN_CORR_ROWS = 5

#: Unambiguous mega caps; absent ones are reported as skipped, never failed.
DEFAULT_BELLWETHERS = ("SH600519", "SH601398", "SH600036")


@dataclass(frozen=True)
class FloatCapGateReport:
    """Verdict of the derived-cap gate. ``passed`` False ⇒ size is blocked."""

    passed: bool
    rows: int = 0
    days: int = 0
    nan_rate: float = 1.0
    median_rank_corr: float | None = None
    corr_days: int = 0
    bellwether_percentiles: dict[str, float] = field(default_factory=dict)
    bellwethers_missing: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    thresholds: dict[str, float] = field(default_factory=dict)

    @property
    def size_blocked(self) -> bool:
        return not self.passed

    def blocked_message(self) -> str:
        return "float cap gate failed (size neutralization blocked): " + "; ".join(
            self.reasons or ("unknown reason",)
        )

    def as_manifest_fields(self) -> dict[str, Any]:
        """Flat, JSON-safe summary for the export manifest config block."""
        return {
            "float_cap_gate_passed": bool(self.passed),
            "float_cap_gate_rows": int(self.rows),
            "float_cap_gate_days": int(self.days),
            "float_cap_gate_nan_rate": round(float(self.nan_rate), 6),
            "float_cap_gate_median_rank_corr": (
                None if self.median_rank_corr is None else round(float(self.median_rank_corr), 6)
            ),
            "float_cap_gate_bellwethers": {
                code: round(float(value), 6) for code, value in sorted(self.bellwether_percentiles.items())
            },
            "float_cap_gate_bellwethers_missing": list(self.bellwethers_missing),
            "float_cap_gate_reasons": list(self.reasons),
        }


def derive_log_float_cap(
    frame: pd.DataFrame,
    *,
    close_column: str = CLOSE_COLUMN,
    share_column: str = FLOAT_SHARE_COLUMN,
) -> pd.DataFrame:
    """``log($close × $adfadfbasiccurhold)`` as a long ``log_float_cap`` frame.

    Non-positive or missing inputs produce NaN — the size step bypasses those
    rows and the gate counts them, so a thin cap panel shows up as a gate
    failure instead of a silently shrunken universe.
    """
    missing = [
        column
        for column in ("datetime", "instrument", close_column, share_column)
        if column not in frame.columns
    ]
    if missing:
        raise ValueError(f"float cap input missing column(s): {', '.join(missing)}")

    close = pd.to_numeric(frame[close_column], errors="coerce").to_numpy(dtype="float64")
    shares = pd.to_numeric(frame[share_column], errors="coerce").to_numpy(dtype="float64")
    cap = close * shares
    with np.errstate(divide="ignore", invalid="ignore"):
        log_cap = np.where(np.isfinite(cap) & (cap > 0.0), np.log(np.where(cap > 0.0, cap, 1.0)), np.nan)

    out = pd.DataFrame(
        {
            "datetime": pd.to_datetime(frame["datetime"], errors="raise").dt.normalize(),
            "instrument": [to_qlib_code(code) or str(code) for code in frame["instrument"]],
            "float_cap": cap,
            "log_float_cap": log_cap,
        }
    )
    if AMOUNT_COLUMN in frame.columns:
        out[AMOUNT_COLUMN] = pd.to_numeric(frame[AMOUNT_COLUMN], errors="coerce").to_numpy()
    return out


def verify_float_cap(
    log_float_cap: pd.DataFrame | pd.Series | Mapping[Any, Any],
    amount: pd.DataFrame | pd.Series | Mapping[Any, Any] | None = None,
    *,
    bellwethers: tuple[str, ...] = DEFAULT_BELLWETHERS,
    max_nan_rate: float = MAX_NAN_RATE,
    min_median_rank_corr: float = MIN_MEDIAN_RANK_CORR,
    min_bellwether_percentile: float = MIN_BELLWETHER_PERCENTILE,
) -> FloatCapGateReport:
    """Run the three checks and return the verdict; never raises on bad data."""
    thresholds = {
        "max_nan_rate": float(max_nan_rate),
        "min_median_rank_corr": float(min_median_rank_corr),
        "min_bellwether_percentile": float(min_bellwether_percentile),
    }
    caps = as_panel_series(log_float_cap, value_column="log_float_cap", what="log_float_cap")
    if caps.empty:
        return FloatCapGateReport(
            passed=False,
            reasons=("empty cap panel",),
            thresholds=thresholds,
        )

    if amount is None and isinstance(log_float_cap, pd.DataFrame) and AMOUNT_COLUMN in log_float_cap.columns:
        amount = log_float_cap

    reasons: list[str] = []
    rows = int(len(caps))
    days = int(caps.index.get_level_values(0).nunique())
    nan_rate = float(caps.isna().mean())
    if nan_rate >= max_nan_rate:
        reasons.append(f"NaN rate {nan_rate:.2%} >= {max_nan_rate:.2%}")

    median_corr: float | None = None
    corr_days = 0
    if amount is None:
        reasons.append(f"no {AMOUNT_COLUMN} panel supplied for the rank-sanity check")
    else:
        amounts = as_panel_series(amount, value_column=AMOUNT_COLUMN, what=AMOUNT_COLUMN)
        paired = pd.DataFrame({"cap": caps, "amount": amounts.reindex(caps.index)}).dropna()
        daily_corr = []
        for _, block in paired.groupby(level=0, sort=True):
            if len(block) < MIN_CORR_ROWS:
                continue
            if block["cap"].nunique() < 2 or block["amount"].nunique() < 2:
                continue
            value = block["cap"].corr(block["amount"], method="spearman")
            if pd.notna(value):
                daily_corr.append(float(value))
        corr_days = len(daily_corr)
        if not daily_corr:
            reasons.append(f"no day had a usable cap/{AMOUNT_COLUMN} cross-section")
        else:
            median_corr = float(np.median(daily_corr))
            if median_corr <= min_median_rank_corr:
                reasons.append(
                    f"median daily rank-corr vs {AMOUNT_COLUMN} {median_corr:.3f} "
                    f"<= {min_median_rank_corr:.3f}"
                )

    percentiles: dict[str, float] = {}
    missing: list[str] = []
    ranked = caps.dropna()
    for raw_code in bellwethers:
        code = to_qlib_code(raw_code) or str(raw_code)
        per_day = []
        for _, block in ranked.groupby(level=0, sort=True):
            day_caps = block.droplevel(0)
            if len(day_caps) < 2 or code not in day_caps.index:
                continue
            # 1.0 == largest cap of the day.
            per_day.append(float(day_caps.rank(pct=True)[code]))
        if not per_day:
            missing.append(code)
            continue
        percentiles[code] = float(np.median(per_day))
    low = {code: value for code, value in percentiles.items() if value < min_bellwether_percentile}
    if low:
        detail = ", ".join(f"{code}={value:.3f}" for code, value in sorted(low.items()))
        reasons.append(
            f"bellwether cap percentile below {min_bellwether_percentile:.2f}: {detail}"
        )
    if bellwethers and not percentiles:
        reasons.append("no bellwether present in the cap panel")

    return FloatCapGateReport(
        passed=not reasons,
        rows=rows,
        days=days,
        nan_rate=nan_rate,
        median_rank_corr=median_corr,
        corr_days=corr_days,
        bellwether_percentiles=percentiles,
        bellwethers_missing=tuple(missing),
        reasons=tuple(reasons),
        thresholds=thresholds,
    )
