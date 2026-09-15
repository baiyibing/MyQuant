"""eng-perf P1-3: default train path must not full-fetch feature matrices."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_MY_SCRIPTS = _ROOT / "my_scripts"
if str(_MY_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_MY_SCRIPTS))

from train_wiring import parse_train_cli, verify_limit_up_filter  # noqa: E402

_TRAIN_SRC = _MY_SCRIPTS / "custom_train_backtest.py"
_WIRING_SRC = _MY_SCRIPTS / "train_wiring.py"

_FORBIDDEN = (
    "handler.fetch",
    '.fetch(col_set="feature")',
    ".fetch(col_set='feature')",
)


def _strip_verify_filters_block(src: str) -> str:
    """Drop the indented body of ``if verify_filters:`` (opt-in contrast path)."""
    lines = src.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r"^(\s*)if verify_filters\s*:", line):
            indent = len(line) - len(line.lstrip(" \t"))
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if nxt.strip() == "":
                    i += 1
                    continue
                nxt_indent = len(nxt) - len(nxt.lstrip(" \t"))
                if nxt_indent > indent:
                    i += 1
                    continue
                break
            continue
        out.append(line)
        i += 1
    return "".join(out)


def test_preview_rows_cli_default_zero():
    args = parse_train_cli([])
    assert args.preview_rows == 0
    args_n = parse_train_cli(["--preview-rows", "5"])
    assert args_n.preview_rows == 5


def test_custom_train_default_path_no_handler_fetch():
    src = _TRAIN_SRC.read_text(encoding="utf-8")
    default_path = _strip_verify_filters_block(src)
    offenders: list[str] = []
    for i, line in enumerate(default_path.splitlines(), 1):
        for needle in _FORBIDDEN:
            if needle in line:
                offenders.append(f"{i}:{needle}:{line.strip()}")
    assert not offenders, (
        "default train path must not mention full feature fetch:\n" + "\n".join(offenders)
    )


def test_custom_train_uses_handler_feature_names_timer():
    src = _TRAIN_SRC.read_text(encoding="utf-8")
    assert 'timer("handler_feature_names")' in src
    assert 'timer("handler_fetch_feature")' not in src
    assert "get_feature_config()" in src
    assert "preview_rows" in src


def test_verify_limit_up_filter_doc_marks_oom_opt_in():
    src = _WIRING_SRC.read_text(encoding="utf-8")
    # Function exists and still fetches (opt-in algorithm unchanged).
    assert "def verify_limit_up_filter" in src
    assert '.fetch(col_set="feature")' in src
    doc = ast.get_docstring(
        next(
            n
            for n in ast.parse(src).body
            if isinstance(n, ast.FunctionDef) and n.name == "verify_limit_up_filter"
        )
    )
    assert doc is not None
    lower = doc.lower()
    assert "opt-in" in lower or "opt_in" in lower or "opt in" in lower
    assert "oom" in lower


def test_verify_limit_up_filter_emits_warn(capsys):
    class _FakeHandler:
        def fetch(self, col_set="feature"):
            import pandas as pd

            return pd.DataFrame({"OTHER": [1]})

    with pytest.raises(ValueError):
        verify_limit_up_filter(
            _FakeHandler(), _FakeHandler(), {"train": ("2026-01-01", "2026-01-31")}
        )
    out = capsys.readouterr().out
    assert "[WARN]" in out
    assert "OOM" in out
