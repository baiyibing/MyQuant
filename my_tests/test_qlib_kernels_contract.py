"""Contract: production qlib.init sites nail kernels via resolve_qlib_kernels (default 1)."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_MY_SCRIPTS = _ROOT / "my_scripts"
if str(_MY_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_MY_SCRIPTS))

from handler_frame_cache import resolve_qlib_kernels  # noqa: E402

# Production / near-production entrypoints that must pass kernels= explicitly.
_PROD_INIT_FILES = [
    _ROOT / "my_scripts" / "predict_extended.py",
    _ROOT / "my_scripts" / "sweep_live_adapter.py",
    _ROOT / "my_scripts" / "feature_experiments.py",
    _ROOT / "my_scripts" / "build_winner_ratio.py",
    _ROOT / "my_scripts" / "calibrate_winner_ratio_proxy.py",
    _ROOT / "my_scripts" / "custom_train_backtest.py",
]

# Scoped paths that must not hard-code kernels=16 (handoff P0-1).
_NO_KERNELS_16 = [
    _ROOT / "my_scripts",
    _ROOT / "qlib_scripts" / "custom_train_backtest.py",
    _ROOT / "qlib_scripts" / "run_filter.py",
    _ROOT / "qlib_scripts" / "my_rolling_benchmark.py",
    _ROOT / "qlib_scripts" / "custom_train_backtest_1_save.py",
    _ROOT / "qlib_scripts" / "custom_train_backtest_2_reload.py",
    _ROOT / "qlib_scripts" / "custom_train_backtest_3_reload.py",
    _ROOT / "qlib_scripts" / "custom_train_backtest_f1_save.py",
    _ROOT / "qlib_scripts" / "custom_train_backtest_f3_reload.py",
]

def test_resolve_qlib_kernels_default_and_override(monkeypatch):
    monkeypatch.delenv("QLIB_KERNELS", raising=False)
    assert resolve_qlib_kernels() == 1
    monkeypatch.setenv("QLIB_KERNELS", "8")
    assert resolve_qlib_kernels() == 8
    monkeypatch.setenv("QLIB_KERNELS", "1")
    assert resolve_qlib_kernels() == 1


def _qlib_init_blocks(src: str) -> list[str]:
    """Extract approximate qlib.init(...) argument spans (handles nested parens)."""
    blocks: list[str] = []
    needle = "qlib.init"
    start = 0
    while True:
        i = src.find(needle, start)
        if i < 0:
            break
        j = src.find("(", i)
        if j < 0:
            break
        depth = 0
        k = j
        while k < len(src):
            ch = src[k]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    blocks.append(src[j + 1 : k])
                    break
            k += 1
        start = k + 1 if k < len(src) else len(src)
    return blocks


@pytest.mark.parametrize("path", _PROD_INIT_FILES, ids=lambda p: p.name)
def test_prod_qlib_init_passes_kernels(path: Path):
    src = path.read_text(encoding="utf-8")
    assert "resolve_qlib_kernels" in src, f"{path.name} must use resolve_qlib_kernels"
    inits = _qlib_init_blocks(src)
    assert inits, f"{path.name}: no qlib.init(...) found"
    assert any(re.search(r"\bkernels\s*=", body) for body in inits), (
        f"{path.name}: qlib.init must include kernels="
    )


def test_no_hardcoded_kernels_16_in_scoped_paths():
    offenders: list[str] = []
    for target in _NO_KERNELS_16:
        paths = [target] if target.is_file() else sorted(target.rglob("*.py"))
        for path in paths:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), 1):
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if "kernels=16" in line or "kernels = 16" in line:
                    offenders.append(f"{path.relative_to(_ROOT)}:{i}:{line.strip()}")
    assert not offenders, "hard-coded kernels=16 still present:\n" + "\n".join(offenders)


def test_winner_ratio_scripts_no_kernels_8():
    for name in ("build_winner_ratio.py", "calibrate_winner_ratio_proxy.py"):
        path = _MY_SCRIPTS / name
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            assert "kernels=8" not in line and "kernels = 8" not in line, (
                f"{name}:{i} still hard-codes kernels=8: {line.strip()}"
            )
