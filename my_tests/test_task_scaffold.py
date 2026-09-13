"""task_scaffold：模板内容与 slug/分支规则单测（不真跑 git）。"""

from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from task_scaffold import KIND_BRANCH, SLUG_RE, TEMPLATE  # noqa: E402


def test_template_has_prelock_four():
    body = TEMPLATE.format(title="t", today="2026-09-13")
    for anchor in ["采纳条件", "合法终点", "禁止说法", "预期管理", "定位（钉死", "明确不做", "切片"]:
        assert anchor in body, f"模板缺 {anchor}"


def test_slug_rules():
    assert SLUG_RE.match("m3d-impl")
    assert SLUG_RE.match("plan2")
    assert not SLUG_RE.match("M3D")
    assert not SLUG_RE.match("-x")
    assert not SLUG_RE.match("a b")


def test_branch_prefix_by_kind():
    assert KIND_BRANCH["plan"] == "docs/"
    assert KIND_BRANCH["feat"] == "feat/"
    assert KIND_BRANCH["fix"] == "fix/"
