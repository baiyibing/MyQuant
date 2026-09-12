# -*- coding: utf-8 -*-
"""M3-C: feature_experiments pure helpers on synthetic frames."""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from feature_experiments import (  # noqa: E402
    MAX_NAN_RATE,
    feat_turnover_approx,
    feature_qualifies,
    ic_delta,
    nan_rate,
    run_feature_screen,
    spearman_ic,
)


def _synth(n_days=20, n_inst=6, seed=0, nan_frac=0.0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2026-03-02", periods=n_days)
    insts = [f"SH{600000 + i}" for i in range(n_inst)]
    idx = pd.MultiIndex.from_product([dates, insts], names=["datetime", "instrument"])
    n = len(idx)
    volume = rng.uniform(1e5, 2e6, size=n)
    hold = rng.uniform(1e4, 2e5, size=n)
    amount = volume * rng.uniform(8, 40, size=n)
    volddx = rng.normal(0, 1, size=n)
    turnover = volume / (hold + 1e-12)
    label = 0.5 * (turnover - turnover.mean()) / (turnover.std() + 1e-12)
    label = label + rng.normal(0, 0.2, size=n)
    df = pd.DataFrame(
        {
            "volume": volume,
            "adfadfbasiccurhold": hold,
            "amount": amount,
            "volddx": volddx,
            "close": rng.uniform(10, 80, size=n),
        },
        index=idx,
    )
    if nan_frac > 0:
        k = int(n * nan_frac)
        pos = rng.choice(n, size=k, replace=False)
        df.iloc[pos, df.columns.get_loc("volume")] = np.nan
    y = pd.Series(label, index=idx, name="LABEL0")
    return df, y


def test_nan_rate_and_qualify_gate():
    s = pd.Series([1.0, np.nan, 3.0, 4.0])
    assert nan_rate(s) == pytest.approx(0.25)
    assert feature_qualifies(s, max_nan=0.3) is True
    assert feature_qualifies(s, max_nan=0.01) is False
    clean = pd.Series(np.arange(100, dtype=float))
    assert nan_rate(clean) == 0.0
    assert feature_qualifies(clean) is True


def test_turnover_approx_and_positive_ic():
    df, y = _synth()
    feat = feat_turnover_approx(df)
    assert feat.name == "turnover_approx"
    assert feature_qualifies(feat)
    ic = spearman_ic(feat, y)
    assert ic > 0.2  # synthetic label built from turnover


def test_ic_delta():
    assert ic_delta(0.1, 0.25) == pytest.approx(0.15)
    assert np.isnan(ic_delta(float("nan"), 0.1))


def test_run_feature_screen_table_and_nan_disqualify():
    df, y = _synth(nan_frac=0.0)
    table = run_feature_screen(df, y)
    assert set(["feature", "nan_rate", "qualifies", "ic", "ic_delta"]).issubset(table.columns)
    assert (table["nan_rate"] < MAX_NAN_RATE).all()
    assert table["qualifies"].all()
    # turnover_approx should qualify with positive ic
    row = table.set_index("feature").loc["turnover_approx"]
    assert row["qualifies"] is True or bool(row["qualifies"]) is True
    assert row["ic"] > 0

    # High-NaN frame: force volume mostly NaN → turnover fails gate
    df2, y2 = _synth(nan_frac=0.5, seed=1)
    table2 = run_feature_screen(df2, y2)
    t_row = table2.set_index("feature").loc["turnover_approx"]
    assert t_row["qualifies"] in (False, np.False_)
    assert t_row["nan_rate"] >= MAX_NAN_RATE
    assert pd.isna(t_row["ic"])


def test_multiindex_feature_column_lookup():
    df, y = _synth()
    # wrap columns as MultiIndex feature/*
    df2 = df.copy()
    df2.columns = pd.MultiIndex.from_tuples([("feature", c) for c in df.columns])
    feat = feat_turnover_approx(df2)
    assert feature_qualifies(feat)
    assert spearman_ic(feat, y) > 0
