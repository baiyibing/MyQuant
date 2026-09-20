"""Slim research chain: synthetic data only, including frozen packaging (no PnL)."""
from copy import deepcopy
import csv
import json
import subprocess
import sys

import pytest

from my_scripts import joint_return_freeze_snapshot as freeze
from my_scripts import joint_return_merge_scores as merge
from my_scripts import joint_return_portfolio as portfolio
from my_scripts import joint_return_rule_intents as rules
from my_scripts.joint_return_contract import (
    CANDIDATE_RECORDER, RECORDER, ContractError, content_hash, load_snapshot, raw_hash,
)
from test_joint_return_portfolio import snapshot
from test_joint_return_rule_intents import PAIRS, inputs, split_scores, write


def slim_inputs(snapshot, topk=50, n_drop=5):
    s, sessions = inputs(snapshot, topk, n_drop)
    control = split_scores(s["scores"])["control"]
    s["scores"], _ = merge.merge_scores(control, mode="control_only")
    s.pop("pref")
    m = s["metadata"]
    m.update(scores_mode="control_only", arms=["P-BASE"])
    for key in ("candidate_recorder_id", "sidecar_sha256"):
        m.pop(key)
    m["inputs"] = {}
    return s, sessions


def seal(s):
    for name in ("scores", "initial_state", "plans"):
        s["metadata"]["inputs"][name] = {"uri": f"synthetic://{name}",
            "raw_sha256": raw_hash(b"synthetic source"), "content_sha256": content_hash(s[name]),
            "coverage": "explicit synthetic calendar", "version": "synthetic-v1"}
    return s


def generate(s, sessions):
    return rules.generate_plans(s["scores"], s["initial_state"], sessions, s["metadata"])


@pytest.mark.parametrize("topk,n_drop", PAIRS)
def test_slim_base_matches_full_base_quantities_cash_and_turnover(snapshot, topk, n_drop):
    full, sessions = inputs(snapshot, topk, n_drop)
    # Reverse the second day's ranking to exercise actual dropout and subsequent re-entry.
    for row in full["scores"]:
        if row["date"] == sessions[1]["date"]:
            row["score"] = int(row["instrument"][1:])
    expected = generate(full, sessions)
    s, _ = slim_inputs(snapshot, topk, n_drop)
    s["scores"], _ = merge.merge_scores(split_scores(full["scores"])["control"], mode="control_only")
    generated = generate(s, sessions)
    s["plans"] = generated["plans"]
    product = portfolio.build_portfolio(seal(s))
    assert set(product["final_states"]) == {"P-BASE"}
    assert product["final_states"]["P-BASE"] == expected["final_states"]["P-BASE"]
    base = [r for r in expected["reference_states"] if r["arm_id"] == "P-BASE"]
    for actual, reference in zip(product["reference_states"], base, strict=True):
        for key in ("before", "after", "target_weights", "target_turnover", "reference_fees"):
            assert actual[key] == reference[key]
    assert product["reference_states"][0]["target_turnover"] == pytest.approx(.95)
    assert product["reference_states"][1]["target_turnover"] > 0
    assert len(s["plans"][1]["sells"]) == n_drop
    assert all(r["anti_rank"] is None and r["t0_median"] is None for r in product["constraints"])
    assert product["pref_check"]["status"] == "NOT_RUN"
    assert product["scope_status"]["P-CHASE"]["status"] == "INPUT_BLOCKED"
    assert product["scope_status"]["WEAK_SIGNAL"]["status"] == "INPUT_BLOCKED"


def test_one_day_fewer_than_ten_needs_neither_pref_nor_anti(snapshot):
    s, sessions = slim_inputs(snapshot)
    day = sessions[0]["date"]
    s["metadata"].update(calendar=[day], window={"start": day, "end": day})
    s["scores"] = s["scores"][:3]
    s["scores"][1]["score"] = s["scores"][0]["score"]
    s["scores"].reverse()
    sessions = sessions[:1]
    sessions[0]["market"] = sessions[0]["market"][:3]
    s["plans"] = generate(s, sessions)["plans"]
    s["kind"] = "frozen"  # explicit synthetic source data; tests packaging, not real provenance
    out = portfolio.build_portfolio(seal(s))
    assert s["plans"][0]["buys"] == ["I000", "I001", "I002"]
    assert len(out["intents"]) == 3
    assert out["pref_check"]["numeric_scope"] == []


@pytest.mark.parametrize("field,value", [("anti_rank", .5), ("anti_available_at", "2026-09-07T15:00:00+08:00"),
    ("label", 0), ("candidate_present", True), ("candidate_present", False), ("candidate_score", 1),
    ("recorder_id", CANDIDATE_RECORDER), ("score", float("nan")), ("scores_mode", "full")])
def test_slim_never_fills_or_accepts_fake_deferred_fields(snapshot, field, value):
    s, sessions = slim_inputs(snapshot)
    s["scores"][0][field] = value
    with pytest.raises(ContractError, match="INPUT_BLOCKED"):
        generate(s, sessions)


def test_explicit_nulls_are_unknown_not_zero_and_full_mode_remains_strict(snapshot):
    s, sessions = slim_inputs(snapshot)
    for row in s["scores"]:
        row.update(anti_rank=None, anti_available_at=None, candidate_present=None, label=None)
    assert generate(s, sessions)["plans"]
    with pytest.raises(ContractError, match="scores_mode"):
        portfolio.score_days(s["scores"])
    for row in s["scores"]:
        row.pop("scores_mode")
    with pytest.raises(ContractError, match="finite number"):
        portfolio.score_days(s["scores"])


@pytest.mark.parametrize("arm", ["P-CHASE", "WEAK_SIGNAL", "P-REF-anti"])
def test_requested_anti_and_weak_signal_arms_are_blocked(snapshot, arm):
    s, sessions = slim_inputs(snapshot)
    s["metadata"]["arms"] = ["P-BASE", arm]
    with pytest.raises(ContractError, match="requested arms blocked"):
        generate(s, sessions)


def test_direct_anti_entrypoints_cannot_bypass_mode(snapshot):
    s, sessions = slim_inputs(snapshot)
    grouped = portfolio.score_days(s["scores"], mode="control_only")
    with pytest.raises(ContractError, match="anti required"):
        portfolio.select_pref(next(iter(grouped.values())))
    with pytest.raises(ContractError, match="P-REF-anti INPUT_BLOCKED"):
        portfolio.check_pref(grouped, {}, synthetic=True)
    with pytest.raises(ContractError, match="requested arm INPUT_BLOCKED"):
        rules.make_rule_plan("P-CHASE", s["initial_state"], {}, next(iter(grouped.values())), sessions[0], s["metadata"])


@pytest.mark.parametrize("change,match", [
    (lambda s, d: d[0]["market"][0].pop("reference_price"), "missing"),
    (lambda s, d: d[0]["market"][0].pop("buy_eligible"), "missing"),
    (lambda s, d: d[0]["market"][0].pop("sell_eligible"), "missing"),
    (lambda s, d: d.pop(), "missing/extra rule sessions"),
    (lambda s, d: s["initial_state"].pop("cash"), "missing"),
    (lambda s, d: s["scores"][0].update(score_available_at="2026-09-07T16:00:00+08:00"), "not available"),
    (lambda s, d: d[0]["market"][0].update(eligibility_available_at="2026-09-07T16:00:00+08:00"), "future eligibility"),
    (lambda s, d: s["metadata"].update(risk_budget=.5), "risk budget"),
    (lambda s, d: s["metadata"]["fees"].update(minimum=100_000), "cash including fees"),
    (lambda s, d: d[0].update(corporate_actions=[{"factor": 2}]), "SEMANTICS_BLOCKED"),
])
def test_slim_keeps_real_quantity_qualification_and_causal_gates(snapshot, change, match):
    s, sessions = slim_inputs(snapshot)
    change(s, sessions)
    with pytest.raises(ContractError, match=match):
        generate(s, sessions)


def test_three_column_control_requires_explicit_source_and_availability(snapshot):
    s, _ = slim_inputs(snapshot)
    control = [{k: r[k] for k in ("date", "instrument", "score")} for r in s["scores"]]
    declaration = {"recorder_id": RECORDER, "source_version": "synthetic-control-v1",
        "score_available_at_by_date": {r["date"]: r["score_available_at"] for r in s["scores"]}}
    with pytest.raises(ContractError, match="missing"):
        merge.merge_scores(control, mode="control_only")
    rows, audit = merge.merge_scores(control, mode="control_only", control_metadata=declaration)
    assert rows == s["scores"] and audit["control_rows"] == len(control)
    with pytest.raises(ContractError, match="universe.*nonempty"):
        merge.merge_scores(split_scores(inputs(snapshot)[0]["scores"])["control"])
    declaration["score_available_at_by_date"].pop(next(iter(declaration["score_available_at_by_date"])))
    with pytest.raises(ContractError, match="exactly the control dates"):
        merge.merge_scores(control, mode="control_only", control_metadata=declaration)


def test_slim_preserves_control_denominator_and_records_unused_exports(snapshot):
    full, _ = inputs(snapshot)
    parts = split_scores(full["scores"])
    parts["universe"] = parts["universe"][:1]
    parts["anti"] = []
    parts["labels"] = []
    rows, audit = merge.merge_scores(**parts, mode="control_only")
    assert len(rows) == len(parts["control"])
    assert audit["deferred_inputs_not_consumed"] == ["universe", "anti", "labels"]
    assert all(not {"anti_rank", "candidate_present", "label"} & r.keys() for r in rows)
    parts["control"].append(parts["control"][0])
    with pytest.raises(ContractError, match="duplicate key"):
        merge.merge_scores(**parts, mode="control_only")


@pytest.mark.parametrize("change,match", [
    (lambda d: d.update(recorder_id=CANDIDATE_RECORDER), "recorder_id drift"),
    (lambda d: d.update(source_version="different"), "source_version drift"),
    (lambda d: d["score_available_at_by_date"].update({"2026-09-07": "2026-09-07T15:01:00"}), "Asia/Shanghai"),
])
def test_control_declarations_cannot_override_rows_or_guess_timezone(snapshot, change, match):
    full, _ = inputs(snapshot)
    control = split_scores(full["scores"])["control"]
    original = deepcopy(control)
    declaration = {"recorder_id": RECORDER, "source_version": "synthetic-control-v1",
        "score_available_at_by_date": {r["date"]: r["score_available_at"] for r in control}}
    change(declaration)
    with pytest.raises(ContractError, match=match):
        merge.merge_scores(control, mode="control_only", control_metadata=declaration)
    assert control == original


@pytest.mark.parametrize("topk,n_drop", PAIRS)
def test_three_column_merge_rules_freeze_portfolio_cli(snapshot, tmp_path, capsys, topk, n_drop):
    s, sessions = slim_inputs(snapshot, topk, n_drop)
    control = [{k: r[k] for k in ("date", "instrument", "score")} for r in s["scores"]]
    declaration = {"recorder_id": RECORDER, "source_version": "synthetic-control-v1",
        "score_available_at_by_date": {r["date"]: r["score_available_at"] for r in s["scores"]}}
    write(tmp_path / "control.json", control)
    write(tmp_path / "control-metadata.json", declaration)
    merged = tmp_path / "merged"
    assert merge.main(["--mode", "control_only", "--control", str(tmp_path / "control.json"),
        "--control-metadata", str(tmp_path / "control-metadata.json"), "--output-dir", str(merged)]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert set(receipt["inputs"]) == {"control", "control_metadata"}
    assert receipt["scores_mode"] == "control_only"
    paths = {"scores": merged / "scores.json", "initial_state": tmp_path / "initial.json"}
    write(paths["initial_state"], s["initial_state"])
    for name, path in paths.items():
        s["metadata"]["inputs"][name] = {"uri": str(path), "raw_sha256": raw_hash(path.read_bytes()),
            "content_sha256": content_hash(json.loads(path.read_bytes())), "coverage": "synthetic five days", "version": "synthetic-v1"}
    for key in ("topk", "n_drop", "source", "rule_version"):
        s["metadata"]["strategy"].pop(key)
    write(tmp_path / "sessions.json", sessions)
    write(tmp_path / "metadata.json", s["metadata"])
    args = [arg for name, path in paths.items() for arg in (f"--{name.replace('_', '-')}", str(path))]
    rule_dir = tmp_path / "rules"
    rule_args = [*args, "--sessions", str(tmp_path / "sessions.json"), "--metadata", str(tmp_path / "metadata.json"),
                 "--output-dir", str(rule_dir)]
    if topk != 50:
        rule_args += ["--topk", str(topk), "--n-drop", str(n_drop)]
    assert rules.main(rule_args) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert (receipt["topk"], receipt["n_drop"]) == (topk, n_drop)
    frozen_path = tmp_path / "snapshot.json"
    freeze_args = [*args, "--plans", str(rule_dir / "plans.json"), "--metadata", str(rule_dir / "metadata.json"),
                   "--output", str(frozen_path)]
    assert freeze.main(freeze_args) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert set(receipt["inputs"]) == {"scores", "initial_state", "plans"}
    assert receipt["scope_status"]["P-BASE"]["status"] == "FROZEN_SNAPSHOT_ASSEMBLED"
    frozen, _ = load_snapshot(frozen_path)
    assert frozen["kind"] == "frozen" and "pref" not in frozen
    assert "candidate_recorder_id" not in frozen["metadata"]
    command = [sys.executable, "-m", "my_scripts.joint_return_portfolio", "--snapshot", str(frozen_path),
               "--run-id", "slim", "--output-root", str(tmp_path / "portfolio")]
    subprocess.run(command, check=True, capture_output=True, text=True)
    out_dir = tmp_path / "portfolio" / "slim"
    manifest = json.loads((out_dir / "manifest.json").read_bytes())
    assert manifest["portfolio_status"] == "PORTFOLIO_CONSTRAINTS_PASS"
    assert manifest["execution_status"] == "NOT_RUN" and manifest["return_status"] == "待实测"
    assert manifest["input_status"] == "INPUT_BLOCKED"  # local hashes do not prove upstream PIT
    assert manifest["pairing"]["arms"] == ["P-BASE"]
    assert set(manifest["arm_intent_hashes"]) == {"P-BASE"}
    for name in ("P-CHASE", "WEAK_SIGNAL", "Mode B"):
        assert manifest["scope_status"][name]["status"] == "INPUT_BLOCKED"
        assert manifest["scope_status"][name]["execution_status"] == "NOT_RUN"
    assert manifest["scope_status"]["P-REF-anti"]["status"] == "NOT_RUN"
    assert json.loads((out_dir / "pref_check.json").read_bytes())["status"] == "NOT_RUN"
    with (out_dir / "constraints.csv").open() as stream:
        assert all(r["anti_rank"] == r["t0_median"] == "null" for r in csv.DictReader(stream))
    assert subprocess.run(command, capture_output=True).returncode == 2
    assert rules.main([*rule_args, "--arms", "P-BASE", "P-CHASE"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "INPUT_BLOCKED"
    # Neither mode promotion nor an extra chase plan gets past the frozen boundary.
    metadata = json.loads((rule_dir / "metadata.json").read_bytes())
    metadata["scores_mode"] = "full"
    write(rule_dir / "metadata.json", metadata)
    frozen_path.unlink()
    assert freeze.main(freeze_args) == 2
    assert "pref required" in json.loads(capsys.readouterr().out)["detail"]
    assert not frozen_path.exists()


@pytest.mark.parametrize("change,match", [
    (lambda s: s["plans"][0].update(arm_id="P-CHASE"), "requested plan arm"),
    (lambda s: s["plans"].pop(), "missing/extra arm-days"),
    (lambda s: s["plans"][1].update(pre_state_hash="0" * 64), "state discontinuity"),
    (lambda s: s["plans"][0].update(source="PortAna_positions"), "cannot reconstruct"),
    (lambda s: s["metadata"].update(candidate_recorder_id=CANDIDATE_RECORDER), "deferred candidate"),
    (lambda s: s.update(pref={}), "must omit pref"),
])
def test_slim_snapshot_rejects_extra_dependencies_and_plan_drift(snapshot, change, match):
    s, sessions = slim_inputs(snapshot)
    s["plans"] = generate(s, sessions)["plans"]
    change(s)
    with pytest.raises(ContractError, match=match):
        portfolio.build_portfolio(seal(s))
