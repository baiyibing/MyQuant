"""MQ caller contracts and offline dry runs against the shared ops runtime."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import ops_workflow as workflow

ROOT = Path(__file__).resolve().parents[1]
OPS = Path(os.environ.get("MYQUANT_OPS_ROOT") or ROOT.parent / "grok-bot-ops").expanduser().resolve()


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    root = tmp_path / "research checkout 中文"
    (root / "my_scripts").mkdir(parents=True)
    (root / "configs/ops").mkdir(parents=True)
    shutil.copy2(ROOT / "my_scripts/ops_workflow.py", root / "my_scripts/ops_workflow.py")
    for name in ("review.json", "adversarial.json"):
        shutil.copy2(ROOT / "configs/ops" / name, root / "configs/ops" / name)
    monkeypatch.setattr(workflow, "REPO_ROOT", root)
    return root


@pytest.fixture
def fake_ops(tmp_path):
    root = tmp_path / "ops source 中文"
    (root / "scripts").mkdir(parents=True)
    entries = [entry for entry, _profile in workflow.ENTRIES.values()]
    (root / "scripts/runtime-api.json").write_text(
        json.dumps({"schema_version": 1, "entries": entries}), encoding="utf-8",
    )
    for entry in entries:
        path = root / entry
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "import json, os, sys\n"
            "print(json.dumps({'cwd':os.getcwd(), 'args':sys.argv[1:], 'utf8':sys.flags.utf8_mode}))\n"
            "raise SystemExit(int(os.environ.get('TEST_CHILD_EXIT', '0')))\n",
            encoding="utf-8",
        )
    return root


@pytest.mark.parametrize("command", workflow.ENTRIES)
def test_child_process_is_bound_to_mq_with_its_profile(checkout, fake_ops, monkeypatch, capfd, tmp_path, command):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MYQUANT_OPS_ROOT", str(fake_ops))
    monkeypatch.setenv("PYTHONUTF8", "0")
    monkeypatch.setenv("TEST_CHILD_EXIT", "7")
    assert workflow.main([command, "--dry-run"]) == 7
    child = json.loads(capfd.readouterr().out)
    assert Path(child["cwd"]) == checkout
    assert child["args"][:2] == ["--repo-root", str(checkout)]
    profile = workflow.ENTRIES[command][1]
    expected = ["--repo-root", str(checkout)]
    if profile:
        expected += ["--profile-file", str(checkout / profile)]
    assert child["args"] == expected + ["--dry-run"]
    assert child["utf8"] == 1
    assert os.environ["PYTHONUTF8"] == "0"


def test_sibling_default_and_explicit_override(checkout, fake_ops, monkeypatch, capfd):
    monkeypatch.delenv("MYQUANT_OPS_ROOT", raising=False)
    sibling = checkout.parent / "grok-bot-ops"
    shutil.copytree(fake_ops, sibling)
    assert workflow.main(["publish", "--dry-run"]) == 0
    assert "--repo-root" in json.loads(capfd.readouterr().out)["args"]
    monkeypatch.setenv("MYQUANT_OPS_ROOT", str(checkout / "missing"))
    assert workflow.main(["publish", "--ops-root", str(fake_ops), "--dry-run"]) == 0


@pytest.mark.parametrize("override", [
    ["--repo-root", "elsewhere"], ["--repo-root=elsewhere"],
    ["--profile-file", "elsewhere.json"], ["--profile-file=elsewhere.json"],
])
def test_caller_context_cannot_be_overridden(checkout, fake_ops, monkeypatch, override):
    monkeypatch.setenv("MYQUANT_OPS_ROOT", str(fake_ops))
    monkeypatch.setattr(workflow.subprocess, "run", lambda *a, **k: pytest.fail("child launched"))
    with pytest.raises(SystemExit) as error:
        workflow.main(["review", *override])
    assert error.value.code == 2


@pytest.mark.parametrize("manifest", [
    None, "invalid JSON", [], {"schema_version": 2, "entries": []},
    {"schema_version": True, "entries": []}, {"schema_version": 1, "entries": []},
    {"schema_version": 1, "entries": "scripts/run/run_multi_ai_review.py"},
])
def test_missing_or_incompatible_ops_stops_before_child(checkout, fake_ops, monkeypatch, manifest):
    monkeypatch.setenv("MYQUANT_OPS_ROOT", str(fake_ops))
    path = fake_ops / "scripts/runtime-api.json"
    if manifest is None:
        path.unlink()
    else:
        path.write_text(manifest if isinstance(manifest, str) else json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(workflow.subprocess, "run", lambda *a, **k: pytest.fail("child launched"))
    with pytest.raises(SystemExit) as error:
        workflow.main(["review"])
    assert error.value.code == 2


@pytest.mark.parametrize("missing", ["entry", "profile"])
def test_missing_selected_entry_or_profile_does_not_fall_back(checkout, fake_ops, monkeypatch, missing):
    monkeypatch.setenv("MYQUANT_OPS_ROOT", str(fake_ops))
    entry, profile = workflow.ENTRIES["review"]
    ((fake_ops / entry) if missing == "entry" else (checkout / profile)).unlink()
    monkeypatch.setattr(workflow.subprocess, "run", lambda *a, **k: pytest.fail("child launched"))
    with pytest.raises(SystemExit) as error:
        workflow.main(["review"])
    assert error.value.code == 2


def test_relative_ops_setting_is_rejected(checkout, monkeypatch):
    monkeypatch.setenv("MYQUANT_OPS_ROOT", "relative/source")
    with pytest.raises(SystemExit) as error:
        workflow.main(["publish"])
    assert error.value.code == 2


def test_root_help_does_not_require_ops(checkout, monkeypatch, capsys):
    monkeypatch.setenv("MYQUANT_OPS_ROOT", str(checkout / "missing"))
    assert workflow.main(["--help"]) == 0
    assert "review" in capsys.readouterr().out


@pytest.fixture
def real_checkout(checkout):
    git_executable = shutil.which("git")
    assert git_executable
    def git(*args):
        subprocess.run([git_executable, "-C", str(checkout), *args], check=True, capture_output=True)
    git("init", "-b", "master")
    (checkout / "plan.md").write_text("# synthetic research plan\n", encoding="utf-8")
    git("add", ".")
    git("-c", "user.name=Offline test", "-c", "user.email=offline@example.invalid", "commit", "-m", "baseline")
    git("switch", "-c", "feature/consumer-test")
    (checkout / "candidate.txt").write_text("candidate\n", encoding="utf-8")
    git("add", "candidate.txt")
    git("-c", "user.name=Offline test", "-c", "user.email=offline@example.invalid", "commit", "-m", "candidate")
    git("remote", "add", "github", "https://github.com/example/quant-research.git")
    return checkout, git_executable


def invoke_shared(real_checkout, tmp_path, *args, **extra_env):
    root, git_executable = real_checkout
    env = {**os.environ, "MYQUANT_OPS_ROOT": str(OPS), "PYTHONUTF8": "1",
           "PATH": str(Path(git_executable).parent), "GH_TOKEN": "", "GITHUB_TOKEN": "", **extra_env}
    return subprocess.run(
        [sys.executable, str(root / "my_scripts/ops_workflow.py"), *args],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=45,
    )


def test_shared_review_dry_run_renders_mq_policy(real_checkout, tmp_path):
    root, _git = real_checkout
    result = invoke_shared(real_checkout, tmp_path, "review", "--plan", "plan.md",
                           "--out-dir", "review-output", "--agents", "codex", "--host", "claude", "--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    prompt = (root / "review-output/_prompt.md").read_text(encoding="utf-8")
    for requirement in ("PortAnaRecord", "Exchange", "replay", "采纳条件", "合法终点", "禁止说法", "预期管理"):
        assert requirement in prompt
    assert "plan.md" in prompt
    assert not (root / "review-output/codex.md").exists()


def test_shared_publisher_dry_run_is_local_and_uses_target_branch(real_checkout, tmp_path):
    result = invoke_shared(real_checkout, tmp_path, "publish", "--dry-run", "--title", "offline review")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "example/quant-research" in result.stdout
    assert "feature/consumer-test" in result.stdout
    assert "commits=1" in result.stdout
    assert "dry-run PR" in result.stdout


@pytest.mark.parametrize("branch", ["master", "main"])
def test_shared_publisher_keeps_protected_branch_refusal(real_checkout, tmp_path, branch):
    result = invoke_shared(real_checkout, tmp_path, "publish", "--branch", branch, "--dry-run")
    assert result.returncode != 0
    assert "refusing to publish protected branch" in result.stderr


def test_shared_adversarial_nested_guard_is_preserved(real_checkout, tmp_path):
    root, _git = real_checkout
    result = invoke_shared(real_checkout, tmp_path, "adversarial", "--plan", "plan.md",
                           "--out-dir", "lanes-output", "--dry-run", CODEX_THREAD_ID="synthetic-test")
    assert result.returncode == 3, result.stdout + result.stderr
    assert "refuse nested launch" in result.stderr
    assert not (root / "lanes-output").exists()


def test_shared_parser_rejects_context_abbreviation(real_checkout, tmp_path):
    result = invoke_shared(real_checkout, tmp_path, "review", "--plan", "plan.md",
                           "--out-dir", "invalid-output", "--repo-r", str(tmp_path), "--dry-run")
    assert result.returncode == 2
    assert not (real_checkout[0] / "invalid-output").exists()


def test_adversarial_profile_is_formattable_and_has_research_lanes():
    profile = json.loads((ROOT / "configs/ops/adversarial.json").read_text(encoding="utf-8"))
    ids = [lane[0] for lane in profile["lanes"]]
    assert len(set(ids)) == len(ids) == 3
    for lane, _name, stance in profile["lanes"]:
        prompt = profile["prompt_template"].format(plan_rel="plan.md", lane_id=lane, stance=stance)
        assert "Qlib 全部组件" in prompt and "Exchange" in prompt
