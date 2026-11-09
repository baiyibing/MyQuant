"""Pin S25 strict-band boundaries and readiness guards for TR BB signals."""

import pandas as pd
import pytest

from myquant_factors.chip.bands import classify_tr_bb_signal


@pytest.fixture
def row() -> pd.Series:
    return pd.Series(
        {
            "turnover_resistance": 5.0,
            "tr_bb_upper": 4.0,
            "tr_bb_middle": 3.0,
            "tr_bb_lower": 2.0,
            "bands_computed_at": 1.0,
        },
        dtype=object,
    )


@pytest.mark.parametrize(
    ("tr", "expected"),
    [
        pytest.param(5.0, "TR_BREAKOUT", id="above-upper"),
        pytest.param(1.0, "TR_BREAKDOWN", id="below-lower"),
        pytest.param(4.0, None, id="at-upper"),
        pytest.param(2.0, None, id="at-lower"),
        pytest.param(3.0, None, id="inside-band"),
    ],
)
def test_strict_band_boundaries(
    row: pd.Series, tr: float, expected: str | None
) -> None:
    row["turnover_resistance"] = tr

    signal = classify_tr_bb_signal(row)

    assert signal == expected
    assert signal is None or isinstance(signal, str)


@pytest.mark.parametrize("tr", [5.0, 1.0], ids=["breakout", "breakdown"])
@pytest.mark.parametrize("missing", [False, True], ids=["nan", "missing"])
def test_uncomputed_bands_return_none(row: pd.Series, tr: float, missing: bool) -> None:
    row["turnover_resistance"] = tr
    if missing:
        row.pop("bands_computed_at")
    else:
        row["bands_computed_at"] = float("nan")

    assert classify_tr_bb_signal(row) is None


@pytest.mark.parametrize("tr", [5.0, 1.0], ids=["breakout", "breakdown"])
def test_nan_middle_returns_none(row: pd.Series, tr: float) -> None:
    row["turnover_resistance"] = tr
    row["tr_bb_middle"] = float("nan")

    assert classify_tr_bb_signal(row) is None


@pytest.mark.parametrize("tr", [5.0, 1.0], ids=["breakout", "breakdown"])
@pytest.mark.parametrize(
    "field", ["turnover_resistance", "tr_bb_upper", "tr_bb_lower"]
)
@pytest.mark.parametrize("value", [None, float("nan")], ids=["none", "nan"])
def test_none_or_nan_inputs_return_none(
    row: pd.Series, tr: float, field: str, value: float | None
) -> None:
    row["turnover_resistance"] = tr
    row[field] = value

    assert classify_tr_bb_signal(row) is None
