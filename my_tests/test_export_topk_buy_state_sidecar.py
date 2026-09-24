"""Convert D.features-shaped frames without importing qlib."""

from __future__ import annotations

import pandas as pd

from my_scripts.export_topk_buy_state_sidecar import (
    BUY_STATE_FIELDS,
    features_to_sidecar,
)


def test_features_to_sidecar_maps_qlib_codes_and_dollar_winratio():
    idx = pd.MultiIndex.from_tuples(
        [
            ("SH600000", pd.Timestamp("2026-01-06")),
            ("SZ000001", pd.Timestamp("2026-01-06")),
            ("SH600002", pd.Timestamp("2026-01-06")),
        ],
        names=["instrument", "datetime"],
    )
    frame = pd.DataFrame(
        {
            "$close": [9.0, 11.0, float("nan")],
            "Mean($close, 20)": [10.0, 10.0, 10.0],
            "Mean($close, 60)": [11.0, 12.0, 11.0],
            "$winratio": [0.05, 0.90, 0.01],
        },
        index=idx,
    )
    out = features_to_sidecar(frame)
    assert list(out.columns) == [
        "trade_date",
        "code",
        "close",
        "ma20",
        "ma60",
        "winratio",
    ]
    assert list(out["code"]) == ["600000.SH", "000001.SZ"]
    assert out.loc[0, "winratio"] == 0.05
    assert "600002.SH" not in set(out["code"])
    assert BUY_STATE_FIELDS[-1] == "$winratio"
    assert "Mean($close, 5)" not in BUY_STATE_FIELDS
    assert not any("Quantile" in f for f in BUY_STATE_FIELDS)
