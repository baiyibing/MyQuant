# -*- coding: utf-8 -*-
"""M3-D-A: synthetic fixtures for cross-section industry / size neutralization."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from my_scripts.ranking_neutralize import (
    NeutralizeReport,
    industry_demean,
    industry_size_neutral,
    load_industry_map,
    main,
    neutralize,
    size_residual,
    to_bare_code,
    to_qlib_code,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_MAP = REPO_ROOT / "exports" / "m3d_industry" / "sw_l1_map.csv"

DAYS = ("2026-03-02", "2026-03-03")


def _industry_fixture() -> tuple[pd.DataFrame, dict[str, str]]:
    """Two days x two industries, each industry carrying a constant offset.

    Industry demean must delete the offsets and leave the within-industry
    spread intact.
    """
    offsets = {"银行": 10.0, "电子": -4.0}
    members = {"银行": ["SH600000", "SH600016", "SH601398"], "电子": ["SZ000725", "SZ300190"]}
    rows = []
    for day_index, day in enumerate(DAYS):
        for industry, codes in members.items():
            for rank, code in enumerate(codes):
                rows.append(
                    {
                        "datetime": day,
                        "instrument": code,
                        "score": offsets[industry] + rank - day_index * 0.5,
                    }
                )
    mapping = {code: industry for industry, codes in members.items() for code in codes}
    return pd.DataFrame(rows), mapping


def _size_fixture(slope: float = 3.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """score = alpha + slope * log_cap, so the OLS residual is pure alpha."""
    codes = [f"SH60{index:04d}" for index in range(8)]
    caps = np.linspace(20.0, 24.0, num=len(codes))
    alpha = np.array([0.4, -0.3, 0.1, 0.9, -0.7, 0.2, -0.4, -0.2])
    score_rows = []
    cap_rows = []
    for day_index, day in enumerate(DAYS):
        stamp = pd.Timestamp(day)
        for position, code in enumerate(codes):
            cap = caps[position] + 0.01 * day_index
            score_rows.append(
                {
                    "datetime": stamp,
                    "instrument": code,
                    "score": 1.5 + slope * cap + alpha[position],
                }
            )
            cap_rows.append({"datetime": stamp, "instrument": code, "log_float_cap": cap})
    return pd.DataFrame(score_rows), pd.DataFrame(cap_rows)


def test_industry_demean_zeroes_each_daily_industry_mean():
    scores, mapping = _industry_fixture()

    frame, report = industry_demean(scores, mapping)

    frame["sw_l1"] = frame["instrument"].map(mapping)
    means = frame.groupby(["datetime", "sw_l1"])["score"].mean()
    assert np.allclose(means.to_numpy(), 0.0, atol=1e-12)
    # Within-industry ordering survives: only the industry offset is removed.
    bank = frame[frame["sw_l1"] == "银行"].sort_values(["datetime", "instrument"])
    assert np.allclose(bank["score"].to_numpy()[:3], [-1.0, 0.0, 1.0])
    assert report.method == "industry"
    assert (report.rows, report.days) == (10, 2)
    assert report.industry_bypass_rows == 0
    assert report.industry_bypass_instruments == ()


def test_industry_demean_bypasses_unmapped_names_and_counts_them():
    scores, mapping = _industry_fixture()
    extra = pd.DataFrame(
        [{"datetime": day, "instrument": "SZ301999", "score": 99.0} for day in DAYS]
    )
    scores = pd.concat([scores, extra], ignore_index=True)

    frame, report = industry_demean(scores, mapping)

    unmapped = frame[frame["instrument"] == "SZ301999"]
    assert unmapped["score"].tolist() == [99.0, 99.0]
    assert report.industry_bypass_rows == 2
    assert report.industry_bypass_instruments == ("SZ301999",)
    # The unmapped name must not drag the industry means it does not belong to.
    frame["sw_l1"] = frame["instrument"].map(mapping)
    means = frame.dropna(subset=["sw_l1"]).groupby(["datetime", "sw_l1"])["score"].mean()
    assert np.allclose(means.to_numpy(), 0.0, atol=1e-12)


def test_industry_demean_matches_bare_codes_against_the_qlib_map():
    scores, mapping = _industry_fixture()
    scores["instrument"] = [to_bare_code(code) for code in scores["instrument"]]

    frame, report = industry_demean(scores, mapping)

    assert report.industry_bypass_rows == 0
    assert set(frame["instrument"]) == {"600000", "600016", "601398", "000725", "300190"}


def test_size_residual_kills_the_size_exposure():
    scores, caps = _size_fixture()

    frame, report = size_residual(scores, caps)

    merged = frame.merge(caps, on=["datetime", "instrument"])
    for _, day in merged.groupby("datetime"):
        assert abs(np.corrcoef(day["score"], day["log_float_cap"])[0, 1]) < 1e-10
        assert abs(day["score"].mean()) < 1e-10
    assert report.method == "size"
    assert (report.size_bypass_rows, report.size_skipped_days) == (0, 0)


def test_size_residual_bypasses_nan_caps_and_counts_them():
    scores, caps = _size_fixture()
    caps.loc[caps["instrument"] == "SH600003", "log_float_cap"] = np.nan
    raw = scores.set_index(["datetime", "instrument"])["score"]

    frame, report = size_residual(scores, caps)

    held = frame.set_index(["datetime", "instrument"])["score"]
    for day in DAYS:
        key = (pd.Timestamp(day), "SH600003")
        assert held[key] == raw[key]
    assert report.size_bypass_rows == 2
    assert report.size_skipped_days == 0


def test_size_residual_skips_degenerate_days_whole():
    scores, caps = _size_fixture()
    flat_day = pd.Timestamp(DAYS[1])
    caps.loc[pd.to_datetime(caps["datetime"]) == flat_day, "log_float_cap"] = 22.0
    raw = scores.set_index(["datetime", "instrument"])["score"]

    frame, report = size_residual(scores, caps)

    held = frame.set_index(["datetime", "instrument"])["score"]
    for code in caps["instrument"].unique():
        assert held[(flat_day, code)] == raw[(flat_day, code)]
    assert report.size_skipped_days == 1
    assert report.size_bypass_rows == 8


def test_size_residual_skips_days_thinner_than_the_regression_minimum():
    scores = pd.DataFrame(
        [
            {"datetime": DAYS[0], "instrument": "SH600000", "score": 1.0},
            {"datetime": DAYS[0], "instrument": "SH600016", "score": 2.0},
        ]
    )
    caps = pd.DataFrame(
        [
            {"datetime": DAYS[0], "instrument": "SH600000", "log_float_cap": 20.0},
            {"datetime": DAYS[0], "instrument": "SH600016", "log_float_cap": 23.0},
        ]
    )

    frame, report = size_residual(scores, caps)

    assert frame["score"].tolist() == [1.0, 2.0]
    assert (report.size_skipped_days, report.size_bypass_rows) == (1, 2)


def test_industry_size_neutral_removes_size_exposure_and_merges_bypass_counts():
    scores, caps = _size_fixture()
    # Half the cross-section in each industry, plus one name the map misses.
    mapping = {code: ("银行" if index < 4 else "电子") for index, code in enumerate(sorted(set(scores["instrument"])))}
    mapping.pop("SH600007")
    caps.loc[caps["instrument"] == "SH600001", "log_float_cap"] = np.nan

    frame, report = industry_size_neutral(scores, mapping, caps)

    merged = frame.merge(caps, on=["datetime", "instrument"]).dropna(subset=["log_float_cap"])
    for _, day in merged.groupby("datetime"):
        assert abs(np.corrcoef(day["score"], day["log_float_cap"])[0, 1]) < 1e-10
    assert report.method == "both"
    assert report.industry_bypass_rows == 2
    assert report.industry_bypass_instruments == ("SH600007",)
    assert report.size_bypass_rows == 2
    assert (report.rows, report.days) == (16, 2)


def test_neutralize_dispatch_requires_its_inputs():
    scores, mapping = _industry_fixture()
    with pytest.raises(ValueError, match="unsupported neutralize method"):
        neutralize(scores, "momentum", sw_l1=mapping)
    with pytest.raises(ValueError, match="industry map"):
        neutralize(scores, "industry")
    with pytest.raises(ValueError, match="log float cap"):
        neutralize(scores, "size")
    with pytest.raises(ValueError, match="log float cap"):
        neutralize(scores, "both", sw_l1=mapping)


def test_neutralize_never_drops_or_reorders_rows():
    scores, mapping = _industry_fixture()
    frame, _ = neutralize(scores, "industry", sw_l1=mapping)
    assert frame["instrument"].tolist() == scores["instrument"].tolist()
    assert len(frame) == len(scores)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("SZ300190", "SZ300190"),
        ("sz300190", "SZ300190"),
        ("300190.SZ", "SZ300190"),
        ("300190", "SZ300190"),
        ("600000", "SH600000"),
        ("600000.SH", "SH600000"),
        ("900901", "SH900901"),
        ("920014", "BJ920014"),
        ("430047", "BJ430047"),
        ("000001", "SZ000001"),
        ("FOO", None),
        ("SH12", None),
        ("", None),
        (None, None),
    ],
)
def test_dialect_normalization(raw, expected):
    assert to_qlib_code(raw) == expected
    assert to_bare_code(raw) == (None if expected is None else expected[2:])


def test_load_industry_map_reads_the_shipped_sw_l1_map():
    mapping = load_industry_map(REAL_MAP)
    assert len(mapping) >= 5000
    assert mapping["SH600000"] == "银行"
    assert mapping[to_qlib_code("600519")] == "食品饮料"


def test_load_industry_map_skips_unusable_rows(tmp_path):
    path = tmp_path / "map.csv"
    path.write_text(
        "code_qlib,code_gildata,name,sw_l1\n"
        "SH600000,600000.SH,浦发银行,银行\n"
        "NOPE,x,坏码,银行\n"
        "SZ300190,300190.SZ,美晨科技,\n",
        encoding="utf-8",
    )
    assert load_industry_map(path) == {"SH600000": "银行"}


def test_load_industry_map_rejects_a_map_without_industries(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("code_qlib,name\nSH600000,浦发银行\n", encoding="utf-8")
    with pytest.raises(ValueError, match="sw_l1"):
        load_industry_map(path)


def test_load_industry_map_reads_wind_l1_schema(tmp_path):
    path = tmp_path / "wind_l1_map.csv"
    path.write_text(
        "code_gildata,name,wind_sw_l1\n"
        "600000.SH,浦发银行,银行\n"
        "300190.SZ,美晨科技,汽车\n",
        encoding="utf-8",
    )
    assert load_industry_map(path) == {"SH600000": "银行", "SZ300190": "汽车"}


def test_report_manifest_fields_are_json_safe_ints():
    report = NeutralizeReport(
        method="both",
        rows=10,
        days=2,
        industry_bypass_rows=2,
        industry_bypass_instruments=("SZ301999",),
        size_bypass_rows=1,
        size_skipped_days=1,
    )
    fields = report.as_manifest_fields()
    assert fields["neutralize"] == "both"
    assert fields["neutralize_industry_bypass_instruments"] == 1
    assert all(isinstance(value, int) for key, value in fields.items() if key != "neutralize")


def test_cli_writes_a_neutralized_score_table(tmp_path, capsys):
    scores, mapping = _industry_fixture()
    pred = tmp_path / "pred.csv"
    scores.to_csv(pred, index=False)
    map_path = tmp_path / "map.csv"
    pd.DataFrame(
        [{"code_qlib": code, "code_gildata": "", "name": "", "sw_l1": industry} for code, industry in mapping.items()]
    ).to_csv(map_path, index=False)
    out = tmp_path / "nested" / "neutral.csv"

    assert main(["--pred", str(pred), "--out", str(out), "--method", "industry", "--industry-map", str(map_path)]) == 0

    written = pd.read_csv(out, dtype={"instrument": str})
    assert list(written.columns) == ["datetime", "instrument", "score"]
    assert abs(written["score"].sum()) < 1e-9
    assert "method=industry" in capsys.readouterr().out
