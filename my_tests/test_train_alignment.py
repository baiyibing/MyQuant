"""走查优先级5：pred.pkl 与 report_normal_1day 首尾对齐自检。"""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from train_wiring import check_pred_report_alignment  # noqa: E402


def test_aligned_no_error():
    pred = pd.to_datetime(["2026-03-02", "2026-03-03", "2026-03-04"])
    report = pd.to_datetime(["2026-03-02", "2026-03-03", "2026-03-04"])
    facts = check_pred_report_alignment(pred, report)
    assert facts["pred_first"] == pd.Timestamp("2026-03-02")
    assert facts["report_last"] == pd.Timestamp("2026-03-04")
    assert facts["report_days_missing_from_pred"] == 0


def test_report_before_pred_raises():
    pred = pd.to_datetime(["2026-03-03", "2026-03-04"])
    report = pd.to_datetime(["2026-03-02", "2026-03-03"])
    with pytest.raises(ValueError, match="早于 pred 首日"):
        check_pred_report_alignment(pred, report)


def test_disjoint_raises():
    pred = pd.to_datetime(["2026-03-02", "2026-03-03"])
    report = pd.to_datetime(["2026-04-01", "2026-04-02"])
    with pytest.raises(ValueError, match="完全不相交"):
        check_pred_report_alignment(pred, report)


def test_partial_missing_warns_not_raises(capsys):
    pred = pd.to_datetime(["2026-03-02", "2026-03-03", "2026-03-05"])
    report = pd.to_datetime(["2026-03-02", "2026-03-04", "2026-03-05"])
    facts = check_pred_report_alignment(pred, report)
    assert facts["report_days_missing_from_pred"] == 1
    assert "警告" in capsys.readouterr().out


def test_duplicates_are_collapsed():
    pred = pd.to_datetime(["2026-03-02", "2026-03-02", "2026-03-03"])
    report = pd.to_datetime(["2026-03-02", "2026-03-03"])
    facts = check_pred_report_alignment(pred, report)
    assert facts["report_days_missing_from_pred"] == 0


def test_empty_raises():
    with pytest.raises(ValueError, match="日期为空"):
        check_pred_report_alignment([], pd.to_datetime(["2026-03-02"]))
