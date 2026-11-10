"""Qlib must request chip warmup and retain date alignment across missing inputs."""
import numpy as np
import pandas as pd
import pytest
from qlib.data.base import Feature

from myquant_factors.cyq_ops import ASR_T, CYQK_C_T


@pytest.mark.parametrize("operator", [ASR_T, CYQK_C_T])
def test_chip_operators_request_their_full_lookback(operator):
    features = [Feature(name) for name in ("close", "high", "low", "vol", "turnover_rate")]
    expression = operator(*features, 80)
    assert expression.get_extended_window_size() == (79, 0)
    assert expression.get_longest_back_rolling() == 79


def test_missing_input_does_not_shift_results_to_another_date(monkeypatch):
    from myquant_factors import cyq_ops
    columns = {"close": [20., 21., np.nan, 20., 21., 20.],
               "high": [22.] * 6, "low": [19.] * 6, "vol": [1000.] * 6,
               "turnover_rate": [.02] * 6}
    series = {f"${name}": pd.Series(values, name=f"${name}") for name, values in columns.items()}
    monkeypatch.setattr(Feature, "load", lambda self, *a: series[str(self)])
    monkeypatch.setattr(cyq_ops, "calc_dist_chips",
                        lambda *a, **kw: pd.Series([1., 2., 1.], index=[10., 20., 30.]))
    expression = ASR_T(*(Feature(name) for name in columns), 3)
    result = expression._load_internal("SH600000", 0, 5)
    assert result.index.tolist() == list(range(6))
    assert result.iloc[:3].isna().all()
    assert np.isfinite(result.iloc[3:]).all()
