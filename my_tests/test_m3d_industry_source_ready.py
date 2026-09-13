# -*- coding: utf-8 -*-
"""M3-D: lock ready state for the SW L1 industry map (gildata via Kimi datasource)."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_INVENTORY = _ROOT / "docs" / "m3d-industry-source-inventory.md"
_MAP = _ROOT / "exports" / "m3d_industry" / "sw_l1_map.csv"
_WIND_XCHECK = _ROOT / "exports" / "m3d_industry" / "wind_crosscheck.json"
_WIND_CONFLICTS = _ROOT / "exports" / "m3d_industry" / "wind_conflicts.csv"

READY_MARKER = "M3D_STATUS=ready"

SW_L1 = {
    "农林牧渔", "基础化工", "钢铁", "有色金属", "电子", "家用电器", "食品饮料",
    "纺织服饰", "轻工制造", "医药生物", "公用事业", "交通运输", "房地产",
    "商贸零售", "社会服务", "综合", "建筑材料", "建筑装饰", "电力设备",
    "国防军工", "计算机", "传媒", "通信", "银行", "非银金融", "汽车",
    "机械设备", "煤炭", "石油石化", "环保", "美容护理",
}

_CODE_RE = re.compile(r"^(SH|SZ)\d{6}$")

MIN_ROWS = 5000
MIN_SHSZ_COVERAGE = 0.98


def _read_map():
    with _MAP.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_inventory_doc_exists_and_marks_ready():
    assert _INVENTORY.is_file(), f"missing inventory doc: {_INVENTORY}"
    text = _INVENTORY.read_text(encoding="utf-8")
    assert READY_MARKER in text
    assert "sw_l1_map.csv" in text
    assert "as-of" in text.lower() or "现行分类回看" in text


def test_industry_map_schema_and_content():
    assert _MAP.is_file(), f"missing industry map: {_MAP}"
    with _MAP.open(encoding="utf-8", newline="") as f:
        header = f.readline().strip().split(",")
    assert header == ["code_qlib", "code_gildata", "name", "sw_l1"]
    rows = _read_map()
    assert len(rows) >= MIN_ROWS, f"map shrunk: {len(rows)} rows"
    codes = [r["code_qlib"] for r in rows]
    assert len(codes) == len(set(codes)), "duplicate code_qlib in map"
    for r in rows:
        assert _CODE_RE.match(r["code_qlib"]), f"bad code: {r['code_qlib']}"
        assert r["sw_l1"] in SW_L1, f"unknown industry: {r['sw_l1']}"
        assert r["name"].strip(), f"empty name: {r['code_qlib']}"


def test_shsz_coverage_if_universe_present():
    """Coverage vs my_data universe; skipped when qlib data not on host."""
    universe = Path.home() / ".qlib" / "qlib_data" / "my_data" / "instruments" / "all.txt"
    if not universe.is_file():
        pytest.skip("my_data universe not present on this host")
    uni = {
        line.split("\t")[0].strip()
        for line in universe.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    uni_shsz = {c for c in uni if c.startswith(("SH", "SZ"))}
    mapped = {r["code_qlib"] for r in _read_map()}
    covered = uni_shsz & mapped
    ratio = len(covered) / max(len(uni_shsz), 1)
    assert ratio >= MIN_SHSZ_COVERAGE, (
        f"SH/SZ coverage {ratio:.2%} < {MIN_SHSZ_COVERAGE:.0%} "
        f"({len(covered)}/{len(uni_shsz)}); refresh exports/m3d_industry"
    )


def test_wind_crosscheck_verifies_gildata_map():
    """Wind authoritative re-check of the gildata SW L1 map must show 100% agreement."""
    assert _WIND_XCHECK.is_file(), f"missing wind cross-check report: {_WIND_XCHECK}"
    assert _WIND_CONFLICTS.is_file(), f"missing wind conflicts file: {_WIND_CONFLICTS}"

    data = json.loads(_WIND_XCHECK.read_text(encoding="utf-8"))
    assert data.get("overlap") == 5210, data.get("overlap")
    assert data.get("wind_missing") == [], data.get("wind_missing")
    assert data.get("conflicts_raw_count") == 0, data.get("conflicts_raw_count")
    assert data.get("conflicts_normalized_count") == 0, data.get("conflicts_normalized_count")
    assert data.get("agreement_rate_raw") == 1.0, data.get("agreement_rate_raw")
    assert data.get("agreement_rate_normalized") == 1.0, data.get("agreement_rate_normalized")

    lines = _WIND_CONFLICTS.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, f"unexpected conflicts rows: {len(lines) - 1}"


def test_no_fake_neutralize_module():
    """Until the implementation slice ships, no fake neutralize module.

    Optional stub may appear later; absence is OK and preferred.
    """
    scripts = _ROOT / "my_scripts"
    for name in ("industry_neutral.py", "m3d_neutralize.py"):
        path = scripts / name
        if path.is_file():
            body = path.read_text(encoding="utf-8")
            assert READY_MARKER in body or "NotImplementedError" in body
