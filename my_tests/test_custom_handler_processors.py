"""Q3-R2: Alpha158CostKDJ must pass infer/learn processors into Alpha158.__init__."""

from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from custom_handler import (  # noqa: E402
    Alpha158CostKDJ,
    _DEFAULT_INFER_PROCESSORS,
    _DEFAULT_LEARN_PROCESSORS,
)


@pytest.fixture
def capture_alpha158_init(monkeypatch):
    """Monkeypatch Alpha158.__init__ so no qlib data is fetched."""
    captured: dict = {}

    def fake_init(self, *args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        # Minimal attrs some code may touch; no DataHandler setup.
        self.infer_processors = kwargs.get("infer_processors")
        self.learn_processors = kwargs.get("learn_processors")

    monkeypatch.setattr("custom_handler.Alpha158.__init__", fake_init)
    return captured


def test_default_processors_passed_to_super(capture_alpha158_init):
    Alpha158CostKDJ(instruments="all", start_time="2026-01-01", end_time="2026-01-02")
    kwargs = capture_alpha158_init["kwargs"]
    assert "infer_processors" in kwargs
    assert "learn_processors" in kwargs
    assert kwargs["infer_processors"] == _DEFAULT_INFER_PROCESSORS
    assert kwargs["learn_processors"] == _DEFAULT_LEARN_PROCESSORS


def test_caller_processors_override_defaults(capture_alpha158_init):
    custom_infer = [{"class": "Fillna", "kwargs": {}}]
    custom_learn = [{"class": "DropnaLabel"}]
    Alpha158CostKDJ(
        instruments="all",
        start_time="2026-01-01",
        end_time="2026-01-02",
        infer_processors=custom_infer,
        learn_processors=custom_learn,
    )
    kwargs = capture_alpha158_init["kwargs"]
    assert kwargs["infer_processors"] is custom_infer
    assert kwargs["learn_processors"] is custom_learn
