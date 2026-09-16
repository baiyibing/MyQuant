# -*- coding: utf-8 -*-
"""summarize_model_runs: roll train manifests into a comparison table."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from custom_utils import TimerRecorder  # noqa: E402
from run_manifest import write_train_manifest  # noqa: E402
from summarize_model_runs import collect_rows, format_table  # noqa: E402


def test_collect_and_format(tmp_path: Path):
    rec = TimerRecorder()
    rec.nodes.extend(
        [
            {"name": "handler_init", "seconds": 5.0},
            {"name": "model_fit", "seconds": 83.0},
            {"name": "dataset.prepare.train", "seconds": 12.0},
            {"name": "SignalRecord.generate", "seconds": 8.0},
            {"name": "PortAnaRecord.generate", "seconds": 25.0},
        ]
    )
    write_train_manifest(
        manifests_dir=tmp_path,
        config={
            "model": "ridge",
            "topk": 50,
            "n_drop": 5,
            "recorder_id": "1e82e9042e8e4db7",
            "segments": {"test": ["2026-01-01", "2026-09-14"]},
        },
        timer_recorder=rec,
        data={
            "handler_cache_hit": True,
            "excess_ann_with_cost": -0.2428,
            "excess_ir_with_cost": -1.1,
        },
        git_commit_sha="unitsha",
        created_utc="2026-09-16T02:38:52Z",
    )
    rows = collect_rows(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["model"] == "ridge"
    assert row["handler_cache_hit"] is True
    assert abs(row["excess_ann_with_cost"] + 0.2428) < 1e-9
    assert row["model_fit_s"] == 83.0
    assert row["prepare_s"] == 12.0
    assert row["portana_s"] == 25.0
    table = format_table(rows)
    assert "ridge" in table
    assert "HIT" in table
    assert "-24.3%" in table
    assert collect_rows(tmp_path, topk=10) == []
    assert len(collect_rows(tmp_path, models={"ridge"}, topk=50)) == 1
