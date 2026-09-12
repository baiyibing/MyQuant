# -*- coding: utf-8 -*-
"""M3-B: sweep_ranking harness (injectable train/predict; --limit smoke)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from run_manifest import load_manifest  # noqa: E402
from sweep_ranking import (  # noqa: E402
    SweepConfig,
    default_live_train_predict,
    iter_config_grid,
    main,
    parse_int_list,
    run_sweep,
    summarize_ic_ir,
    write_summary_table,
)


def test_parse_int_list():
    assert parse_int_list("5,10,20") == [5, 10, 20]
    assert parse_int_list("1 2") == [1, 2]
    assert parse_int_list("") == []


def test_iter_config_grid_cartesian_and_limit():
    configs = iter_config_grid([5, 10], [1, 3], [1], limit=None)
    assert len(configs) == 4
    assert configs[0].grid_id == "topk5_ndrop1_hold1"
    limited = iter_config_grid([5, 10], [1, 3], [1, 2], limit=2)
    assert len(limited) == 2
    assert limited[0].topk == 5 and limited[0].n_drop == 1 and limited[0].hold_thresh == 1
    assert limited[1].topk == 5 and limited[1].n_drop == 1 and limited[1].hold_thresh == 2


def test_iter_config_grid_rejects_empty():
    with pytest.raises(ValueError):
        iter_config_grid([], [1], [1])


def test_run_sweep_injects_fake_and_writes_manifests(tmp_path: Path):
    calls = []

    def fake(cfg: SweepConfig):
        calls.append(cfg.grid_id)
        return {
            "ic": 0.02 + 0.001 * cfg.topk,
            "ir": 0.5 + 0.01 * cfg.n_drop,
            "notes": "unit-fake",
            "timings": {"total_seconds": 0.1, "nodes": []},
            "data": {"calendar_days": 2},
        }

    configs = iter_config_grid([10, 20], [3], [1], limit=2)
    manifests_dir = tmp_path / "manifests"
    results = run_sweep(
        configs,
        train_predict_fn=fake,
        manifests_dir=manifests_dir,
        repo_root=_ROOT,
        write_manifests=True,
    )
    assert len(results) == 2
    assert len(calls) == 2
    assert results[0].ic == pytest.approx(0.03)
    assert results[0].manifest_path
    man = load_manifest(results[0].manifest_path)
    assert man["schema"] == "myquant.run-manifest/1"
    assert man["stage"] == "train"
    assert man["config"]["topk"] == 10
    assert man["config"]["n_drop"] == 3
    assert man["config"]["hold_thresh"] == 1
    assert "config_hash" in man["config"]

    summary = summarize_ic_ir(results)
    assert list(summary.columns)[:5] == [
        "grid_id",
        "topk",
        "n_drop",
        "hold_thresh",
        "ic",
    ]
    assert len(summary) == 2
    # Sorted by ic desc: topk20 first
    assert summary.iloc[0]["topk"] == 20

    paths = write_summary_table(summary, tmp_path / "out")
    assert paths["csv"].is_file()
    assert paths["md"].is_file()
    text = paths["md"].read_text(encoding="utf-8")
    assert "topk" in text and "ic" in text


def test_live_default_raises():
    with pytest.raises(RuntimeError, match="18min"):
        default_live_train_predict(SweepConfig(10, 3, 1).with_id())


def test_cli_limit_2_dry_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "sweep_out"
    rc = main(
        [
            "--topk",
            "5,10,20",
            "--n-drop",
            "1,3",
            "--hold",
            "1,2",
            "--limit",
            "2",
            "--out-dir",
            str(out),
            "--dry-run-fake",
        ]
    )
    assert rc == 0
    assert (out / "sweep_summary.csv").is_file()
    df = pd.read_csv(out / "sweep_summary.csv")
    assert len(df) == 2
    # manifests written
    mans = list((out / "manifests").glob("train_sweep_*.json"))
    assert len(mans) == 2
    raw = mans[0].read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    data = json.loads(raw.decode("utf-8"))
    assert data["config"]["stage_kind"] == "ranking_sweep"
