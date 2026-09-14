"""CSV Windows/MSVC 非法浮点扫描。"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_QLIB_SCRIPTS = os.path.join(_ROOT, "qlib_scripts")
if _QLIB_SCRIPTS not in sys.path:
    sys.path.insert(0, _QLIB_SCRIPTS)

from csv_float_scan import inspect_csv_illegal, scan_csv_dir  # noqa: E402


def test_inspect_winratio_junk_is_warn(tmp_path):
    p = tmp_path / "SH600157.csv"
    p.write_text("date,close,winratio\n2020-01-02,10.0,-1.#J\n", encoding="utf-8")
    hits = inspect_csv_illegal(p)
    assert len(hits) == 1
    assert hits[0]["column"] == "winratio"
    assert hits[0]["fatal"] is False
    assert hits[0]["sample"] == "-1.#J"


def test_inspect_vwap_ind_is_warn(tmp_path):
    p = tmp_path / "SH600301.csv"
    p.write_text(
        "date,close,vwap\n2026-09-14,10.0,-1.#IND\n",
        encoding="utf-8",
    )
    hits = inspect_csv_illegal(p)
    assert hits[0]["column"] == "vwap"
    assert hits[0]["fatal"] is False


def test_inspect_close_junk_is_fatal(tmp_path):
    p = tmp_path / "SH600000.csv"
    p.write_text("date,close\n2020-01-02,-1.#J\n", encoding="utf-8")
    hits = inspect_csv_illegal(p)
    assert hits[0]["fatal"] is True
    assert hits[0]["column"] == "close"


def test_scan_csv_dir_splits_fatal_and_warn(tmp_path):
    (tmp_path / "ok.csv").write_text("date,close\n2020-01-02,1.0\n", encoding="utf-8")
    (tmp_path / "wr.csv").write_text("date,close,winratio\n2020-01-02,1.0,-1.#J\n", encoding="utf-8")
    (tmp_path / "bad.csv").write_text("date,open,close\n2020-01-02,-1.#IND,1.0\n", encoding="utf-8")
    report = scan_csv_dir(tmp_path)
    assert report["files_scanned"] == 3
    assert report["files_hit"] == 2
    assert len(report["fatal"]) == 1
    assert report["fatal"][0]["file"] == "bad.csv"
    assert len(report["warn"]) == 1
