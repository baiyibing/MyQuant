# -*- coding: utf-8 -*-
"""任务 2：manifest git 溯源取启动时 HEAD（不随收尾 rev-parse 漂移）。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from run_manifest import (  # noqa: E402
    capture_git_provenance,
    load_manifest,
    write_train_manifest,
)


def _fake_check_output_factory(state: dict[str, Any]):
    def _fake(cmd, cwd=None, stderr=None, text=True):  # noqa: ANN001
        if not isinstance(cmd, (list, tuple)):
            raise TypeError(cmd)
        # Track every rev-parse HEAD so we can flip after startup capture.
        if list(cmd[:3]) == ["git", "rev-parse", "HEAD"]:
            state["rev_parse_calls"] = state.get("rev_parse_calls", 0) + 1
            return state["head"] + "\n"
        if list(cmd[:3]) == ["git", "rev-parse", "--abbrev-ref"]:
            return state["branch"] + "\n"
        if list(cmd[:3]) == ["git", "status", "--porcelain"]:
            return state.get("porcelain", " M dirty.txt\n")
        raise AssertionError(f"unexpected git cmd: {cmd}")

    return _fake


def test_manifest_keeps_startup_git_provenance(tmp_path: Path):
    """mock 两次不同 rev-parse：启动真 / 收尾假 → manifest 保留启动值 + branch + dirty。"""
    state = {
        "head": "startupaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "branch": "feat/followups-env-manifest",
        "porcelain": " M my_scripts/host_env.py\n",
        "rev_parse_calls": 0,
    }
    with patch("run_manifest.subprocess.check_output", side_effect=_fake_check_output_factory(state)):
        prov = capture_git_provenance(repo_root=_ROOT)
        assert prov["git_commit"] == "startupaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        assert prov["git_branch"] == "feat/followups-env-manifest"
        assert prov["git_dirty"] is True
        assert state["rev_parse_calls"] == 1

        # 模拟训练中途切分支：后续任何 git_commit() / 再 capture 都会读到假 HEAD
        state["head"] = "laterbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        state["branch"] = "some-other-branch"
        state["porcelain"] = ""

        written = write_train_manifest(
            manifests_dir=tmp_path / "manifests",
            config={"topk": 5, "n_drop": 2, "note": "startup-git-test"},
            timings={"total_seconds": 0.01, "nodes": []},
            git_commit_sha=prov["git_commit"],
            git_branch=prov["git_branch"],
            git_dirty=prov["git_dirty"],
            created_utc="2026-09-13T01:00:00Z",
            repo_root=_ROOT,
        )

    man = load_manifest(written[0])
    assert man["git_commit"] == "startupaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert man["git_branch"] == "feat/followups-env-manifest"
    assert man["git_dirty"] is True
    # 证明若未传入启动值、收尾再读会得到 later…（对照）
    with patch("run_manifest.subprocess.check_output", side_effect=_fake_check_output_factory(state)):
        drifted = capture_git_provenance(repo_root=_ROOT)
    assert drifted["git_commit"] == "laterbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    assert drifted["git_commit"] != man["git_commit"]
