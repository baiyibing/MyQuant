"""Per-fold RobustZScoreNorm uses only the train window."""

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

qlib = pytest.importorskip("qlib")

from roll_monthly_expanding_scaler import apply_robust_zscore  # noqa: E402


def _feature_frame() -> pd.DataFrame:
    idx = pd.MultiIndex.from_product(
        [pd.to_datetime(["2024-12-31", "2025-01-31", "2026-01-05"]), ["SH600000"]],
        names=["datetime", "instrument"],
    )
    cols = pd.MultiIndex.from_tuples([("feature", "F1"), ("label", "LABEL0")])
    data = np.array([[0.0, 0.1], [10.0, 0.2], [20.0, 0.3]], dtype=float)
    return pd.DataFrame(data, index=idx, columns=cols)


def test_scaler_fit_window_changes_test_value():
    raw = _feature_frame()
    early = apply_robust_zscore(raw, "2024-12-31", "2024-12-31")
    late = apply_robust_zscore(raw, "2024-12-31", "2025-01-31")
    test = pd.Timestamp("2026-01-05")
    v0 = float(early.loc[(test, "SH600000"), ("feature", "F1")])
    v1 = float(late.loc[(test, "SH600000"), ("feature", "F1")])
    assert v0 != pytest.approx(v1)
    assert np.isfinite(v0) and np.isfinite(v1)
