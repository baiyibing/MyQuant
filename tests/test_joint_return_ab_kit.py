"""PR #102 A/B kit self-test: slow (--no-cache-plan-hash) vs default chain must PASS ab_compare;
a tampered intents.csv must FAIL. Helpers run without PYTHONPATH, as on the 4090."""
import json
import os
import subprocess
import sys
from pathlib import Path

from my_scripts import joint_return_freeze_snapshot as freeze
from my_scripts import joint_return_merge_scores as merge
from my_scripts import joint_return_rule_intents as rules
from my_scripts.joint_return_contract import RECORDER, content_hash, raw_hash
from test_joint_return_control_only import slim_inputs
from test_joint_return_portfolio import snapshot  # noqa: F401 (pytest fixture)
from test_joint_return_rule_intents import write

REPO = Path(__file__).resolve().parents[1]
KIT = REPO / "docs/performance/ab-2026-09-25"
ENV = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}


def kit(tmp_path, *args):
    return subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, check=False,
                          cwd=tmp_path, env=ENV)

def test_ab_kit_passes_equal_chain_and_catches_tamper(snapshot, tmp_path, capsys):  # noqa: F811
    s, sessions = slim_inputs(snapshot, 50, 5)
    control = [{k: r[k] for k in ("date", "instrument", "score")} for r in s["scores"]]
    decl = {"recorder_id": RECORDER, "source_version": "synthetic-control-v1",
            "score_available_at_by_date": {r["date"]: r["score_available_at"] for r in s["scores"]}}
    write(tmp_path / "control.json", control); write(tmp_path / "control-metadata.json", decl)
    merged = tmp_path / "merged"
    assert merge.main(["--mode", "control_only", "--control", str(tmp_path / "control.json"),
        "--control-metadata", str(tmp_path / "control-metadata.json"), "--output-dir", str(merged)]) == 0
    paths = {"scores": merged / "scores.json", "initial_state": tmp_path / "initial.json"}
    write(paths["initial_state"], s["initial_state"])
    for n, p in paths.items():
        s["metadata"]["inputs"][n] = {"uri": str(p), "raw_sha256": raw_hash(p.read_bytes()),
            "content_sha256": content_hash(json.loads(p.read_bytes())), "coverage": "c", "version": "v"}
    for k in ("topk", "n_drop", "source", "rule_version"):
        s["metadata"]["strategy"].pop(k)
    write(tmp_path / "sessions.json", sessions); write(tmp_path / "metadata.json", s["metadata"])
    args = [a for n, p in paths.items() for a in (f"--{n.replace('_', '-')}", str(p))]
    py = sys.executable
    # SLOW baseline: old reference path on both ends; freeze uses rules metadata
    slow, new = tmp_path / "slow", tmp_path / "new"
    base = [*args, "--sessions", str(tmp_path / "sessions.json"), "--metadata", str(tmp_path / "metadata.json"),
            "--arms", "P-BASE", "--topk", "50", "--n-drop", "5"]
    assert rules.main([*base, "--output-dir", str(slow / "rules"), "--no-cache-plan-hash"]) == 0
    assert freeze.main([*args, "--plans", str(slow / "rules/plans.json"), "--metadata", str(slow / "rules/metadata.json"),
                        "--output", str(slow / "snapshot.json")]) == 0
    subprocess.run([py, "-m", "my_scripts.joint_return_portfolio", "--snapshot", str(slow / "snapshot.json"),
                    "--run-id", "rid", "--output-root", str(slow / "portfolio"), "--no-cache-plan-hash"], check=True, cwd=REPO)
    # NEW: default (cache on); freeze metadata = slow freeze metadata re-pointed at new plans
    assert rules.main([*base, "--output-dir", str(new / "rules")]) == 0
    assert kit(tmp_path, KIT / "patch_freeze_metadata.py", slow / "rules/metadata.json",
               new / "rules/plans.json", new / "freeze-metadata.json").returncode == 0
    assert freeze.main([*args, "--plans", str(new / "rules/plans.json"), "--metadata", str(new / "freeze-metadata.json"),
                        "--output", str(new / "snapshot.json")]) == 0
    subprocess.run([py, "-m", "my_scripts.joint_return_portfolio", "--snapshot", str(new / "snapshot.json"),
                    "--run-id", "rid", "--output-root", str(new / "portfolio")], check=True, cwd=REPO)
    capsys.readouterr()
    compare = [KIT / "ab_compare.py", slow / "rules", new / "rules", slow / "snapshot.json",
               new / "snapshot.json", slow / "portfolio/rid", new / "portfolio/rid"]
    r = kit(tmp_path, *compare)
    assert r.returncode == 0 and "RESULT: PASS" in r.stdout, r.stdout + r.stderr
    p = new / "portfolio/rid/intents.csv"
    p.write_bytes(p.read_bytes().replace(b"P-BASE", b"P-BASF", 1))
    r = kit(tmp_path, *compare)
    assert r.returncode == 1 and "FAIL intents.csv bytes" in r.stdout, r.stdout + r.stderr
