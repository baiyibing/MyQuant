"""Pure fold math for Cat monthly expanding walk-forward."""

from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from roll_cat_monthly import monthly_folds  # noqa: E402


def test_first_fold_matches_base_split():
    folds = monthly_folds()
    assert folds[0]["train"] == ("2020-01-01", "2024-12-31")
    assert folds[0]["valid"] == ("2025-01-01", "2025-12-31")
    assert folds[0]["test"] == ("2026-01-01", "2026-01-31")


def test_second_fold_expands_train_one_month():
    folds = monthly_folds()
    assert folds[1]["train"] == ("2020-01-01", "2025-01-31")
    assert folds[1]["valid"] == ("2025-02-01", "2026-01-31")
    assert folds[1]["test"] == ("2026-02-01", "2026-02-28")


def test_last_fold_clips_september_2026():
    folds = monthly_folds()
    assert len(folds) == 9
    assert folds[-1]["train"] == ("2020-01-01", "2025-08-31")
    assert folds[-1]["valid"] == ("2025-09-01", "2026-08-31")
    assert folds[-1]["test"] == ("2026-09-01", "2026-09-14")
