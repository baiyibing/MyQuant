"""merge_archive_and_csv：CSV 多出的列（winratio）必须进 staging。"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_QLIB_SCRIPTS = os.path.join(_ROOT, "qlib_scripts")
if _QLIB_SCRIPTS not in sys.path:
    sys.path.insert(0, _QLIB_SCRIPTS)

from merge_archive_and_csv import extra_csv_fields  # noqa: E402


def test_extra_csv_fields_keeps_winratio():
    archive = ["adjclose", "amount", "close", "open"]
    csv_cols = ["code", "date", "open", "close", "adjclose", "amount", "winratio"]
    assert extra_csv_fields(csv_cols, archive) == ["winratio"]


def test_extra_csv_fields_skips_ids_and_duplicates():
    archive = ["close"]
    csv_cols = ["CODE", "date", "symbol", "time", "close", "close"]
    assert extra_csv_fields(csv_cols, archive) == []


def test_to_numeric_coerces_msvc_nan():
    """F:\\qlibdata20260914 全量扫描：非法浮点只有两种 Windows/MSVC 写法。

    - ``-1.#J``：MSVC NaN 截断，只出现在 winratio
    - ``-1.#IND``：标准 Windows NaN，只出现在 vwap（0 成交除出来）
    """
    import pandas as pd

    s = pd.to_numeric(pd.Series(["0.31", "-1.#J", "-1.#IND", None]), errors="coerce")
    assert float(s.iloc[0]) == 0.31
    assert pd.isna(s.iloc[1])
    assert pd.isna(s.iloc[2])
    assert pd.isna(s.iloc[3])
