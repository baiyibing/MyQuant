# -*- coding: utf-8 -*-
"""factor_analyze groups via pandas.qcut — no alphalens / empyrical."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
FACTOR_ANALYZE = REPO / "myquant_factors" / "factor_analyze.py"


def _ranked_factor_frame(n_stocks: int = 10) -> pd.DataFrame:
    dates = pd.to_datetime(["2026-01-05", "2026-01-06"])
    stocks = [f"{i:06d}.SZ" for i in range(n_stocks)]
    idx = pd.MultiIndex.from_product([dates, stocks], names=["date", "assert"])
    ranks = list(range(n_stocks)) * len(dates)
    return pd.DataFrame(
        {"mom": [float(v) for v in ranks], "next_ret": [0.01 * v for v in ranks]},
        index=idx,
    )


def test_factor_analyze_source_has_no_alphalens():
    text = FACTOR_ANALYZE.read_text(encoding="utf-8")
    assert "from alphalens" not in text
    assert "import alphalens" not in text
    assert "pd.qcut" in text


def test_import_factor_analyze_without_alphalens():
    import myquant_factors.factor_analyze as fa

    assert fa.quantize_factor.__module__ == "myquant_factors.factor_analyze"
    assert "alphalens" not in __import__("sys").modules
    assert "empyrical" not in __import__("sys").modules


def test_quantize_factor_five_equal_groups():
    from myquant_factors.factor_analyze import quantize_factor

    frame = _ranked_factor_frame(10)
    factor_only = cast(pd.DataFrame, frame.rename(columns={"mom": "factor"})[["factor"]])
    groups = quantize_factor(factor_only, quantiles=5)
    assert set(groups.unique()) == {1, 2, 3, 4, 5}
    one_day = groups.xs(pd.Timestamp("2026-01-05"), level=0)
    assert one_day.value_counts().sort_index().tolist() == [2, 2, 2, 2, 2]


def test_get_factor_group_returns_monotonic():
    from myquant_factors.factor_analyze import get_factor_group_returns

    out = get_factor_group_returns(_ranked_factor_frame(10), quantile=5)
    mom = out["mom"]
    assert list(mom.columns) == [1, 2, 3, 4, 5]
    # next_ret = 0.01 * rank; each quintile is two consecutive ranks
    pd.testing.assert_series_equal(
        mom.loc[pd.Timestamp("2026-01-05")],
        pd.Series([0.005, 0.025, 0.045, 0.065, 0.085], index=mom.columns, name=pd.Timestamp("2026-01-05")),
    )


def test_quantize_factor_no_raise_on_ties():
    from myquant_factors.factor_analyze import get_factor_group_returns, quantize_factor

    idx = pd.MultiIndex.from_product(
        [pd.to_datetime(["2026-01-05"]), ["000001.SZ", "000002.SZ", "000003.SZ"]],
        names=["date", "assert"],
    )
    tied = pd.DataFrame({"factor": [1.0, 1.0, 1.0], "next_ret": [0.01, 0.02, 0.03]}, index=idx)
    factor_only = cast(pd.DataFrame, tied[["factor"]])
    with pytest.raises(ValueError):
        quantize_factor(factor_only, quantiles=5, no_raise=False)
    groups = quantize_factor(factor_only, quantiles=5, no_raise=True)
    assert groups.empty
    out = get_factor_group_returns(
        tied.rename(columns={"factor": "mom"}),
        quantile=5,
        no_raise=True,
    )
    assert isinstance(out, pd.DataFrame)
