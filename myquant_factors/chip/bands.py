# -*- coding: utf-8 -*-
"""Turnover-resistance Bollinger Bands (TR BB) — rolling computation helpers."""

from __future__ import annotations

from typing import Literal, Optional, cast

import numpy as np
import pandas as pd

TR_BB_SIGNAL = Literal["TR_BREAKOUT", "TR_BREAKDOWN"]

_TR_BB_OUTPUT_COLS = (
    "tr_bb_upper",
    "tr_bb_middle",
    "tr_bb_lower",
    "tr_bb_position",
    "tr_bb_width",
    "tr_bb_free_upper",
    "tr_bb_free_middle",
    "tr_bb_free_lower",
    "tr_bb_free_position",
    "tr_bb_free_width",
)


def tr_bollinger_bands(
    tr_series: pd.Series,
    period: int = 20,
    nbdev: float = 2.0,
    ddof: int = 1,
) -> dict[str, float]:
    """Compute turnover-resistance Bollinger Bands for the last point in *tr_series*.

    *tr_series* must be sorted by date ascending (oldest first).
    """
    valid = tr_series.dropna()
    if len(valid) < period:
        return {
            "tr_bb_upper": float("nan"),
            "tr_bb_middle": float("nan"),
            "tr_bb_lower": float("nan"),
            "tr_bb_position": 0.5,
            "tr_bb_width": float("nan"),
        }

    roll = tr_series.rolling(window=period, min_periods=period)
    ma = cast(pd.Series, roll.mean()).iloc[-1]
    std = cast(pd.Series, roll.std(ddof=ddof)).iloc[-1]

    upper = ma + nbdev * std
    lower = ma - nbdev * std
    last_tr = tr_series.iloc[-1]

    if pd.notna(last_tr) and pd.notna(upper) and pd.notna(lower) and upper > lower:
        position = (last_tr - lower) / (upper - lower)
    else:
        position = 0.5

    width = (upper - lower) / abs(ma) if pd.notna(ma) and abs(ma) > 1e-8 else float("nan")

    return {
        "tr_bb_upper": round(float(upper), 4) if pd.notna(upper) else float("nan"),
        "tr_bb_middle": round(float(ma), 4) if pd.notna(ma) else float("nan"),
        "tr_bb_lower": round(float(lower), 4) if pd.notna(lower) else float("nan"),
        "tr_bb_position": round(float(position), 4),
        "tr_bb_width": round(float(width), 4) if pd.notna(width) else float("nan"),
    }


def _prefix_bb_columns(
    tr_series: pd.Series,
    prefix: str,
    *,
    period: int,
    nbdev: float,
    ddof: int,
) -> pd.DataFrame:
    """Vectorized TR BB columns for one stock series (index aligned)."""
    roll = tr_series.rolling(window=period, min_periods=period)
    ma = cast(pd.Series, roll.mean())
    std = cast(pd.Series, roll.std(ddof=ddof))
    upper = ma + nbdev * std
    lower = ma - nbdev * std

    band_width = upper - lower
    position = pd.Series(0.5, index=tr_series.index, dtype="float64")
    valid_pos = (
        band_width.notna()
        & (band_width > 0)
        & tr_series.notna()
        & upper.notna()
        & lower.notna()
    )
    position.loc[valid_pos] = (tr_series.loc[valid_pos] - lower.loc[valid_pos]) / band_width.loc[valid_pos]

    width = pd.Series(np.nan, index=tr_series.index, dtype="float64")
    width_valid = ma.notna() & (ma.abs() > 1e-8) & band_width.notna()
    width.loc[width_valid] = band_width.loc[width_valid] / ma.loc[width_valid].abs()

    return pd.DataFrame(
        {
            f"{prefix}_upper": upper.round(4),
            f"{prefix}_middle": ma.round(4),
            f"{prefix}_lower": lower.round(4),
            f"{prefix}_position": position.round(4),
            f"{prefix}_width": width.round(4),
        },
        index=tr_series.index,
    )


def compute_tr_bb_columns(
    df: pd.DataFrame,
    *,
    period: int = 20,
    nbdev: float = 2.0,
    ddof: int = 1,
) -> pd.DataFrame:
    """Add ``tr_bb_*`` and ``tr_bb_free_*`` columns for all rows in *df*.

    Expects columns ``stock_code``, ``trade_date``, ``turnover_resistance``,
    ``turnover_resistance_free``. Rows must be per-stock sparse trading-day series.
    """
    if df.empty:
        return df.copy()

    required = {"stock_code", "trade_date", "turnover_resistance", "turnover_resistance_free"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"compute_tr_bb_columns missing columns: {sorted(missing)}")

    parts: list[pd.DataFrame] = []
    drop_cols = list(_TR_BB_OUTPUT_COLS)
    for _, group in df.sort_values(["stock_code", "trade_date"]).groupby(
        "stock_code", sort=False
    ):
        g = group.copy()
        g = g.drop(columns=[c for c in drop_cols if c in g.columns], errors="ignore")
        circ = _prefix_bb_columns(
            pd.Series(g["turnover_resistance"]),
            "tr_bb",
            period=period,
            nbdev=nbdev,
            ddof=ddof,
        )
        free = _prefix_bb_columns(
            pd.Series(g["turnover_resistance_free"]),
            "tr_bb_free",
            period=period,
            nbdev=nbdev,
            ddof=ddof,
        )
        parts.append(pd.concat([g, circ, free], axis=1))

    return pd.concat(parts, ignore_index=True)


def classify_tr_bb_signal(row: pd.Series) -> Optional[str]:
    """Return MVP TR BB signal or None when bands are not ready."""
    if bool(pd.isna(row.get("bands_computed_at"))) or bool(pd.isna(row.get("tr_bb_middle"))):
        return None
    tr = row.get("turnover_resistance")
    upper = row.get("tr_bb_upper")
    lower = row.get("tr_bb_lower")
    if tr is None or upper is None or lower is None:
        return None
    if pd.isna(tr) or pd.isna(upper) or pd.isna(lower):
        return None
    if tr > upper:
        return "TR_BREAKOUT"
    if tr < lower:
        return "TR_BREAKDOWN"
    return None
