# -*- coding: utf-8 -*-
"""M2-B: chip_parity_check harness (injected fake bt; map 不可比 soft-pass)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from chip_parity_check import (  # noqa: E402
    DEFAULT_RTOL,
    DEFAULT_SYMBOLS,
    compare_quantity_maps,
    format_report,
    is_incomparable,
    load_mapping_conclusion,
    main,
    parse_mapping_conclusion,
    relative_diff,
    run_check,
    values_agree,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "chip_parity"
_MAP = Path(_ROOT) / "docs" / "chip-parity-map.md"


def test_map_marker_is_incomparable():
    conclusion = load_mapping_conclusion(_MAP)
    assert is_incomparable(conclusion)
    assert "不可比" in conclusion


def test_parse_mapping_conclusion_tolerates_markdown():
    text = "**总结论：`MAPPING_CONCLUSION=不可比`**（说明）\n"
    assert parse_mapping_conclusion(text) == "不可比"


def test_relative_diff_and_agree():
    assert relative_diff(1.0, 1.0 + 1e-5) < DEFAULT_RTOL
    assert values_agree(1.0, 1.0 + 5e-5, rtol=1e-4)
    assert not values_agree(1.0, 1.1, rtol=1e-4)
    assert relative_diff(float("nan"), 1.0) == float("inf")


def test_compare_agree_and_disagree():
    ok = compare_quantity_maps({"a": 1.0}, {"a": 1.0}, rtol=1e-4)
    assert ok.ok and not ok.disagreements
    bad = compare_quantity_maps({"a": 1.0}, {"a": 2.0}, rtol=1e-4)
    assert not bad.ok and len(bad.disagreements) == 1


def test_incomparable_live_exits_zero_without_faking(capsys):
    """Real map says 不可比 → CLI exit 0 and report not comparable."""
    code = main(
        [
            "--map",
            str(_MAP),
            "--bt-repo",
            "/workspace/MyQuant-backtrader",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "comparable=False" in out
    assert "not comparable" in out.lower() or "不可比" in out


def test_cli_injected_json_agree_exit_0(tmp_path, capsys):
    code = main(
        [
            "--map",
            str(_MAP),
            "--myquant-values-json",
            str(_FIXTURES / "mq_agree.json"),
            "--bt-values-json",
            str(_FIXTURES / "bt_agree.json"),
            "--rtol",
            "1e-4",
            "--report-out",
            str(tmp_path / "r.txt"),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "comparable=True" in out
    assert "disagreements=0" in out
    assert (tmp_path / "r.txt").is_file()


def test_cli_injected_json_disagree_exit_1(capsys):
    code = main(
        [
            "--map",
            str(_MAP),
            "--myquant-values-json",
            str(_FIXTURES / "mq_agree.json"),
            "--bt-values-json",
            str(_FIXTURES / "bt_disagree.json"),
            "--rtol",
            "1e-4",
        ]
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "DISAGREE:" in out


def test_injected_fake_bt_module_agree_and_disagree():
    mq = {"x": 10.0, "y": 0.5}

    class FakeAgree:
        def compute_chip_values(self, symbols, start, end):
            assert "600000" in symbols
            return {"x": 10.0, "y": 0.5}

    class FakeDisagree:
        def compute_chip_values(self, symbols, start, end):
            return {"x": 10.0, "y": 9.9}

    r_ok = run_check(
        map_path=_MAP,
        myquant_values=mq,
        bt_inject=FakeAgree(),
        rtol=1e-4,
    )
    assert r_ok.comparable and r_ok.ok

    r_bad = run_check(
        map_path=_MAP,
        myquant_values=mq,
        bt_inject=FakeDisagree(),
        rtol=1e-4,
    )
    assert r_bad.comparable and not r_bad.ok
    assert any("y:" in d for d in r_bad.disagreements)


def test_default_symbols_include_bj_and_eight():
    assert len(DEFAULT_SYMBOLS) == 8
    assert "600000" in DEFAULT_SYMBOLS
    assert "300190" in DEFAULT_SYMBOLS
    assert "920014" in DEFAULT_SYMBOLS


def test_golden_meta_fixture():
    meta = json.loads((_FIXTURES / "golden_meta.json").read_text(encoding="utf-8"))
    assert meta["window_start"] == "2026-03-02"
    assert meta["window_end"] == "2026-03-23"
    assert len(meta["symbols"]) == 8
    assert meta["mapping_conclusion"] == "不可比"


def test_format_report_includes_ok_flag():
    r = compare_quantity_maps({"a": 1.0}, {"a": 1.0})
    text = format_report(r)
    assert "ok=True" in text
