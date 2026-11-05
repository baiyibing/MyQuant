"""CSV Windows/MSVC 非法浮点扫描。"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

pytest.importorskip("myquant_infra.data_validation.csv_float")

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_QLIB_SCRIPTS = os.path.join(_ROOT, "qlib_scripts")
if _QLIB_SCRIPTS not in sys.path:
    sys.path.insert(0, _QLIB_SCRIPTS)

from csv_float_scan import (  # noqa: E402
    format_scan_report,
    inspect_csv_illegal,
    scan_csv_dir,
    summarize_hits_by_column,
)


@pytest.mark.parametrize("token", ["-1.#J", "-1.#IND", "1.#QNAN", "1.#inf"])
def test_illegal_tokens_preserve_report_and_csv(tmp_path, token):
    p = tmp_path / "tokens.csv"
    p.write_text(f"date,close,vwap\n2026-11-05,{token},{token}\n", encoding="utf-8")
    before = p.read_bytes()
    report = scan_csv_dir(tmp_path)
    assert report["files_scanned"] == report["files_hit"] == 1
    assert len(report["fatal"]) == len(report["warn"]) == 1
    assert report["fatal"][0]["column"] == "close"
    assert report["warn"][0]["column"] == "vwap"
    assert all(h["sample"] == token and h["first_date"] == "2026-11-05" for h in report["hits"])
    assert p.read_bytes() == before


@pytest.mark.parametrize("entry", ["script", "module"])
@pytest.mark.parametrize("column,value,code", [
    ("close", "10.0", 0),
    ("winratio", "-1.#J", 0),
    ("close", "-1.#IND", 2),
])
def test_cli_real_csv(tmp_path, entry, column, value, code):
    p = tmp_path / "fixture.csv"
    p.write_text(f"date,{column}\n2026-11-05,{value}\n", encoding="utf-8")
    before = p.read_bytes()
    argv = (
        [str(Path(_ROOT) / "qlib_scripts" / "csv_float_scan.py")]
        if entry == "script" else ["-m", "qlib_scripts.csv_float_scan"]
    )
    proc = subprocess.run(
        [sys.executable, *argv, "--csv-dir", str(tmp_path)],
        cwd=_ROOT, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == code, proc.stderr
    assert proc.stdout == format_scan_report(scan_csv_dir(tmp_path)) + "\n"
    assert proc.stderr == ""
    assert p.read_bytes() == before


def test_invalid_csv_directory_fails_closed(tmp_path):
    with pytest.raises(NotADirectoryError):
        scan_csv_dir(tmp_path / "missing")


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
    assert report["by_column"]["winratio"]["fatal"] is False
    assert report["by_column"]["winratio"]["files"] == 1
    assert report["by_column"]["open"]["fatal"] is True


def test_summarize_hits_by_column_separates_winratio_and_vwap():
    hits = [
        {"file": "A.csv", "column": "winratio", "count": 10, "fatal": False, "sample": "-1.#J"},
        {"file": "B.csv", "column": "vwap", "count": 1, "fatal": False, "sample": "-1.#IND"},
        {"file": "C.csv", "column": "vwap", "count": 1, "fatal": False, "sample": "-1.#IND"},
    ]
    summary = summarize_hits_by_column(hits)
    assert summary["winratio"]["files"] == 1
    assert summary["winratio"]["count"] == 10
    assert summary["vwap"]["files"] == 2
    assert summary["vwap"]["count"] == 2
    text = format_scan_report(
        {
            "files_scanned": 3,
            "files_hit": 3,
            "hits": hits,
            "fatal": [],
            "warn": hits,
            "by_column": summary,
        }
    )
    assert "by_column:" in text
    assert "winratio warn" in text
    assert "vwap warn" in text
    assert "-1.#J" in text
    assert "-1.#IND" in text
