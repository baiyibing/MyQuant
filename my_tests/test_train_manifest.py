# -*- coding: utf-8 -*-
"""M4-B: write_train_manifest 可单测 helper（无 full train / handler_init）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from custom_utils import TimerRecorder  # noqa: E402
from run_manifest import load_manifest, write_train_manifest  # noqa: E402


class _FakeTimer:
    def __init__(self):
        self.nodes = [{"name": "handler_init", "seconds": 1.25}, {"name": "model_fit", "seconds": 0.5}]
        self._t0 = 0.0

    # timings_from_recorder uses timeit.default_timer()-_t0; stub _t0 near now via real TimerRecorder instead


def test_write_train_manifest_with_pred_and_timer(tmp_path: Path):
    pred = tmp_path / "预测结果.csv"
    pred.write_text(
        "datetime,instrument,score\n2026-03-02,SH600000,0.1\n2026-03-02,SZ000001,0.2\n",
        encoding="utf-8",
    )
    rec = TimerRecorder()
    with rec.timer("handler_init"):
        pass
    with rec.timer("model_fit"):
        pass

    cfg = {
        "exp_name": "unit",
        "segments": {"train": ("2026-01-01", "2026-01-31"), "valid": ("2026-02-01", "2026-02-28"), "test": ("2026-03-01", "2026-03-23")},
        "topk": 10,
        "n_drop": 3,
    }
    written = write_train_manifest(
        manifests_dir=tmp_path / "manifests",
        config=cfg,
        pred_path=pred,
        timer_recorder=rec,
        data={"calendar_first": "2026-01-01", "calendar_last": "2026-03-23", "calendar_days": 50},
        git_commit_sha="unitsha",
        created_utc="2026-09-13T03:00:00Z",
        pred_rows=2,
        repo_root=_ROOT,
    )
    assert written[0].name.startswith("train_")
    man = load_manifest(written[0])
    assert man["stage"] == "train"
    assert man["config"]["topk"] == 10
    assert man["config"]["n_drop"] == 3
    assert man["config"]["segments"]["train"][0] == "2026-01-01"
    assert man["artifacts"][0]["rows"] == 2
    assert man["artifacts"][0]["md5"]
    names = [n["name"] for n in man["timings"]["nodes"]]
    assert "handler_init" in names and "model_fit" in names
    # sidecar beside pred
    assert any(p.parent == pred.parent for p in written[1:])


def test_write_train_manifest_without_pred(tmp_path: Path):
    written = write_train_manifest(
        manifests_dir=tmp_path / "manifests",
        config={"topk": 5, "n_drop": 1},
        pred_path=tmp_path / "missing.csv",
        timings={"total_seconds": 0.1, "nodes": []},
        git_commit_sha="x",
        created_utc="2026-09-13T03:01:00Z",
    )
    man = load_manifest(written[0])
    assert man["artifacts"] == []
    assert man["config"]["topk"] == 5
