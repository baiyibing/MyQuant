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
    monkeypatch.setattr(sla, "_build_pred_label", lambda: (pred, label))
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
    monkeypatch.setattr(sla, "_build_pred_label", lambda: (pred, label))
    payload = sla.train_predict_fn(SweepConfig(5, 2, 1))
    segs = payload["config"]["segments"]
    assert segs["train"] == ["2026-01-01", "2026-01-31"]
    assert segs["valid"] == ["2026-02-01", "2026-02-28"]
    assert segs["test"] == ["2026-03-01", "2026-03-23"]


def test_manifest_receives_payload_segments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pred, label = _toy_pred_label()
    monkeypatch.setattr(sla, "_build_pred_label", lambda: (pred, label))
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


def test_make_shared_handler_cache_key_stable_and_segment_sensitive():
    k1 = sla.make_shared_handler_cache_key(MARCH)
    k2 = sla.make_shared_handler_cache_key(MARCH)
    assert k1 == k2
    assert isinstance(k1, str) and len(k1) == 64
    k_oos = sla.make_shared_handler_cache_key(OOS)
    assert k_oos != k1


def test_init_once_three_arms_same_key(monkeypatch: pytest.MonkeyPatch):
    """同一 segments 下 3 臂只构建 1 次；首臂 INIT_ONCE，后两臂 ARM_ONLY。"""
    pred, label = _toy_pred_label()
    builds = {"n": 0}

    def fake_build():
        builds["n"] += 1
        return pred, label

    monkeypatch.setattr(sla, "_build_pred_label", fake_build)

    payloads = []
    for topk in (5, 10, 20):
        payloads.append(sla.train_predict_fn(SweepConfig(topk, 2, 1)))

    assert builds["n"] == 1
    keys = [p["data"]["shared_handler_cache_key"] for p in payloads]
    assert keys[0] == keys[1] == keys[2]
    assert keys[0] == sla.make_shared_handler_cache_key(MARCH)
    assert payloads[0]["data"]["arm_mode"] == "INIT_ONCE"
    assert payloads[1]["data"]["arm_mode"] == "ARM_ONLY"
    assert payloads[2]["data"]["arm_mode"] == "ARM_ONLY"

    init_names = [n["name"] for n in payloads[0]["timings"]["nodes"]]
    assert "init_once" in init_names or "handler_init" in init_names
    arm_names = [n["name"] for n in payloads[1]["timings"]["nodes"]]
    assert "arm_only" in arm_names
    assert payloads[1]["timings"].get("unknown") is not True


def test_set_segments_forces_rebuild_and_new_key(monkeypatch: pytest.MonkeyPatch):
    """换窗后必须重新构建且 shared_handler_cache_key 变化。"""
    pred, label = _toy_pred_label()
    builds = {"n": 0}

    def fake_build():
        builds["n"] += 1
        return pred, label

    monkeypatch.setattr(sla, "_build_pred_label", fake_build)

    p1 = sla.train_predict_fn(SweepConfig(5, 2, 1))
    assert builds["n"] == 1
    assert p1["data"]["arm_mode"] == "INIT_ONCE"
    key1 = p1["data"]["shared_handler_cache_key"]

    # same window arm
    p2 = sla.train_predict_fn(SweepConfig(10, 3, 1))
    assert builds["n"] == 1
    assert p2["data"]["arm_mode"] == "ARM_ONLY"
    assert p2["data"]["shared_handler_cache_key"] == key1

    sla.set_segments(OOS)
    assert "pred" not in sla._STATE
    assert "shared_handler_cache_key" not in sla._STATE

    p3 = sla.train_predict_fn(SweepConfig(5, 2, 1))
    assert builds["n"] == 2
    assert p3["data"]["arm_mode"] == "INIT_ONCE"
    key2 = p3["data"]["shared_handler_cache_key"]
    assert key2 != key1
    assert key2 == sla.make_shared_handler_cache_key(OOS)


def test_manifest_receives_arm_mode_and_cache_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pred, label = _toy_pred_label()
    monkeypatch.setattr(sla, "_build_pred_label", lambda: (pred, label))
    man_dir = tmp_path / "manifests"
    r1 = run_one(
        SweepConfig(5, 2, 1),
        train_predict_fn=sla.train_predict_fn,
        manifests_dir=man_dir,
        repo_root=_ROOT,
        write_manifests=True,
    )
    r2 = run_one(
        SweepConfig(10, 3, 1),
        train_predict_fn=sla.train_predict_fn,
        manifests_dir=man_dir,
        repo_root=_ROOT,
        write_manifests=True,
    )
    m1 = load_manifest(r1.manifest_path)
    m2 = load_manifest(r2.manifest_path)
    assert m1["data"]["arm_mode"] == "INIT_ONCE"
    assert m2["data"]["arm_mode"] == "ARM_ONLY"
    assert m1["data"]["shared_handler_cache_key"] == m2["data"]["shared_handler_cache_key"]
    assert m1["timings"]["nodes"]
    assert any(n["name"] in {"init_once", "handler_init"} for n in m1["timings"]["nodes"])
    assert any(n["name"] == "arm_only" for n in m2["timings"]["nodes"])



def _write_toy_pred_label_csvs(tmp_path: Path):
    pred, label = _toy_pred_label()
    pred_path = tmp_path / "pred.csv"
    label_path = tmp_path / "label.csv"
    sla.write_pred_artifact(pred, pred_path, label=label, segments=MARCH)
    # write_pred_artifact also writes .label.csv sidecar; keep explicit label_path
    return pred_path, sla._label_sidecar_path(pred_path), pred, label


def test_pred_from_hit_skips_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pred_path, label_path, _pred, _label = _write_toy_pred_label_csvs(tmp_path)
    builds = {"n": 0}

    def boom():
        builds["n"] += 1
        raise AssertionError("_build_pred_label must not run on PRED_FROM HIT")

    monkeypatch.setattr(sla, "_build_pred_label", boom)
    sla.configure_pred_handoff(pred_from=pred_path, label_from=label_path)
    payload = sla.train_predict_fn(SweepConfig(5, 2, 1))
    assert builds["n"] == 0
    assert payload["data"]["arm_mode"] == "PRED_FROM"
    assert payload["pred_path"] == str(pred_path)
    assert payload["pred_md5"]
    assert payload["data"]["pred_md5"] == payload["pred_md5"]
    assert any(n["name"] == "pred_from" for n in payload["timings"]["nodes"])

    # second arm uses in-process cache
    p2 = sla.train_predict_fn(SweepConfig(10, 3, 1))
    assert builds["n"] == 0
    assert p2["data"]["arm_mode"] == "ARM_ONLY"


def test_pred_from_missing_file_miss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    missing = tmp_path / "nope.csv"
    builds = {"n": 0}

    def fake_build():
        builds["n"] += 1
        return _toy_pred_label()

    monkeypatch.setattr(sla, "_build_pred_label", fake_build)
    sla.configure_pred_handoff(pred_from=missing, label_from=tmp_path / "lab.csv")
    with pytest.raises(FileNotFoundError, match="missing_file"):
        sla.train_predict_fn(SweepConfig(5, 2, 1))
    assert builds["n"] == 0  # must not fall through to build


def test_pred_from_empty_table_miss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    empty = tmp_path / "empty.csv"
    empty.write_text("datetime,instrument,score\n", encoding="utf-8")
    label = tmp_path / "label.csv"
    label.write_text(
        "datetime,instrument,label\n2026-03-02,SH600000,0.01\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        sla, "_build_pred_label", lambda: (_ for _ in ()).throw(AssertionError("no build"))
    )
    sla.configure_pred_handoff(pred_from=empty, label_from=label)
    with pytest.raises(ValueError, match="empty"):
        sla.train_predict_fn(SweepConfig(5, 2, 1))


def test_pred_from_missing_label_miss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pred, _label = _toy_pred_label()
    pred_path = tmp_path / "pred_only.csv"
    # write pred without label sidecar / meta label_path
    frame = sla.series_to_pred_frame(pred)
    frame.to_csv(pred_path, index=False, encoding="utf-8", lineterminator="\n")
    monkeypatch.setattr(
        sla, "_build_pred_label", lambda: (_ for _ in ()).throw(AssertionError("no build"))
    )
    sla.configure_pred_handoff(pred_from=pred_path, label_from=None)
    with pytest.raises(ValueError, match="missing_label"):
        sla.train_predict_fn(SweepConfig(5, 2, 1))


def test_pred_from_key_mismatch_miss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pred_path, label_path, _p, _l = _write_toy_pred_label_csvs(tmp_path)
    # meta was written for MARCH; switch to OOS → key mismatch
    monkeypatch.setattr(
        sla, "_build_pred_label", lambda: (_ for _ in ()).throw(AssertionError("no build"))
    )
    sla.set_segments(OOS)
    sla.configure_pred_handoff(pred_from=pred_path, label_from=label_path)
    with pytest.raises(ValueError, match="shared_handler_cache_key mismatch|segments mismatch"):
        sla.train_predict_fn(SweepConfig(5, 2, 1))


def test_pred_out_then_pred_from_metrics_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pred, label = _toy_pred_label()
    monkeypatch.setattr(sla, "_build_pred_label", lambda: (pred, label))
    out = tmp_path / "handoff" / "pred.csv"
    sla.configure_pred_handoff(pred_out=out)
    live = sla.train_predict_fn(SweepConfig(5, 2, 1))
    assert live["data"]["arm_mode"] == "INIT_ONCE"
    assert Path(live["pred_path"]).is_file()
    assert live["pred_md5"]
    assert (tmp_path / "handoff" / "pred.csv.meta.json").is_file()
    assert sla._label_sidecar_path(out).is_file()

    # fresh process-like state: clear and load from disk
    sla._STATE.clear()
    sla._ACTIVE_SEGMENTS.clear()
    sla._ACTIVE_SEGMENTS.update({k: (v[0], v[1]) for k, v in sla.SEGMENTS.items()})
    builds = {"n": 0}

    def boom():
        builds["n"] += 1
        raise AssertionError("offline arm must not rebuild")

    monkeypatch.setattr(sla, "_build_pred_label", boom)
    sla.configure_pred_handoff(pred_from=out)  # label via sidecar/meta
    offline = sla.train_predict_fn(SweepConfig(5, 2, 1))
    assert builds["n"] == 0
    assert offline["data"]["arm_mode"] == "PRED_FROM"
    assert offline["ic"] == pytest.approx(live["ic"])
    assert offline["ir"] == pytest.approx(live["ir"])
    assert offline["pred_md5"] == live["pred_md5"]


# --- eng-perf P1-7: same-pred day ranks built once -------------------------


def _naive_simulate_list(pred, label, topk, n_drop, hold_thresh):
    """Reference: per-day xs + sort (pre-P1-7 semantics)."""
    held: dict[str, int] = {}
    daily = {}
    dates = sorted(pred.index.get_level_values(0).unique())
    for day in dates:
        scored = pred.xs(day).sort_values(ascending=False)
        ranked_pos = {inst: i for i, inst in enumerate(scored.index)}
        droppable = [s for s in held if held[s] >= hold_thresh and s in ranked_pos]
        droppable.sort(key=lambda s: ranked_pos[s], reverse=True)
        for s in droppable[:n_drop]:
            del held[s]
        for inst in scored.index:
            if len(held) >= topk:
                break
            held.setdefault(inst, 0)
        rets = [label.get((day, s)) for s in held]
        rets = [r for r in rets if r == r and r is not None]
        if rets:
            daily[day] = float(__import__("numpy").mean(rets))
        for s in list(held):
            held[s] += 1
    return pd.Series(daily, name="list_ret").sort_index()


def test_pred_day_ranks_built_once_across_arms(monkeypatch: pytest.MonkeyPatch):
    pred, label = _toy_pred_label()
    builds = {"n": 0}
    real = sla._prebuild_pred_day_ranks

    def wrapped(p):
        builds["n"] += 1
        return real(p)

    monkeypatch.setattr(sla, "_prebuild_pred_day_ranks", wrapped)
    for topk, n_drop, hold in ((2, 1, 1), (3, 1, 1), (2, 1, 2)):
        sla._simulate_list(pred, label, topk, n_drop, hold)
    assert builds["n"] == 1
    assert sla._STATE["pred_day_ranks"]["pred_id"] == id(pred)


def test_simulate_list_matches_naive_multi_arm():
    pred, label = _toy_pred_label()
    for topk, n_drop, hold in ((1, 1, 1), (2, 1, 1), (3, 2, 2), (5, 2, 1)):
        got = sla._simulate_list(pred, label, topk, n_drop, hold)
        exp = _naive_simulate_list(pred, label, topk, n_drop, hold)
        pd.testing.assert_series_equal(got, exp, check_names=True)


def test_set_segments_clears_pred_day_ranks(monkeypatch: pytest.MonkeyPatch):
    pred, label = _toy_pred_label()
    sla._simulate_list(pred, label, 2, 1, 1)
    assert "pred_day_ranks" in sla._STATE
    sla.set_segments(OOS)
    assert "pred_day_ranks" not in sla._STATE


def test_configure_pred_handoff_clears_pred_day_ranks():
    pred, label = _toy_pred_label()
    sla._simulate_list(pred, label, 2, 1, 1)
    assert "pred_day_ranks" in sla._STATE
    sla.configure_pred_handoff(pred_from=None, label_from=None, pred_out=None)
    assert "pred_day_ranks" not in sla._STATE
