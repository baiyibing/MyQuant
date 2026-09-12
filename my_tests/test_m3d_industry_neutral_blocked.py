# -*- coding: utf-8 -*-
"""M3-D: document blocked state when no industry classification source on VM."""

from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_INVENTORY = _ROOT / "docs" / "m3d-industry-source-inventory.md"

BLOCKED_MARKER = "M3D_STATUS=blocked"


def test_inventory_doc_exists_and_marks_blocked():
    assert _INVENTORY.is_file(), f"missing inventory doc: {_INVENTORY}"
    text = _INVENTORY.read_text(encoding="utf-8")
    assert BLOCKED_MARKER in text
    # Fence-style marker line for machines
    assert any(
        line.strip() == BLOCKED_MARKER or line.strip() == f"`{BLOCKED_MARKER}`"
        or BLOCKED_MARKER in line
        for line in text.splitlines()
    )
    assert "disclosure_data" in text or "F:\\disclosure_data" in text or "F:" in text
    assert "跳过" in text or "blocked" in text.lower()


def test_no_neutralize_module_required_while_blocked():
    """While blocked, production neutralize module must not be required.

    Optional stub may appear later; absence is OK and preferred.
    """
    scripts = _ROOT / "my_scripts"
    # Must not silently ship a fake industry map
    for name in ("industry_neutral.py", "m3d_neutralize.py"):
        path = scripts / name
        if path.is_file():
            body = path.read_text(encoding="utf-8")
            assert BLOCKED_MARKER in body or "NotImplementedError" in body
