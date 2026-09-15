# -*- coding: utf-8 -*-
"""TimerRecorder rollup / D.features probe（不触发 qlib.init）。"""

from __future__ import annotations

import json
import os
import sys
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from custom_utils import (  # noqa: E402
    TimerRecorder,
    install_features_probe,
    maybe_timer,
    set_global_timer_recorder,
)
from run_manifest import timings_from_recorder  # noqa: E402


def test_rollup_groups_repeated_names():
    rec = TimerRecorder()
    rec.nodes.append({"name": "foo", "seconds": 1.0})
    rec.nodes.append({"name": "foo", "seconds": 3.0})
    rec.nodes.append({"name": "bar", "seconds": 2.0})
    rows = rec.rollup()
    by = {r["name"]: r for r in rows}
    assert by["foo"]["count"] == 2
    assert by["foo"]["seconds"] == 4.0
    assert by["foo"]["max"] == 3.0
    assert by["foo"]["mean"] == 2.0
    assert rows[0]["name"] == "foo"


def test_increment_and_as_timings(tmp_path):
    rec = TimerRecorder()
    rec.increment("D.features", n=1, seconds=0.5, instruments=10, fields=2)
    rec.increment("D.features", n=1, seconds=1.5, instruments=20, fields=2)
    slot = rec.counters["D.features"]
    assert slot["count"] == 2
    assert abs(slot["seconds"] - 2.0) < 1e-9
    assert slot["max_seconds"] == 1.5
    assert slot["instruments"] == 30
    payload = rec.as_timings()
    assert "rollup" in payload and "counters" in payload
    dest = tmp_path / "timing.json"
    rec.dump_json(str(dest), extra={"exp_name": "unit"})
    loaded = json.loads(dest.read_text(encoding="utf-8"))
    assert loaded["exp_name"] == "unit"
    assert loaded["counters"]["D.features"]["count"] == 2


def test_features_probe_counts_and_slow(monkeypatch):
    class FakeD:
        def features(self, instruments, fields, start_time=None, end_time=None, **kwargs):
            if kwargs.get("sleep"):
                time.sleep(0.02)
            return (instruments, fields)

    fake = FakeD()
    rec = TimerRecorder()
    uninstall = install_features_probe(rec, target=fake, slow_seconds=0.01)
    try:
        fake.features(["SH600000", "SZ000001"], ["$close", "$open"])
        fake.features(["SH600000"], ["$close"], sleep=True)
    finally:
        uninstall()
    slot = rec.counters["D.features"]
    assert slot["count"] == 2
    assert slot["instruments"] == 3
    assert slot["fields"] == 3
    slow = [n for n in rec.nodes if n["name"] == "D.features.slow"]
    assert len(slow) == 1
    fake.features(["X"], ["$close"])  # uninstalled: no more counts
    assert rec.counters["D.features"]["count"] == 2


def test_maybe_timer_and_manifest_payload():
    rec = TimerRecorder()
    set_global_timer_recorder(rec)
    try:
        with maybe_timer("unit.span"):
            time.sleep(0.01)
        payload = timings_from_recorder(rec)
        assert payload["nodes"][0]["name"] == "unit.span"
        assert payload["rollup"][0]["name"] == "unit.span"
        assert payload["counters"] == {}
    finally:
        set_global_timer_recorder(None)

    with maybe_timer("no_recorder"):
        pass
