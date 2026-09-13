# -*- coding: utf-8 -*-
"""sweep_live_adapter: set_segments 校验 + payload config 含生效窗口。"""

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

import sweep_live_adapter as sla  # noqa: E402
from run_manifest import load_manifest  # noqa: E402
from sweep_ranking import SweepConfig, run_one  # noqa: E402


MARCH = {
    "train": ("2026-01-01", "2026-01-31"),
    "valid": ("2026-02-01", "2026-02-28"),
    "test": ("2026-03-01", "2026-03-23"),
}
OOS = {
    "train": ("2026-01-01", "2026-01-31"),
    "valid": ("2026-02-01", "2026-02-28"),
    "test": ("2026-04-01", "2026-08-31"),
}


@pytest.fixture(autouse=True)
def _reset_adapter():
    sla._ACTIVE_SEGMENTS.clear()
    sla._ACTIVE_SEGMENTS.update({k: (v[0], v[1]) for k, v in sla.SEGMENTS.items()})
    sla._STATE.clear()
    yield
    sla._ACTIVE_SEGMENTS.clear()
    sla._ACTIVE_SEGMENTS.update({k: (v[0], v[1]) for k, v in sla.SEGMENTS.items()})
    sla._STATE.clear()


def test_segments_constant_is_march_default():
    assert sla.SEGMENTS == MARCH
    assert sla.get_segments() == MARCH


def test_set_segments_accepts_oos_and_keeps_constant():
    sla.set_segments(OOS)
    assert sla.get_segments() == OOS
    # 常量不被污染
    assert sla.SEGMENTS == MARCH


def test_set_segments_rejects_missing_segment():
    with pytest.raises(ValueError, match="missing"):
        sla.set_segments({"train": MARCH["train"], "valid": MARCH["valid"]})


def test_set_segments_rejects_illegal_dates():
    with pytest.raises(ValueError):
        sla.set_segments(
            {
                "train": ("2026-01-01", "2026-01-31"),
                "valid": ("not-a-date", "2026-02-28"),
                "test": ("2026-03-01", "2026-03-23"),
            }
        )
    with pytest.raises(ValueError):
        sla.set_segments(
            {
                "train": ("2026-01-31", "2026-01-01"),
                "valid": MARCH["valid"],
                "test": MARCH["test"],
            }
        )


def test_set_segments_rejects_ordering():
    """train.start <= valid.start <= test.start。"""
    with pytest.raises(ValueError, match="train.start"):
        sla.set_segments(
            {
                "train": ("2026-03-01", "2026-03-31"),
                "valid": ("2026-02-01", "2026-02-28"),
                "test": ("2026-04-01", "2026-04-30"),
            }
        )
    with pytest.raises(ValueError, match="train.start"):
        sla.set_segments(
            {
                "train": ("2026-01-01", "2026-01-31"),
                "valid": ("2026-04-01", "2026-04-30"),
                "test": ("2026-03-01", "2026-03-23"),
            }
        )


def test_handler_span_min_start_max_end():
    start, end = sla._handler_span(OOS)
    assert start == "2026-01-01"
    assert end == "2026-08-31"
    start, end = sla._handler_span(MARCH)
    assert start == "2026-01-01"
    assert end == "2026-03-23"


def _toy_pred_label():
    days = pd.to_datetime(["2026-03-02", "2026-03-03", "2026-03-04"])
    insts = ["SH600000", "SH600001", "SH600002"]
    idx = pd.MultiIndex.from_product([days, insts], names=["datetime", "instrument"])
    pred = pd.Series(
        [0.3, 0.2, 0.1, 0.25, 0.15, 0.05, 0.4, 0.1, 0.2],
        index=idx,
    )
    label = pd.Series(
        [0.01, -0.01, 0.02, 0.01, 0.0, -0.02, 0.03, -0.01, 0.01],
        index=idx,
    )
    return pred, label


def test_payload_config_contains_effective_segments(monkeypatch: pytest.MonkeyPatch):
    pred, label = _toy_pred_label()
    monkeypatch.setattr(sla, "_predict_once", lambda: (pred, label))
    sla.set_segments(OOS)
    payload = sla.train_predict_fn(SweepConfig(10, 3, 1))
    assert "ic" in payload and "ir" in payload
    assert "config" in payload
    segs = payload["config"]["segments"]
    assert segs["train"] == ["2026-01-01", "2026-01-31"]
    assert segs["valid"] == ["2026-02-01", "2026-02-28"]
    assert segs["test"] == ["2026-04-01", "2026-08-31"]


def test_payload_config_default_segments_without_set(monkeypatch: pytest.MonkeyPatch):
    """未调 set_segments 时 payload 仍带默认三月窗，manifest 可区分。"""
    pred, label = _toy_pred_label()
    monkeypatch.setattr(sla, "_predict_once", lambda: (pred, label))
    payload = sla.train_predict_fn(SweepConfig(5, 2, 1))
    segs = payload["config"]["segments"]
    assert segs["train"] == ["2026-01-01", "2026-01-31"]
    assert segs["valid"] == ["2026-02-01", "2026-02-28"]
    assert segs["test"] == ["2026-03-01", "2026-03-23"]


def test_manifest_receives_payload_segments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pred, label = _toy_pred_label()
    monkeypatch.setattr(sla, "_predict_once", lambda: (pred, label))
    sla.set_segments(OOS)
    result = run_one(
        SweepConfig(10, 3, 1),
        train_predict_fn=sla.train_predict_fn,
        manifests_dir=tmp_path / "manifests",
        repo_root=_ROOT,
        write_manifests=True,
    )
    man = load_manifest(result.manifest_path)
    segs = man["config"]["segments"]
    assert segs["test"] == ["2026-04-01", "2026-08-31"]
    assert man["config"]["topk"] == 10
    assert man["config"]["stage_kind"] == "ranking_sweep"
