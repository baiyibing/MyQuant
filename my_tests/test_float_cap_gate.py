# -*- coding: utf-8 -*-
"""M3-D-B: fixtures for the derived float-cap verification gate.

Strong-correlation panel must pass; weak-correlation, thin-coverage and
low-bellwether panels must be rejected and leave the size method blocked.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from my_scripts.float_cap_gate import (
    AMOUNT_COLUMN,
    DEFAULT_BELLWETHERS,
    derive_log_float_cap,
    verify_float_cap,
)
from my_scripts.ranking_neutralize import neutralize

DAYS = tuple(pd.Timestamp(day) for day in ("2026-03-02", "2026-03-03", "2026-03-04"))
BELLWETHER = "SH600519"


def _panel(
    *,
    corr: str = "strong",
    nan_codes: tuple[str, ...] = (),
    bellwether_rank: int = 0,
    days: tuple[pd.Timestamp, ...] = DAYS,
) -> pd.DataFrame:
    """Build a cap/amount panel with a controllable cap↔amount relationship.

    ``corr='strong'`` makes amount a monotone function of the cap (the real
    world anchor); ``corr='weak'`` scrambles the pairing with a fixed
    permutation so the daily rank correlation collapses toward zero.
    ``bellwether_rank`` positions 600519 in the cap ordering: 0 is the largest.
    """
    others = [f"SZ00{index:04d}" for index in range(19)]
    codes = list(others)
    codes.insert(bellwether_rank, BELLWETHER)
    caps = np.linspace(24.0, 20.0, num=len(codes))  # index 0 = largest

    rows = []
    for day_index, day in enumerate(days):
        amounts = np.exp(caps) / 40.0
        if corr == "weak":
            amounts = amounts[np.random.default_rng(day_index).permutation(len(codes))]
        for position, code in enumerate(codes):
            cap = caps[position] + 0.01 * day_index
            rows.append(
                {
                    "datetime": day,
                    "instrument": code,
                    "log_float_cap": np.nan if code in nan_codes else cap,
                    AMOUNT_COLUMN: float(amounts[position]),
                }
            )
    return pd.DataFrame(rows)


def test_strong_correlation_panel_passes_the_gate():
    report = verify_float_cap(_panel())

    assert report.passed is True
    assert report.size_blocked is False
    assert report.reasons == ()
    assert report.nan_rate == 0.0
    assert report.median_rank_corr == pytest.approx(1.0)
    assert report.corr_days == len(DAYS)
    assert report.bellwether_percentiles[BELLWETHER] == pytest.approx(1.0)
    assert set(report.bellwethers_missing) == set(DEFAULT_BELLWETHERS) - {BELLWETHER}


def test_weak_correlation_panel_is_rejected():
    report = verify_float_cap(_panel(corr="weak"))

    assert report.passed is False
    assert report.size_blocked is True
    assert report.median_rank_corr is not None and report.median_rank_corr <= 0.5
    assert any("rank-corr" in reason for reason in report.reasons)


def test_nan_rate_above_one_percent_is_rejected():
    panel = _panel(nan_codes=("SZ000000", "SZ000001"))

    report = verify_float_cap(panel)

    assert report.passed is False
    assert report.nan_rate == pytest.approx(2 / 20)
    assert any("NaN rate" in reason for reason in report.reasons)


def test_a_single_nan_row_stays_under_the_coverage_threshold():
    # 1 / 60 rows ≈ 1.7% would fail the gate; 1 / 200 is inside the budget.
    long_days = tuple(DAYS[0] + pd.Timedelta(days=offset) for offset in range(10))
    panel = _panel(days=long_days)
    panel.loc[0, "log_float_cap"] = np.nan

    report = verify_float_cap(panel)

    assert report.nan_rate < 0.01
    assert report.passed is True


def test_bellwether_ranked_low_is_rejected():
    report = verify_float_cap(_panel(bellwether_rank=19))

    assert report.passed is False
    assert report.bellwether_percentiles[BELLWETHER] < 0.9
    assert any("bellwether" in reason for reason in report.reasons)


def test_missing_amount_panel_is_rejected_rather_than_assumed():
    panel = _panel().drop(columns=[AMOUNT_COLUMN])

    report = verify_float_cap(panel)

    assert report.passed is False
    assert report.median_rank_corr is None
    assert any(AMOUNT_COLUMN in reason for reason in report.reasons)


def test_empty_panel_is_rejected():
    report = verify_float_cap(pd.DataFrame(columns=["datetime", "instrument", "log_float_cap"]))

    assert report.passed is False
    assert report.reasons == ("empty cap panel",)


def test_amount_can_be_supplied_as_a_separate_panel():
    panel = _panel()
    caps = panel[["datetime", "instrument", "log_float_cap"]]
    amounts = panel[["datetime", "instrument", AMOUNT_COLUMN]]

    report = verify_float_cap(caps, amounts)

    assert report.passed is True
    assert report.median_rank_corr == pytest.approx(1.0)


def test_derive_log_float_cap_from_close_times_float_shares():
    frame = pd.DataFrame(
        [
            {"datetime": "2026-03-02", "instrument": "600519", "$close": 1500.0, "$adfadfbasiccurhold": 1.0e9},
            {"datetime": "2026-03-02", "instrument": "SZ000001", "$close": 10.0, "$adfadfbasiccurhold": 1.9e10},
            {"datetime": "2026-03-02", "instrument": "SZ000002", "$close": np.nan, "$adfadfbasiccurhold": 1.0e9},
            {"datetime": "2026-03-02", "instrument": "SZ000003", "$close": 0.0, "$adfadfbasiccurhold": 1.0e9},
        ]
    )

    out = derive_log_float_cap(frame)

    assert out["instrument"].tolist() == ["SH600519", "SZ000001", "SZ000002", "SZ000003"]
    assert out.loc[0, "log_float_cap"] == pytest.approx(np.log(1500.0 * 1.0e9))
    assert np.isnan(out.loc[2, "log_float_cap"])
    assert np.isnan(out.loc[3, "log_float_cap"])
    assert out["datetime"].tolist() == [pd.Timestamp("2026-03-02")] * 4


def test_derive_log_float_cap_requires_the_bin16_columns():
    frame = pd.DataFrame([{"datetime": "2026-03-02", "instrument": "600519", "$close": 1.0}])
    with pytest.raises(ValueError, match=r"\$adfadfbasiccurhold"):
        derive_log_float_cap(frame)


def test_derive_log_float_cap_carries_amount_through_for_the_gate():
    frame = pd.DataFrame(
        [
            {
                "datetime": "2026-03-02",
                "instrument": code,
                "$close": 10.0 * (index + 1),
                "$adfadfbasiccurhold": 1.0e9,
                AMOUNT_COLUMN: 1.0e8 * (index + 1),
            }
            for index, code in enumerate(["SZ000001", "SZ000002", "SZ000003", "SZ000004", "SZ000005"])
        ]
    )

    derived = derive_log_float_cap(frame)
    report = verify_float_cap(derived, bellwethers=())

    assert AMOUNT_COLUMN in derived.columns
    assert report.median_rank_corr == pytest.approx(1.0)
    # No bellwether requested: the other two checks decide.
    assert report.passed is True


def test_blocked_gate_leaves_industry_available_and_size_refused():
    """The blocked path: a failing gate must not silently degrade to a fit."""
    report = verify_float_cap(_panel(corr="weak"))
    assert report.size_blocked is True
    assert "size neutralization blocked" in report.blocked_message()

    scores = pd.DataFrame(
        [
            {"datetime": DAYS[0], "instrument": "SH600519", "score": 1.0},
            {"datetime": DAYS[0], "instrument": "SZ000001", "score": 2.0},
            {"datetime": DAYS[0], "instrument": "SZ000002", "score": 3.0},
        ]
    )
    mapping = {"SH600519": "食品饮料", "SZ000001": "银行", "SZ000002": "房地产"}

    frame, industry_report = neutralize(scores, "industry", sw_l1=mapping)

    assert industry_report.method == "industry"
    assert len(frame) == 3


def test_report_manifest_fields_are_json_safe():
    import json

    fields = verify_float_cap(_panel()).as_manifest_fields()
    assert json.loads(json.dumps(fields))["float_cap_gate_passed"] is True
    assert fields["float_cap_gate_reasons"] == []
    assert fields["float_cap_gate_median_rank_corr"] == pytest.approx(1.0)
