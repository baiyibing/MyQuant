# -*- coding: utf-8 -*-
"""M3-A: learn-only DropLimitUpLearn / drop_limit_up_rows 样本数断言。"""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
# Force my_scripts ahead of qlib_scripts: earlier tests (e.g. test_csv_float_scan)
# may have inserted qlib_scripts at front; a mere "not in path" check then skips
# insert and bare `import custom_handler` hits the wrong file.
while _MY_SCRIPTS in sys.path:
    sys.path.remove(_MY_SCRIPTS)
sys.path.insert(0, _MY_SCRIPTS)
_ch = sys.modules.get("custom_handler")
if _ch is not None:
    _origin = os.path.abspath(getattr(_ch, "__file__", "") or "")
    if not _origin.startswith(os.path.abspath(_MY_SCRIPTS) + os.sep):
        del sys.modules["custom_handler"]

from custom_handler import (  # noqa: E402
    DropLimitUpLearn,
    _DEFAULT_INFER_PROCESSORS,
    _DEFAULT_LEARN_PROCESSORS,
    drop_limit_up_rows,
)


def _flat_frame():
    idx = pd.MultiIndex.from_product(
        [pd.to_datetime(["2026-03-02", "2026-03-03"]), ["SH600000", "SZ000001"]],
        names=["datetime", "instrument"],
    )
    return pd.DataFrame(
        {
            "KMID": [0.1, 0.2, 0.3, 0.4],
            "LIMIT_STATUS": [0, 1, 0, 1],
            "LABEL0": [0.01, 0.02, 0.03, 0.04],
        },
        index=idx,
    )


def _multi_frame():
    idx = pd.MultiIndex.from_product(
        [pd.to_datetime(["2026-03-02", "2026-03-03"]), ["SH600000", "SZ000001"]],
        names=["datetime", "instrument"],
    )
    cols = pd.MultiIndex.from_tuples(
        [
            ("feature", "KMID"),
            ("feature", "LIMIT_STATUS"),
            ("label", "LABEL0"),
        ]
    )
    return pd.DataFrame(
        [[0.1, 0, 0.01], [0.2, 1, 0.02], [0.3, 0, 0.03], [0.4, 1, 0.04]],
        index=idx,
        columns=cols,
    )


def test_drop_limit_up_rows_flat_reduces_count():
    df = _flat_frame()
    out = drop_limit_up_rows(df)
    assert len(df) == 4
    assert len(out) == 2
    assert (out["LIMIT_STATUS"] == 1).sum() == 0


def test_drop_limit_up_rows_multiindex_columns():
    df = _multi_frame()
    out = drop_limit_up_rows(df)
    assert len(out) == 2
    assert (out[("feature", "LIMIT_STATUS")] == 1).sum() == 0


def test_processor_learn_only_and_callable():
    proc = DropLimitUpLearn(col="LIMIT_STATUS", value=1)
    assert proc.is_for_infer() is False
    out = proc(_flat_frame())
    assert len(out) == 2


def test_missing_col_noop():
    df = _flat_frame().drop(columns=["LIMIT_STATUS"])
    assert len(drop_limit_up_rows(df)) == len(df)


def test_default_learn_processors_include_drop_limit_up():
    assert _DEFAULT_LEARN_PROCESSORS[0]["class"] == "DropLimitUpLearn"
    assert _DEFAULT_LEARN_PROCESSORS[0]["module_path"] == "custom_handler"
    # infer path unchanged: no DropLimitUpLearn
    assert all(p.get("class") != "DropLimitUpLearn" for p in _DEFAULT_INFER_PROCESSORS)


def test_nan_limit_status_kept():
    df = _flat_frame()
    df.loc[df.index[0], "LIMIT_STATUS"] = float("nan")
    out = drop_limit_up_rows(df)
    # original: nan,1,0,1 → keep nan + 0 → 2 rows (same as dropping two 1s)
    assert len(out) == 2
    assert df.index[0] in out.index
