"""Score-compare helper for expanding-scaler last fold."""

from __future__ import annotations

import os
import sys

import pandas as pd

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from roll_cat_refit_lastfold import compare_scores  # noqa: E402


def test_identical_scores_full_overlap():
    rows = []
    for i, code in enumerate(["SH600000", "SZ000001", "SH600519"]):
        rows.append({"datetime": "2026-09-01", "instrument": code, "score": float(3 - i)})
    frame = pd.DataFrame(rows)
    out = compare_scores(frame, frame.copy())
    assert out["days"] == 1
    assert out["spearman_mean"] == 1.0
    assert out["top50_overlap_mean"] == 3
