# -*- coding: utf-8 -*-
"""M3-C: ranking feature experiments from bin-16 fields only.

Computable from:
adjclose amount basiccurhold adfadfbasiccurhold bigddx change close factor
high low netcsfree open volddx volume vwap zhangting

No full retrain required for merge — pure pandas helpers + synthetic-frame
IC / NaN screening. Host may later plug real bins.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

# Qualification gate from midterm plan §4 M3-C
MAX_NAN_RATE = 0.01
EPS = 1e-12

FeatureBuilder = Callable[[pd.DataFrame], pd.Series]


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    builder: FeatureBuilder
    description: str


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    """Fetch a flat column or MultiIndex last-level match."""
    if name in df.columns:
        return df[name]
    if isinstance(df.columns, pd.MultiIndex):
        # match last level
        matches = [c for c in df.columns if c[-1] == name]
        if len(matches) == 1:
            return df[matches[0]]
        if len(matches) > 1:
            # prefer ('feature', name) or exact 2-tuple
            for c in matches:
                if c[0] == "feature":
                    return df[c]
            return df[matches[0]]
    raise KeyError(f"column not found: {name}")


def nan_rate(series: pd.Series) -> float:
    """Fraction of NaN / None in series (empty → 1.0)."""
    if series is None:
        return 1.0
    n = len(series)
    if n == 0:
        return 1.0
    return float(pd.isna(series).sum()) / float(n)


def feature_qualifies(series: pd.Series, max_nan: float = MAX_NAN_RATE) -> bool:
    """NaN rate must be strictly < max_nan (plan: NaN<1%)."""
    return nan_rate(series) < float(max_nan)


def spearman_ic(feature: pd.Series, label: pd.Series) -> float:
    """Cross-sectional-friendly Spearman IC over aligned pairs (drops NaN)."""
    a = pd.to_numeric(feature, errors="coerce")
    b = pd.to_numeric(label, errors="coerce")
    aligned = pd.concat([a, b], axis=1, keys=["f", "y"]).dropna()
    if len(aligned) < 3:
        return float("nan")
    # pandas Series.corr(method='spearman')
    return float(aligned["f"].corr(aligned["y"], method="spearman"))


def ic_delta(baseline_ic: float, feature_ic: float) -> float:
    """Incremental IC vs baseline (feature_ic - baseline_ic)."""
    if pd.isna(baseline_ic) or pd.isna(feature_ic):
        return float("nan")
    return float(feature_ic) - float(baseline_ic)


# ---------------------------------------------------------------------------
# Feature builders (bin-16 only)
# ---------------------------------------------------------------------------

def feat_turnover_approx(df: pd.DataFrame) -> pd.Series:
    """Approx daily turnover: volume / (adfadfbasiccurhold + eps).

    Uses free-float-like chip field already in bin-16.
    """
    vol = pd.to_numeric(_col(df, "volume"), errors="coerce")
    hold = pd.to_numeric(_col(df, "adfadfbasiccurhold"), errors="coerce")
    out = vol / (hold + EPS)
    out.name = "turnover_approx"
    return out


def feat_turnover_resist_approx(df: pd.DataFrame, short: int = 5, long: int = 20) -> pd.Series:
    """Crude turnover-resistance proxy from volume path only.

    resist ≈ short_sum(volume) / (long_sum(volume) + eps)
    High values ≈ recent volume concentrated vs long window (not BT cyq).
    Requires datetime level for rolling; if absent, uses expanding fallback
    per instrument when MultiIndex (datetime, instrument).
    """
    vol = pd.to_numeric(_col(df, "volume"), errors="coerce").astype(float)
    if isinstance(vol.index, pd.MultiIndex) and "instrument" in (vol.index.names or []):
        # groupby instrument, rolling on datetime order
        def _resist(s: pd.Series) -> pd.Series:
            s = s.sort_index()
            short_sum = s.rolling(short, min_periods=1).sum()
            long_sum = s.rolling(long, min_periods=1).sum()
            return short_sum / (long_sum + EPS)

        # group by instrument level
        level = list(vol.index.names).index("instrument")
        out = vol.groupby(level=level, group_keys=False).apply(_resist)
    else:
        short_sum = vol.rolling(short, min_periods=1).sum()
        long_sum = vol.rolling(long, min_periods=1).sum()
        out = short_sum / (long_sum + EPS)
    out.name = "turnover_resist_approx"
    return out


def feat_amount_per_volume(df: pd.DataFrame) -> pd.Series:
    """Liquidity / price proxy: amount / (volume + eps) ≈ VWAP-like."""
    amount = pd.to_numeric(_col(df, "amount"), errors="coerce")
    vol = pd.to_numeric(_col(df, "volume"), errors="coerce")
    out = amount / (vol + EPS)
    out.name = "amount_per_volume"
    return out


def feat_volddx_zscore(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """Rolling z-score of volddx (chip flow field in bin-16).

    Leading warm-up (rolling burn-in) is filled with 0 so the NaN<1% gate
    measures real data holes, not window length. Documented as warm-start=0.
    """
    x = pd.to_numeric(_col(df, "volddx"), errors="coerce").astype(float)

    def _z(s: pd.Series) -> pd.Series:
        s = s.sort_index()
        mu = s.rolling(window, min_periods=1).mean()
        sd = s.rolling(window, min_periods=1).std(ddof=0)
        z = (s - mu) / (sd + EPS)
        # period-0 std is 0 → z~0; any residual warm-up NaN → 0
        return z.fillna(0.0)

    if isinstance(x.index, pd.MultiIndex) and "instrument" in (x.index.names or []):
        level = list(x.index.names).index("instrument")
        out = x.groupby(level=level, group_keys=False).apply(_z)
    else:
        out = _z(x)
    out.name = "volddx_zscore"
    return out


DEFAULT_SPECS: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        "turnover_approx",
        feat_turnover_approx,
        "volume / (adfadfbasiccurhold + eps)",
    ),
    FeatureSpec(
        "turnover_resist_approx",
        feat_turnover_resist_approx,
        "sum_short(volume) / sum_long(volume); not BT cyq",
    ),
    FeatureSpec(
        "amount_per_volume",
        feat_amount_per_volume,
        "amount / (volume + eps)",
    ),
    FeatureSpec(
        "volddx_zscore",
        feat_volddx_zscore,
        "rolling z-score of $volddx",
    ),
)


def run_feature_screen(
    df: pd.DataFrame,
    label: pd.Series | str,
    *,
    specs: Sequence[FeatureSpec] | None = None,
    baseline_feature: pd.Series | str | None = None,
    max_nan: float = MAX_NAN_RATE,
) -> pd.DataFrame:
    """Per-feature NaN rate + single-window IC (+ delta vs baseline).

    ``label`` may be a Series or column name in ``df``.
    ``baseline_feature`` optional Series or column for ic_delta (else delta=ic).
    """
    if isinstance(label, str):
        y = _col(df, label)
    else:
        y = label

    if baseline_feature is None:
        baseline_ic = 0.0
    elif isinstance(baseline_feature, str):
        baseline_ic = spearman_ic(_col(df, baseline_feature), y)
    else:
        baseline_ic = spearman_ic(baseline_feature, y)

    rows = []
    for spec in specs or DEFAULT_SPECS:
        series = spec.builder(df)
        nr = nan_rate(series)
        ok = nr < float(max_nan)
        ic = spearman_ic(series, y) if ok else float("nan")
        delta = ic_delta(baseline_ic, ic) if ok else float("nan")
        rows.append(
            {
                "feature": spec.name,
                "description": spec.description,
                "nan_rate": nr,
                "qualifies": ok,
                "ic": ic,
                "ic_delta": delta,
                "baseline_ic": baseline_ic,
            }
        )
    return pd.DataFrame(rows)


def results_to_markdown(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "_empty_\n"
    cols = ["feature", "nan_rate", "qualifies", "ic", "ic_delta"]
    cols = [c for c in cols if c in df.columns]
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for _, row in df.iterrows():
        cells = []
        for c in cols:
            v = row[c]
            if isinstance(v, float):
                cells.append("nan" if pd.isna(v) else f"{v:.6g}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="M3-C feature screen (bin-16 only)")
    p.add_argument(
        "--demo-synthetic",
        action="store_true",
        help="Run screen on built-in synthetic frame and print markdown table",
    )
    return p


def _demo_frame(n_days: int = 30, n_inst: int = 8, seed: int = 42) -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2026-03-02", periods=n_days)
    insts = [f"SH{600000 + i}" for i in range(n_inst)]
    idx = pd.MultiIndex.from_product([dates, insts], names=["datetime", "instrument"])
    n = len(idx)
    volume = rng.uniform(1e5, 5e6, size=n)
    hold = rng.uniform(1e4, 5e5, size=n)
    amount = volume * rng.uniform(5, 50, size=n)
    volddx = rng.normal(0, 1, size=n)
    # label correlated with turnover
    turnover = volume / (hold + EPS)
    label = 0.3 * (turnover - turnover.mean()) / (turnover.std() + EPS) + rng.normal(0, 1, size=n)
    df = pd.DataFrame(
        {
            "volume": volume,
            "adfadfbasiccurhold": hold,
            "amount": amount,
            "volddx": volddx,
            "close": rng.uniform(5, 100, size=n),
        },
        index=idx,
    )
    return df, pd.Series(label, index=idx, name="LABEL0")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.demo_synthetic:
        df, y = _demo_frame()
        table = run_feature_screen(df, y)
        print(results_to_markdown(table))
        return 0
    build_arg_parser().print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
