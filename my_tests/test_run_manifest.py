# -*- coding: utf-8 -*-
"""M4-A: run_manifest 构建 / 校验 / 写盘单测。"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from run_manifest import (  # noqa: E402
    SCHEMA_ID,
    ManifestError,
    build_manifest,
    canonical_json,
    config_hash,
    fingerprint_artifact,
    load_manifest,
    manifest_to_json_bytes,
    md5_file,
    unknown_timings,
    validate_manifest,
    write_manifest,
    write_sweep_parent_manifest,
)


def test_config_hash_deterministic_same_input():
    cfg = {"topk": 10, "n_drop": 3, "segments": {"train": ["2026-01-01", "2026-01-31"]}}
    h1 = config_hash(cfg)
    h2 = config_hash(dict(reversed(list(cfg.items()))))
    assert h1 == h2
    assert h1 == hashlib.sha256(canonical_json(cfg).encode("utf-8")).hexdigest()
    # config_hash key ignored if present
    assert config_hash({**cfg, "config_hash": "deadbeef"}) == h1


def test_build_manifest_embeds_matching_config_hash():
    m = build_manifest(
        stage="train",
        config={"topk": 10},
        git_commit_sha="abc123",
        created_utc="2026-09-13T01:00:00Z",
    )
    assert m["schema"] == SCHEMA_ID
    assert m["stage"] == "train"
    assert m["git_commit"] == "abc123"
    assert m["config"]["topk"] == 10
    assert m["config"]["config_hash"] == config_hash({"topk": 10})
    validate_manifest(m)


def test_artifact_fingerprints(tmp_path: Path):
    f = tmp_path / "pred.csv"
    payload = b"datetime,instrument,score\n2026-03-02,600000,1\n"
    f.write_bytes(payload)
    expected_md5 = hashlib.md5(payload).hexdigest()
    assert md5_file(f) == expected_md5
    art = fingerprint_artifact(f, rows=1, base_dir=tmp_path)
    assert art == {"path": "pred.csv", "md5": expected_md5, "rows": 1}


def test_write_manifest_utf8_no_bom_and_sidecar(tmp_path: Path):
    art_dir = tmp_path / "exports" / "pool"
    art_dir.mkdir(parents=True)
    pred = art_dir / "pred.csv"
    pred.write_text("x\n", encoding="utf-8")
    art = fingerprint_artifact(pred, rows=1, base_dir=art_dir)
    m = build_manifest(
        stage="export",
        config={"asof": "pred_minus_one", "topk": 10},
        artifacts=[art],
        data={"calendar_first": "2026-03-02", "calendar_last": "2026-03-09", "calendar_days": 2},
        timings={"total_seconds": 1.5, "nodes": [{"name": "export", "seconds": 1.5}]},
        git_commit_sha="deadbeef",
        created_utc="2026-09-13T02:03:04Z",
    )
    written = write_manifest(
        m,
        manifests_dir=tmp_path / "manifests",
        artifact_dirs=[art_dir],
    )
    assert len(written) == 2
    primary, sidecar = written
    assert primary.name == "export_20260913T020304Z.json"
    assert sidecar.parent == art_dir
    raw = primary.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert sidecar.read_bytes() == raw
    loaded = load_manifest(primary)
    assert loaded["artifacts"][0]["md5"] == art["md5"]


def test_reject_bad_schema():
    with pytest.raises(ManifestError, match="bad schema"):
        validate_manifest(
            {
                "schema": "other/1",
                "stage": "train",
                "git_commit": "x",
                "created_utc": "2026-09-13T00:00:00Z",
                "config": {"config_hash": config_hash({})},
                "data": {},
                "artifacts": [],
                "timings": {},
            }
        )


def test_reject_bad_stage_and_hash_and_artifact():
    with pytest.raises(ManifestError, match="unsupported stage"):
        build_manifest(stage="infer")
    m = build_manifest(stage="refresh", config={"x": 1}, git_commit_sha="g")
    m["config"]["config_hash"] = "0" * 32
    with pytest.raises(ManifestError, match="config_hash mismatch"):
        validate_manifest(m)
    m2 = build_manifest(stage="train", git_commit_sha="g")
    m2["artifacts"] = [{"path": "a.csv", "md5": "ZZ"}]
    with pytest.raises(ManifestError, match="md5"):
        validate_manifest(m2)


def test_manifest_to_json_bytes_roundtrip():
    m = build_manifest(stage="train", config={"a": 1}, git_commit_sha="g", created_utc="2026-09-13T00:00:00Z")
    raw = manifest_to_json_bytes(m)
    assert isinstance(raw, bytes)
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert json.loads(raw.decode("utf-8"))["config"]["a"] == 1


def test_write_sweep_parent_manifest(tmp_path: Path):
    written = write_sweep_parent_manifest(
        manifests_dir=tmp_path / "manifests",
        parent_id="20260915T010203Z_deadbeef",
        shared_handler_cache_key="abc" * 10 + "abcd",  # 64-ish
        arm_ids=[
            {"grid_id": "topk5_ndrop1_hold1", "manifest_path": "train_sweep_a.json"},
            {"grid_id": "topk10_ndrop1_hold1", "manifest_path": "train_sweep_b.json"},
        ],
        timings={
            "total_seconds": 12.5,
            "nodes": [
                {"name": "init_once", "seconds": 12.0},
                {"name": "predict_once", "seconds": 0.5},
            ],
        },
        segments={
            "train": ["2026-01-01", "2026-01-31"],
            "valid": ["2026-02-01", "2026-02-28"],
            "test": ["2026-03-01", "2026-03-23"],
        },
        git_commit_sha="deadbeef",
        created_utc="2026-09-15T01:02:03Z",
    )
    assert len(written) == 1
    assert written[0].name == "sweep_parent_20260915T010203Z_deadbeef.json"
    man = load_manifest(written[0])
    assert man["stage"] == "sweep_parent"
    assert man["data"]["parent_id"] == "20260915T010203Z_deadbeef"
    assert man["data"]["shared_handler_cache_key"].startswith("abc")
    assert len(man["data"]["arm_ids"]) == 2
    assert man["config"]["segments"]["test"] == ["2026-03-01", "2026-03-23"]
    names = [n["name"] for n in man["timings"]["nodes"]]
    assert "init_once" in names and "predict_once" in names
    assert man["timings"]["total_seconds"] == pytest.approx(12.5)
    assert man["timings"].get("unknown") is not True


def test_write_sweep_parent_unknown_timings_no_fake_zero(tmp_path: Path):
    written = write_sweep_parent_manifest(
        manifests_dir=tmp_path / "manifests",
        parent_id="parent_unknown",
        timings=None,
        git_commit_sha="g",
    )
    man = load_manifest(written[0])
    assert man["timings"] == unknown_timings() or (
        man["timings"].get("unknown") is True
        and man["timings"]["total_seconds"] is None
        and man["timings"]["nodes"] == []
    )
    assert man["timings"]["total_seconds"] is None
