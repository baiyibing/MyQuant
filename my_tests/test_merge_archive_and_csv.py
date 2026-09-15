"""merge_archive_and_csv：CSV 多出的列（winratio）必须进 staging。"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_QLIB_SCRIPTS = os.path.join(_ROOT, "qlib_scripts")
if _QLIB_SCRIPTS not in sys.path:
    sys.path.insert(0, _QLIB_SCRIPTS)

from merge_archive_and_csv import (  # noqa: E402
    extra_csv_fields,
    format_csv_profile,
    list_archive_fields,
    overlay_csv_on_archive,
    profile_csv_batch,
)


def test_overlay_keeps_archive_winratio_on_short_csv():
    import numpy as np
    import pandas as pd

    archive = pd.DataFrame(
        {"close": [10.0, 11.0], "winratio": [0.50, 0.56]},
        index=pd.to_datetime(["2026-09-01", "2026-09-02"]),
    )
    csv_df = pd.DataFrame(
        {"close": [11.5, 12.0], "volume": [1.0, 2.0]},
        index=pd.to_datetime(["2026-09-02", "2026-09-15"]),
    )
    out = overlay_csv_on_archive(archive, csv_df, ["close", "volume", "winratio"])
    assert float(out.loc["2026-09-01", "close"]) == 10.0
    assert float(out.loc["2026-09-02", "close"]) == 11.5
    assert float(out.loc["2026-09-15", "close"]) == 12.0
    assert float(out.loc["2026-09-01", "winratio"]) == 0.50
    assert float(out.loc["2026-09-02", "winratio"]) == 0.56
    assert pd.isna(out.loc["2026-09-15", "winratio"])
    assert float(out.loc["2026-09-15", "volume"]) == 2.0
    assert np.isnan(out.loc["2026-09-01", "volume"]) or pd.isna(out.loc["2026-09-01", "volume"])


def test_overlay_ignores_empty_winratio_column():
    import pandas as pd

    archive = pd.DataFrame(
        {"close": [10.0, 11.0], "winratio": [0.50, 0.56]},
        index=pd.to_datetime(["2026-09-01", "2026-09-02"]),
    )
    csv_df = pd.DataFrame(
        {"close": [11.5, 12.0], "winratio": ["", None]},
        index=pd.to_datetime(["2026-09-02", "2026-09-15"]),
    )
    out = overlay_csv_on_archive(archive, csv_df, ["close", "winratio"])
    assert float(out.loc["2026-09-02", "close"]) == 11.5
    assert float(out.loc["2026-09-02", "winratio"]) == 0.56
    assert pd.isna(out.loc["2026-09-15", "winratio"])


def test_overlay_keeps_archive_when_csv_cell_empty_but_writes_valid():
    import pandas as pd

    archive = pd.DataFrame(
        {"close": [11.0], "winratio": [0.56]},
        index=pd.to_datetime(["2026-09-02"]),
    )
    csv_df = pd.DataFrame(
        {"close": [11.5, 12.0], "winratio": [None, 0.40]},
        index=pd.to_datetime(["2026-09-02", "2026-09-15"]),
    )
    out = overlay_csv_on_archive(archive, csv_df, ["close", "winratio"])
    assert float(out.loc["2026-09-02", "winratio"]) == 0.56
    assert float(out.loc["2026-09-15", "winratio"]) == 0.40


def test_profile_short_tail_missing_winratio(tmp_path):
    rows = "\n".join(
        f"SH600000,2026-09-{d:02d},10.0" for d in range(2, 12)
    )
    (tmp_path / "SH600000.csv").write_text(
        "code,date,close\n" + rows + "\n", encoding="utf-8"
    )
    profile = profile_csv_batch(tmp_path, ["close", "winratio"])
    assert profile["files"] == 1
    assert profile["short_tail"] is True
    assert profile["approx_days"] == 10
    assert profile["missing_vs_archive"] == ["winratio"]
    text = format_csv_profile(profile)
    assert "short_tail=True" in text
    assert "winratio" in text
    assert "dump_all" in text


def test_list_archive_fields(tmp_path):
    feat = tmp_path / "features" / "sh600000"
    feat.mkdir(parents=True)
    for name in [
        "close", "open", "high", "low", "volume", "amount", "factor", "vwap",
        "adjclose", "change", "winratio", "volddx", "bigddx", "netcsfree",
        "basiccurhold", "adfadfbasiccurhold",
    ]:
        (feat / f"{name}.day.bin").write_bytes(b"")
    assert "winratio" in list_archive_fields(tmp_path)


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
