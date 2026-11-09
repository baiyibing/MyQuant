# -*- coding: utf-8 -*-
"""Direct pins for the current ``myquant_factors.price_bb`` behaviour.

Synthetic closes only. The factor module is not modified. No lake and no network.
"""

from __future__ import annotations

import inspect
import math
import warnings
from typing import cast

import numpy as np
import pandas as pd
import pytest

from myquant_factors.price_bb import bb_position


def _inline_population_position(close: np.ndarray, period: int, nbdev: float) -> float:
    """Bollinger position using population std (``np.std(..., ddof=0)``).

    Arithmetic order matches ``bb_position``: mean, std, upper, lower, width, ratio.
    The width gate is the module's ``band_width < 1e-8`` check.
    """
    window = np.asarray(close, dtype=np.float64)[-period:]
    mean = np.mean(window)
    std = np.std(window, ddof=0)
    upper = mean + nbdev * std
    lower = mean - nbdev * std
    band_width = upper - lower
    if band_width < 1e-8:
        return 0.5
    return float((window[-1] - lower) / band_width)


def test_only_public_function_is_bb_position() -> None:
    import myquant_factors
    import myquant_factors.price_bb as price_bb

    public_functions = [
        name
        for name, obj in vars(price_bb).items()
        if inspect.isfunction(obj) and not name.startswith("_")
    ]
    assert public_functions == ["bb_position"]
    assert myquant_factors.bb_position is price_bb.bb_position


def test_parameter_defaults_are_period_20_and_nbdev_2() -> None:
    signature = inspect.signature(bb_position)
    assert list(signature.parameters) == ["close", "period", "nbdev"]
    assert signature.parameters["period"].default == 20
    assert signature.parameters["nbdev"].default == 2.0
    assert bb_position.__annotations__ == {
        "close": "np.ndarray",
        "period": "int",
        "nbdev": "float",
        "return": "float",
    }

    head = np.full(5, -50.0)
    tail = np.arange(1.0, 21.0)
    assert tail.shape == (20,)
    series = np.concatenate([head, tail])
    assert bb_position(series) == bb_position(series, period=20, nbdev=2.0)
    assert bb_position(series) == bb_position(tail, period=20, nbdev=2.0)
    assert bb_position(series) == _inline_population_position(series, 20, 2.0)
    assert bb_position(series, period=25) != bb_position(series)
    assert bb_position(series, nbdev=1.0) != bb_position(series)


def test_normal_values_match_inline_population_reference() -> None:
    close = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    got = bb_position(close, period=5, nbdev=2.0)
    assert got == _inline_population_position(close, 5, 2.0)
    # mean = 3, population variance = 2, std = sqrt(2)
    # (5 - (3 - 2*sqrt(2))) / (4*sqrt(2)) = 1/2 + sqrt(2)/4
    assert float(np.std(close, ddof=0)) == math.sqrt(2.0)
    assert got == pytest.approx(0.5 + math.sqrt(2.0) / 4.0, rel=0, abs=1e-15)

    sample_std = float(np.std(close, ddof=1))
    assert sample_std == 1.5811388300841898
    sample_pos = (5.0 - (3.0 - 2.0 * sample_std)) / (4.0 * sample_std)
    assert abs(got - sample_pos) > 1e-2

    above = bb_position(close, period=5, nbdev=1.0)
    assert above == _inline_population_position(close, 5, 1.0)
    assert above == pytest.approx(0.5 + math.sqrt(2.0) / 2.0, rel=0, abs=1e-15)
    assert above > 1.0

    rev = np.array([5.0, 4.0, 3.0, 2.0, 1.0])
    below = bb_position(rev, period=5, nbdev=1.0)
    assert below == _inline_population_position(rev, 5, 1.0)
    assert below == pytest.approx(0.5 - math.sqrt(2.0) / 2.0, rel=0, abs=1e-15)
    assert below < 0.0

    centered = np.array([1.0, 3.0, 2.0])
    assert bb_position(centered, period=3, nbdev=2.0) == 0.5

    other = np.array([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
    assert bb_position(other, period=8, nbdev=2.0) == _inline_population_position(other, 8, 2.0)
    assert bb_position(other, period=8, nbdev=1.25) == _inline_population_position(other, 8, 1.25)


def test_series_longer_than_window_uses_tail_only() -> None:
    tail = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    prefixed = np.concatenate([np.array([100.0, -100.0, 0.0]), tail])
    assert bb_position(prefixed, period=5, nbdev=2.0) == bb_position(tail, period=5, nbdev=2.0)
    assert bb_position(prefixed, period=5, nbdev=2.0) == _inline_population_position(tail, 5, 2.0)
    assert bb_position(prefixed, period=8, nbdev=2.0) != bb_position(prefixed, period=5, nbdev=2.0)


def test_short_series_below_window_returns_one_half() -> None:
    assert bb_position(np.array([], dtype=np.float64)) == 0.5
    assert bb_position(np.array([np.nan], dtype=np.float64)) == 0.5
    assert bb_position(np.array([np.inf, -np.inf, np.nan]), period=4) == 0.5
    assert bb_position(np.array([1.0, 2.0, 3.0, 4.0]), period=5) == 0.5

    nineteen = np.arange(1.0, 20.0)
    assert nineteen.shape == (19,)
    assert bb_position(nineteen) == 0.5
    full = bb_position(nineteen, period=19, nbdev=2.0)
    assert full == _inline_population_position(nineteen, 19, 2.0)
    assert full != 0.5


def test_nan_inside_window_returns_nan() -> None:
    samples = (
        np.array([1.0, 2.0, np.nan, 4.0, 5.0]),
        np.array([1.0, 2.0, 3.0, 4.0, np.nan]),
        np.full(20, np.nan),
    )
    for close in samples:
        result = bb_position(close, period=len(close), nbdev=2.0)
        reference = _inline_population_position(close, len(close), 2.0)
        assert type(result) is float
        assert math.isnan(result)
        assert math.isnan(reference)


def test_nan_before_the_window_is_ignored() -> None:
    tail = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    close = np.concatenate([np.array([np.nan, np.nan]), tail])
    assert bb_position(close, period=5, nbdev=2.0) == bb_position(tail, period=5, nbdev=2.0)
    assert math.isfinite(bb_position(close, period=5, nbdev=2.0))


def test_constant_price_returns_one_half() -> None:
    samples = (
        np.full(20, 12.5),
        np.zeros(8),
        np.array([7.0, 7.0, 7.0, 7.0]),
        np.full(6, -3.0),
    )
    for close in samples:
        assert float(np.std(close, ddof=0)) == 0.0
        result = bb_position(close, period=len(close), nbdev=2.0)
        assert result == 0.5
        assert math.isfinite(result)
        assert result == _inline_population_position(close, len(close), 2.0)


def test_narrow_band_cutoff_returns_half_or_finite_ratio() -> None:
    """``band_width < 1e-8`` returns 0.5. Width equal to 1e-8 takes the ratio.

    Two-point window and ``nbdev=2``: population std is ``delta / 2``, so
    ``band_width = 2 * delta``.
    """
    varying = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert float(np.std(varying, ddof=0)) > 0.0
    assert bb_position(varying, period=5, nbdev=0.0) == 0.5
    assert bb_position(varying, period=5, nbdev=-2.0) == 0.5

    below = np.array([0.0, 4.9e-9])
    at_edge = np.array([0.0, 5e-9])
    assert float(np.std(below, ddof=0)) * 4.0 < 1e-8
    assert float(np.std(at_edge, ddof=0)) * 4.0 == 1e-8
    assert bb_position(below, period=2, nbdev=2.0) == 0.5

    ratio = bb_position(at_edge, period=2, nbdev=2.0)
    assert ratio == _inline_population_position(at_edge, 2, 2.0)
    assert ratio == pytest.approx(0.75, rel=0, abs=1e-15)
    assert math.isfinite(ratio)


def test_nonfinite_prices_inside_window_return_nan() -> None:
    samples = (
        np.array([1.0, 2.0, 3.0, 4.0, np.inf]),
        np.array([np.inf, np.inf]),
        np.array([-np.inf, 1.0, 2.0, 3.0]),
        np.array([1.0, np.inf, 3.0]),
    )
    for close in samples:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = bb_position(close, period=len(close), nbdev=2.0)
            reference = _inline_population_position(close, len(close), 2.0)
        assert type(result) is float
        assert math.isnan(result)
        assert math.isnan(reference)


def test_inputs_are_not_mutated_and_result_is_plain_float() -> None:
    dates = [
        "2024-01-02",
        "2024-01-03",
        "2024-01-04",
        "2024-01-05",
        "2024-01-08",
        "2024-01-09",
    ]
    frame = pd.DataFrame(
        {
            "close": [10.0, 11.0, 12.5, 12.0, 13.0, 14.0],
            "volume": [100, 110, 120, 130, 140, 150],
        },
        index=pd.Index(dates, name="date"),
    )
    original = frame.copy(deep=True)
    close = frame["close"].to_numpy()
    close_before = np.array(close, copy=True)
    result = bb_position(close, period=5, nbdev=2.0)
    assert type(result) is float
    assert result == _inline_population_position(close, 5, 2.0)
    np.testing.assert_array_equal(close, close_before)
    pd.testing.assert_frame_equal(frame, original)
    assert list(frame.columns) == ["close", "volume"]
    assert list(frame.index) == dates
    assert frame.index.name == "date"

    ints = np.array([1, 2, 3, 4, 5], dtype=np.int64)
    int_snapshot = ints.copy()
    int_result = bb_position(ints, period=5, nbdev=2.0)
    assert type(int_result) is float
    assert ints.dtype == np.int64
    np.testing.assert_array_equal(ints, int_snapshot)

    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    values_snapshot = values.copy()
    list_result = bb_position(cast(np.ndarray, values), period=5, nbdev=2.0)
    assert values == values_snapshot
    assert list_result == int_result

    base = np.arange(12, dtype=np.float64)
    base_snapshot = base.copy()
    view = base[::2]
    view_snapshot = view.copy()
    view_result = bb_position(view, period=4, nbdev=2.0)
    assert type(view_result) is float
    np.testing.assert_array_equal(base, base_snapshot)
    np.testing.assert_array_equal(view, view_snapshot)

    locked = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    locked.setflags(write=False)
    assert bb_position(locked, period=5, nbdev=2.0) == int_result
