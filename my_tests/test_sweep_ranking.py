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
    build_arg_parser,
    default_live_train_predict,
    iter_config_grid,
    main,
    maybe_segments_from_args,
    parse_date_range,
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


def test_parse_date_range_ok():
    assert parse_date_range("2026-01-01:2026-01-31") == ("2026-01-01", "2026-01-31")
    assert parse_date_range(" 2026-04-01 : 2026-08-31 ") == ("2026-04-01", "2026-08-31")


@pytest.mark.parametrize(
    "bad",
    [
        "2026-01-01",
        "2026-01-01-2026-01-31",
        "foo:bar",
        "2026-01-31:2026-01-01",
        "",
        "2026-01-01:",
        ":2026-01-31",
        "2026-13-01:2026-13-31",
    ],
)
def test_parse_date_range_rejects_illegal(bad: str):
    with pytest.raises(ValueError):
        parse_date_range(bad)


def test_cli_parses_train_valid_test():
    args = build_arg_parser().parse_args(
        [
            "--train",
            "2026-01-01:2026-01-31",
            "--valid",
            "2026-02-01:2026-02-28",
            "--test",
            "2026-04-01:2026-08-31",
        ]
    )
    assert args.train == ("2026-01-01", "2026-01-31")
    assert args.valid == ("2026-02-01", "2026-02-28")
    assert args.test == ("2026-04-01", "2026-08-31")
    segs = maybe_segments_from_args(args)
    assert segs == {
        "train": ("2026-01-01", "2026-01-31"),
        "valid": ("2026-02-01", "2026-02-28"),
        "test": ("2026-04-01", "2026-08-31"),
    }


def test_cli_default_segments_none():
    args = build_arg_parser().parse_args([])
    assert args.train is None and args.valid is None and args.test is None
    assert maybe_segments_from_args(args) is None


def test_cli_rejects_illegal_train_format(tmp_path: Path):
    with pytest.raises(SystemExit):
        main(
            [
                "--dry-run-fake",
                "--limit",
                "1",
                "--train",
                "2026-01-01",
                "--out-dir",
                str(tmp_path / "out"),
            ]
        )


def test_sweep_config_has_no_window_fields():
    from dataclasses import fields

    names = {f.name for f in fields(SweepConfig)}
    assert names == {"topk", "n_drop", "hold_thresh", "grid_id"}
    cfg = SweepConfig(10, 3, 1).as_manifest_config()
    assert "train" not in cfg and "valid" not in cfg and "test" not in cfg
    assert "segments" not in cfg


def test_default_adapter_path_does_not_call_set_segments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """缺省不调 set_segments（向后兼容：adapter 用三月窗常量）。"""
    import importlib
    import types

    calls: list = []
    fake = types.ModuleType("fake_adapter_no_segs")

    def train_predict_fn(cfg):
        return {
            "ic": 0.01,
            "ir": 0.1,
            "notes": "fake-adapter",
            "timings": {"total_seconds": 0, "nodes": []},
            "data": {},
        }

    def set_segments(segs):
        calls.append(segs)

    fake.train_predict_fn = train_predict_fn
    fake.set_segments = set_segments
    fake.SEGMENTS = {
        "train": ("2026-01-01", "2026-01-31"),
        "valid": ("2026-02-01", "2026-02-28"),
        "test": ("2026-03-01", "2026-03-23"),
    }
    real_import = importlib.import_module

    def _import(name, package=None):
        if name == "fake_adapter_no_segs":
            return fake
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", _import)
    monkeypatch.chdir(tmp_path)
    rc = main(
        [
            "--adapter",
            "fake_adapter_no_segs",
            "--limit",
            "1",
            "--out-dir",
            str(tmp_path / "out"),
        ]
    )
    assert rc == 0
    assert calls == []


def test_adapter_path_calls_set_segments_when_any_window_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import importlib
    import types

    calls: list = []
    fake = types.ModuleType("fake_adapter_with_segs")

    def train_predict_fn(cfg):
        return {
            "ic": 0.02,
            "ir": 0.2,
            "notes": "fake-adapter",
            "config": {"segments": {"train": ["2026-01-01", "2026-01-31"]}},
            "timings": {"total_seconds": 0, "nodes": []},
            "data": {},
        }

    def set_segments(segs):
        calls.append(segs)

    fake.train_predict_fn = train_predict_fn
    fake.set_segments = set_segments
    fake.SEGMENTS = {
        "train": ("2026-01-01", "2026-01-31"),
        "valid": ("2026-02-01", "2026-02-28"),
        "test": ("2026-03-01", "2026-03-23"),
    }
    real_import = importlib.import_module

    def _import(name, package=None):
        if name == "fake_adapter_with_segs":
            return fake
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", _import)
    monkeypatch.chdir(tmp_path)
    rc = main(
        [
            "--adapter",
            "fake_adapter_with_segs",
            "--train",
            "2026-01-01:2026-01-31",
            "--valid",
            "2026-02-01:2026-02-28",
            "--test",
            "2026-04-01:2026-08-31",
            "--limit",
            "1",
            "--out-dir",
            str(tmp_path / "out"),
        ]
    )
    assert rc == 0
    assert len(calls) == 1
    assert calls[0]["train"] == ("2026-01-01", "2026-01-31")
    assert calls[0]["valid"] == ("2026-02-01", "2026-02-28")
    assert calls[0]["test"] == ("2026-04-01", "2026-08-31")


def test_dry_run_fake_with_windows_does_not_need_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """--dry-run-fake 不走 adapter，传窗口也不调 set_segments，冒烟不受影响。"""
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "sweep_out_fake_win"
    rc = main(
        [
            "--topk",
            "5,10",
            "--n-drop",
            "3",
            "--hold",
            "1",
            "--limit",
            "2",
            "--out-dir",
            str(out),
            "--dry-run-fake",
            "--train",
            "2026-01-01:2026-01-31",
            "--valid",
            "2026-02-01:2026-02-28",
            "--test",
            "2026-04-01:2026-08-31",
        ]
    )
    assert rc == 0
    assert (out / "sweep_summary.csv").is_file()
    df = pd.read_csv(out / "sweep_summary.csv")
    assert len(df) == 2
    mans = list((out / "manifests").glob("train_sweep_*.json"))
    assert len(mans) == 2
    data = json.loads(mans[0].read_text(encoding="utf-8"))
    assert data["config"]["stage_kind"] == "ranking_sweep"
    # fake payload 不含窗口；窗口不得渗进 SweepConfig
    assert "train" not in data["config"]
    assert "valid" not in data["config"]
    assert "test" not in data["config"]
    assert "segments" not in data["config"]


def test_run_one_missing_timings_marks_unknown(tmp_path: Path):
    """缺 timings 时不写假零秒，标 unknown（adapter 应必给 timings）。"""

    def fake(cfg: SweepConfig):
        return {
            "ic": 0.01,
            "ir": 0.1,
            "notes": "no-timings",
            "data": {"arm_mode": "ARM_ONLY", "shared_handler_cache_key": "abc"},
        }

    result = run_sweep(
        [SweepConfig(5, 1, 1).with_id()],
        train_predict_fn=fake,
        manifests_dir=tmp_path / "manifests",
        repo_root=_ROOT,
        write_manifests=True,
    )[0]
    man = load_manifest(result.manifest_path)
    assert man["data"]["arm_mode"] == "ARM_ONLY"
    assert man["data"]["shared_handler_cache_key"] == "abc"
    assert man["timings"].get("unknown") is True
    assert man["timings"]["nodes"] == []
    assert man["timings"]["total_seconds"] is None

