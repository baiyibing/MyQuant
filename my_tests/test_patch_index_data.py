"""湖指数补丁：纯函数单测（clip / code 映射 / all.txt 挪移）。"""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_QLIB_SCRIPTS = os.path.join(_ROOT, "qlib_scripts")
if _QLIB_SCRIPTS not in sys.path:
    sys.path.insert(0, _QLIB_SCRIPTS)

from patch_index_data import (  # noqa: E402
    FIELDS,
    clip_index_frame,
    coverage_report,
    lake_to_qlib_code,
    move_indices_out_of_all_txt,
    upsert_index_txt_dates,
)


def _lake_frame(times_ms, closes):
    return pd.DataFrame(
        {"time": times_ms, "open": closes, "high": closes, "low": closes,
         "close": closes, "volume": [1] * len(closes), "amount": [1.0] * len(closes)}
    )


CAL = pd.DatetimeIndex(pd.to_datetime(["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05"]))


def test_lake_to_qlib_code():
    assert lake_to_qlib_code("000300_SH") == "SH000300"
    assert lake_to_qlib_code("399001_SZ") == "SZ399001"
    with pytest.raises(ValueError):
        lake_to_qlib_code("000300")


def test_clip_utc_millis_to_shanghai_date():
    # 2026-03-03 09:30 上海 = 01:30 UTC 同日；按 UTC 直接取日期也是 03-03，
    # 但 2026-03-03 00:30 上海 = 前一日 16:30 UTC，若不转时区会错成 03-02。
    ms = pd.Timestamp("2026-03-03 00:30", tz="Asia/Shanghai").value // 10**6
    clipped = clip_index_frame(_lake_frame([ms], [4000.0]), CAL)
    assert clipped["date"].iloc[0] == pd.Timestamp("2026-03-03")


def test_clip_drops_out_of_calendar_and_duplicates():
    in1 = pd.Timestamp("2026-03-02 15:00", tz="Asia/Shanghai").value // 10**6
    dup = pd.Timestamp("2026-03-02 09:30", tz="Asia/Shanghai").value // 10**6
    out = pd.Timestamp("2019-12-31 15:00", tz="Asia/Shanghai").value // 10**6
    clipped = clip_index_frame(_lake_frame([out, in1, dup, in1], [1.0, 2.0, 3.0, 2.0]), CAL)
    assert len(clipped) == 1
    assert clipped["date"].iloc[0] == pd.Timestamp("2026-03-02")
    assert list(clipped.columns) == ["date", *FIELDS]


def test_coverage_report_counts_missing():
    clipped = pd.DataFrame({"close": [1.0], "date": pd.to_datetime(["2026-03-02"])})
    stats = coverage_report(clipped, CAL)
    assert stats["calendar_missing"] == 3
    assert stats["nan_close"] == 0


def test_move_indices_out_of_all_txt(tmp_path):
    (tmp_path / "instruments").mkdir()
    all_path = tmp_path / "instruments" / "all.txt"
    all_path.write_text(
        "SH600000\t2020-01-02\t2026-04-10\nSH000300\t2020-01-02\t2026-04-10\nSH000001\t2020-01-02\t2026-04-10\n",
        encoding="utf-8",
    )
    moved = move_indices_out_of_all_txt(tmp_path, ["SH000300", "SH000001"])
    assert len(moved) == 2
    assert all_path.read_text(encoding="utf-8").splitlines() == ["SH600000\t2020-01-02\t2026-04-10"]
    index_lines = (tmp_path / "instruments" / "index.txt").read_text(encoding="utf-8").splitlines()
    assert len(index_lines) == 2
    # 幂等：重跑不再挪
    assert move_indices_out_of_all_txt(tmp_path, ["SH000300", "SH000001"]) == []
    assert len((tmp_path / "instruments" / "index.txt").read_text(encoding="utf-8").splitlines()) == 2


def test_move_replaces_stale_index_row(tmp_path):
    """index.txt 里的旧登记（如上次裁剪的陈旧区间）须被本次 dump 的新行覆盖。"""
    (tmp_path / "instruments").mkdir()
    (tmp_path / "instruments" / "all.txt").write_text(
        "SH000300\t2020-01-02\t2026-09-08\n", encoding="utf-8"
    )
    (tmp_path / "instruments" / "index.txt").write_text(
        "SH000300\t2020-01-02\t2026-04-10\n", encoding="utf-8"
    )
    moved = move_indices_out_of_all_txt(tmp_path, ["SH000300"])
    assert len(moved) == 1
    index_lines = (tmp_path / "instruments" / "index.txt").read_text(encoding="utf-8").splitlines()
    assert index_lines == ["SH000300\t2020-01-02\t2026-09-08"]


def test_upsert_index_txt_dates_extends_stale_end(tmp_path):
    (tmp_path / "instruments").mkdir()
    (tmp_path / "instruments" / "index.txt").write_text(
        "SH000300\t2020-01-02\t2026-09-08\nSH000001\t2020-01-02\t2026-09-08\n",
        encoding="utf-8",
    )
    updated = upsert_index_txt_dates(
        tmp_path, ["SH000300", "SH000001"], "2020-01-02", "2026-09-14"
    )
    assert updated == ["SH000300", "SH000001"]
    lines = (tmp_path / "instruments" / "index.txt").read_text(encoding="utf-8").splitlines()
    assert lines == [
        "SH000300\t2020-01-02\t2026-09-14",
        "SH000001\t2020-01-02\t2026-09-14",
    ]
