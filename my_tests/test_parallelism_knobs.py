"""eng-perf P1-1: three independent parallelism knobs (kernels / dump / LGB)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_MY_SCRIPTS = _ROOT / "my_scripts"
_QLIB_SCRIPTS = _ROOT / "qlib_scripts"
if str(_MY_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_MY_SCRIPTS))
if str(_QLIB_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_QLIB_SCRIPTS))

from handler_frame_cache import (  # noqa: E402
    DEFAULT_DUMP_MAX_WORKERS,
    DEFAULT_LGB_NUM_THREADS,
    log_parallelism_knobs,
    resolve_dump_max_workers,
    resolve_lgb_num_threads,
    resolve_qlib_kernels,
)
from refresh_mydata import DEFAULT_MAX_WORKERS  # noqa: E402


def test_defaults_three_knobs(monkeypatch):
    monkeypatch.delenv("QLIB_KERNELS", raising=False)
    monkeypatch.delenv("QLIB_DUMP_MAX_WORKERS", raising=False)
    monkeypatch.delenv("LGB_NUM_THREADS", raising=False)
    assert resolve_qlib_kernels() == 1
    assert resolve_dump_max_workers() == 8
    assert resolve_lgb_num_threads() == 20
    assert DEFAULT_DUMP_MAX_WORKERS == DEFAULT_MAX_WORKERS == 8
    assert DEFAULT_LGB_NUM_THREADS == 20


def test_env_overrides_independent(monkeypatch):
    monkeypatch.setenv("QLIB_KERNELS", "4")
    monkeypatch.setenv("QLIB_DUMP_MAX_WORKERS", "2")
    monkeypatch.setenv("LGB_NUM_THREADS", "7")
    assert resolve_qlib_kernels() == 4
    assert resolve_dump_max_workers() == 2
    assert resolve_lgb_num_threads() == 7
    # Changing one must not affect others
    monkeypatch.setenv("QLIB_KERNELS", "1")
    assert resolve_qlib_kernels() == 1
    assert resolve_dump_max_workers() == 2
    assert resolve_lgb_num_threads() == 7


def test_dump_rejects_16(monkeypatch, capsys):
    monkeypatch.setenv("QLIB_DUMP_MAX_WORKERS", "16")
    assert resolve_dump_max_workers() == 8
    out = capsys.readouterr().out
    assert "16" in out
    assert "forbidden" in out.lower()


def test_log_parallelism_knobs_line(monkeypatch, capsys):
    monkeypatch.delenv("QLIB_KERNELS", raising=False)
    monkeypatch.delenv("QLIB_DUMP_MAX_WORKERS", raising=False)
    monkeypatch.delenv("LGB_NUM_THREADS", raising=False)
    vals = log_parallelism_knobs()
    assert vals == {"kernels": 1, "dump_max_workers": 8, "lgb_num_threads": 20}
    line = capsys.readouterr().out
    assert "[parallelism]" in line
    assert "kernels=1 (QLIB_KERNELS)" in line
    assert "dump_max_workers=8 (QLIB_DUMP_MAX_WORKERS)" in line
    assert "lgb_num_threads=20 (LGB_NUM_THREADS)" in line


def test_custom_train_uses_resolve_lgb_not_bare_20():
    src = (_MY_SCRIPTS / "custom_train_backtest.py").read_text(encoding="utf-8")
    assert "resolve_lgb_num_threads" in src
    assert "log_parallelism_knobs" in src
    # LGB kwargs must not hard-code a bare 20 for num_threads
    assert re.search(r'"num_threads"\s*:\s*_lgb_threads', src), (
        "custom_train_backtest must pass resolve_lgb_num_threads() into LGB kwargs"
    )
    for i, line in enumerate(src.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if re.search(r'"num_threads"\s*:\s*20\b', line):
            pytest.fail(f"custom_train_backtest.py:{i} still hard-codes num_threads: 20")


def test_custom_train_qlib_init_no_kernels_16():
    src = (_MY_SCRIPTS / "custom_train_backtest.py").read_text(encoding="utf-8")
    for i, line in enumerate(src.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        assert "kernels=16" not in line and "kernels = 16" not in line, (
            f"custom_train_backtest.py:{i} has literal kernels=16"
        )


def test_manifest_writes_three_knobs():
    src = (_MY_SCRIPTS / "custom_train_backtest.py").read_text(encoding="utf-8")
    assert '"qlib_kernels"' in src or "'qlib_kernels'" in src
    assert '"dump_max_workers"' in src
    assert '"lgb_num_threads"' in src


def test_refresh_documents_three_knob_split():
    src = (_QLIB_SCRIPTS / "refresh_mydata.py").read_text(encoding="utf-8")
    assert "三钮" in src or "P1-1" in src or "eng-perf P1-1" in src
    assert "DEFAULT_MAX_WORKERS = 8" in src
    # Must not feed dump workers into a live qlib.init(kernels=) call
    for i, line in enumerate(src.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        assert "qlib.init" not in line, f"refresh_mydata.py:{i} must not call qlib.init"
