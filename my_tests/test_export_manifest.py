# -*- coding: utf-8 -*-
"""M4-C: export manifest helper + tiny window via export_daily_pool main."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from export_daily_pool import main  # noqa: E402
from run_manifest import load_manifest, write_export_manifest  # noqa: E402


def test_write_export_manifest_helper(tmp_path: Path):
    pred = tmp_path / "pred.csv"
    pred.write_text(
        "datetime,instrument,score\n"
        "2026-03-02,SZ300190,2\n"
        "2026-03-05,SH600000,1\n",
        encoding="utf-8",
    )
    out = tmp_path / "pool"
    out.mkdir()
    (out / "20260305.csv").write_text("300190\n", encoding="utf-8", newline="\n")
    written = write_export_manifest(
        manifests_dir=tmp_path / "manifests",
        config={"asof": "pred_minus_one", "topk": 10},
        pred_path=pred,
        out_dir=out,
        output_file_count=1,
        pred_rows=2,
        git_commit_sha="expsha",
        created_utc="2026-09-13T04:00:00Z",
        data={"calendar_first": "2026-03-02", "calendar_last": "2026-03-05", "calendar_days": 2},
    )
    man = load_manifest(written[0])
    assert man["stage"] == "export"
    assert man["config"]["asof"] == "pred_minus_one"
    assert man["config"]["output_file_count"] == 1
    assert man["artifacts"][0]["md5"]


def test_export_main_writes_manifest_tiny_window(tmp_path: Path, monkeypatch):
    pred = tmp_path / "pred.csv"
    pred.write_text(
        "datetime,instrument,score\n"
        "2026-03-02,SZ300190,2\n"
        "2026-03-02,SH600000,1\n"
        "2026-03-05,BJ920014,3\n"
        "2026-03-09,SZ000001,4\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    # Point REPO_ROOT manifests under tmp by monkeypatching module constant
    import export_daily_pool as edp
    import run_manifest as rm

    monkeypatch.setattr(edp, "REPO_ROOT", tmp_path)
    rc = main(["--pred", str(pred), "--out-dir", str(out), "--topk", "1", "--asof", "pred_minus_one"])
    assert rc == 0
    assert (out / "20260305.csv").read_text(encoding="utf-8") == "300190\n"
    assert (out / "20260309.csv").read_text(encoding="utf-8") == "920014\n"
    man_dir = tmp_path / "manifests"
    files = list(man_dir.glob("export_*.json"))
    assert len(files) == 1
    man = load_manifest(files[0])
    assert man["config"]["asof"] == "pred_minus_one"
    assert man["config"]["topk"] == 1
    assert man["config"]["output_file_count"] == 2
    assert man["artifacts"][0]["path"].endswith("pred.csv") or man["artifacts"][0]["path"] == "pred.csv"
    # as-of lock: last pred day has no buy file
    assert not (out / "20260302.csv").exists()
