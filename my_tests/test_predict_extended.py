# -*- coding: utf-8 -*-
"""M5r2: predict_extended segment/CLI validation + injected predict (no qlib)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from predict_extended import (  # noqa: E402
    DEFAULT_SEGMENTS,
    M5R2_EXPORT_ASOF,
    M5R2_EXPORT_OUT_DIR,
    M5R2_EXPORT_TOPK,
    PRED_CSV_NAME,
    build_arg_parser,
    handler_span,
    main,
    pred_series_to_frame,
    run_predict_extended,
    validate_segments,
)
from run_manifest import load_manifest  # noqa: E402
from export_daily_pool import build_parser as export_build_parser  # noqa: E402


DEFAULT = {
    "train": ("2026-01-01", "2026-01-31"),
    "valid": ("2026-02-01", "2026-02-28"),
    "test": ("2026-03-01", "2026-09-14"),
}


def _fake_pred_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2026-03-02", "2026-03-02", "2026-03-03"]),
            "instrument": ["SZ300190", "SH600000", "BJ920014"],
            "score": [0.9, 0.5, 0.1],
        }
    )


def test_default_segments_match_plan():
    assert DEFAULT_SEGMENTS == DEFAULT
    assert PRED_CSV_NAME == "预测结果_ext.csv"


def test_cli_defaults_are_m5r2_windows():
    args = build_arg_parser().parse_args([])
    assert args.train == DEFAULT["train"]
    assert args.valid == DEFAULT["valid"]
    assert args.test == DEFAULT["test"]
    assert args.out_csv == PRED_CSV_NAME


def test_cli_parses_custom_segments():
    args = build_arg_parser().parse_args(
        [
            "--train",
            "2026-01-01:2026-01-31",
            "--valid",
            "2026-02-01:2026-02-28",
            "--test",
            "2026-03-01:2026-06-30",
        ]
    )
    assert args.test == ("2026-03-01", "2026-06-30")


@pytest.mark.parametrize(
    "bad",
    [
        "2026-01-01",
        "2026-01-01-2026-01-31",
        "foo:bar",
        "2026-01-31:2026-01-01",
        "2026-01-01:",
        ":2026-01-31",
        "2026-13-01:2026-13-31",
    ],
)
def test_cli_rejects_illegal_segment_format(bad: str):
    with pytest.raises(SystemExit):
        build_arg_parser().parse_args(["--train", bad])


def test_validate_segments_rejects_order_and_missing():
    with pytest.raises(ValueError, match="missing"):
        validate_segments({"train": DEFAULT["train"], "valid": DEFAULT["valid"]})
    with pytest.raises(ValueError, match="train.start"):
        validate_segments(
            {
                "train": ("2026-03-01", "2026-03-31"),
                "valid": ("2026-02-01", "2026-02-28"),
                "test": ("2026-04-01", "2026-04-30"),
            }
        )
    with pytest.raises(ValueError):
        validate_segments(
            {
                "train": ("2026-01-31", "2026-01-01"),
                "valid": DEFAULT["valid"],
                "test": DEFAULT["test"],
            }
        )


def test_handler_span_is_min_max():
    assert handler_span(DEFAULT) == ("2026-01-01", "2026-09-14")


def test_pred_series_to_frame_from_multiindex():
    idx = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2026-03-02"), "SZ300190"),
            (pd.Timestamp("2026-03-03"), "SH600000"),
        ],
        names=["datetime", "instrument"],
    )
    series = pd.Series([1.2, -0.3], index=idx, name="score")
    frame = pred_series_to_frame(series)
    assert list(frame.columns) == ["datetime", "instrument", "score"]
    assert len(frame) == 2
    assert frame.iloc[0]["instrument"] == "SZ300190"


def test_run_with_injected_predict_writes_csv_and_manifest(tmp_path: Path):
    def fake(segs, provider_uri=None):
        assert segs == DEFAULT
        return {
            "pred_frame": _fake_pred_frame(),
            "pred_rows": 3,
            "data": {"calendar_days": 2},
            "timings": {"total_seconds": 0.01, "nodes": []},
        }

    git_prov = {
        "git_commit": "deadbeef",
        "git_branch": "feat/m5r2-predict-extended",
        "git_dirty": False,
    }
    result = run_predict_extended(
        DEFAULT,
        out_csv=PRED_CSV_NAME,
        manifests_dir=tmp_path / "manifests",
        repo_root=_ROOT,
        predict_fn=fake,
        git_prov=git_prov,
        cwd=tmp_path,
    )
    pred_path = Path(result["pred_path"])
    assert pred_path.is_file()
    assert pred_path.name == PRED_CSV_NAME
    text = pred_path.read_text(encoding="utf-8")
    assert text.startswith("datetime,instrument,score\n")
    assert "SZ300190" in text
    assert result["handler_span"] == ("2026-01-01", "2026-09-14")
    assert result["manifest_paths"]
    man = load_manifest(result["manifest_paths"][0])
    assert man["stage"] == "train"
    assert man["config"]["stage_kind"] == "predict_extended"
    assert man["config"]["segments"] == {
        "train": ["2026-01-01", "2026-01-31"],
        "valid": ["2026-02-01", "2026-02-28"],
        "test": ["2026-03-01", "2026-09-14"],
    }
    assert man["config"]["portana"] is False
    assert man["config"]["alignment_check"] is False
    assert man["git_commit"] == "deadbeef"
    assert man["config"]["handler_start"] == "2026-01-01"
    assert man["config"]["handler_end"] == "2026-09-14"


def test_main_rejects_unordered_segments(capsys):
    rc = main(
        [
            "--train",
            "2026-04-01:2026-04-30",
            "--valid",
            "2026-02-01:2026-02-28",
            "--test",
            "2026-03-01:2026-09-14",
            "--no-manifest",
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "train.start" in err


def test_m5r2_export_cli_args_locked():
    """任务 2：as-of / topk 锁死；out-dir 约定与文档一致。"""
    assert M5R2_EXPORT_ASOF == "pred_minus_one"
    assert M5R2_EXPORT_TOPK == 10
    assert M5R2_EXPORT_OUT_DIR == "exports/m5r2_pred_topn10_20260302_20260914"
    args = export_build_parser().parse_args(
        [
            "--pred",
            "my_scripts/预测结果_ext.csv",
            "--out-dir",
            M5R2_EXPORT_OUT_DIR,
        ]
    )
    assert args.asof == M5R2_EXPORT_ASOF
    assert args.topk == M5R2_EXPORT_TOPK
    assert Path(args.out_dir).as_posix().endswith(M5R2_EXPORT_OUT_DIR)
