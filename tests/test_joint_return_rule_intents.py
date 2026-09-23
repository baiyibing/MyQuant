"""Backtest-rule adaptation: deterministic data-free vectors, never PortAna/live."""
from copy import deepcopy
import json
import subprocess
import sys

import pytest

from my_scripts import joint_return_freeze_snapshot as freeze
from my_scripts import joint_return_merge_scores as merge
from my_scripts import joint_return_rule_intents as rules
from my_scripts.joint_return_contract import (
    ARMS, CANDIDATE_RECORDER, RECORDER, SIDECAR_SHA256, ContractError,
    canonical_bytes, content_hash, load_snapshot, raw_hash, next_session_clocks,
)
from my_scripts.joint_return_portfolio import build_portfolio, score_days
from test_joint_return_portfolio import seal, snapshot


PAIRS = [(50, 5), (20, 3), (10, 3)]


def inputs(snapshot, topk=50, n_drop=5):
    s = deepcopy(snapshot)
    days = s["pref"]["calendar"]
    s["metadata"].update(calendar=days, window={"start": days[0], "end": days[-1]})
    s["metadata"]["execution_calendar"] = [*days, "2026-09-14"]
    s["metadata"]["strategy"].update(topk=topk, n_drop=n_drop)
    s["initial_state"].update(cash=1_000_000, positions={})
    s["scores"] = [{"date": day, "instrument": f"I{i:03}", "score": 100 - i,
                    "score_available_at": f"{day}T15:01:00+08:00", "source_version": "synthetic-control-v1",
                    "recorder_id": RECORDER, "anti_rank": 0 if i < 3 else 1,
                    "anti_available_at": f"{day}T15:00:00+08:00", "candidate_present": True, "label": 0}
                   for day in days for i in range(80)]
    expected = s["pref"]["expected"]["windows"]["hand"]
    expected.update(n_rows_mean=80, top10_t0=0, top10_t1=0, d_top10=0, d_top10_share_pos=0,
                    d_top10_share_neg=0, d_top10_share_zero=1, jaccard_mean=7 / 13,
                    turnover_mean=0.3, overlap_mean=7, n_t0_below_median_mean=3,
                    t0_feat=0.7, t1_feat=1, univ_feat=77 / 80, n_days_rankic=0, rankic_ctrl=None,
                    added_feat=1, dropped_feat=0, added_label=0, dropped_label=0, swap_label_gap=0,
                    quarters={"2026Q3": 0},
                    months=[{"month": "2026-09", "n_days": 5, "d_top10": 0, "d_top10_sum": 0,
                             "d_top10_share_neg": 0, "turnover": 0.3, "n_relax_mean": 0, "share_relaxed": 0}],
                    t0_vs_frozen_ctrl={"top10_t0": 0, "frozen_top10_ctrl": 0, "abs_diff": 0})
    expected["bootstrap"].update(point=0, lo=0, hi=0)
    sessions = [{"date": day, **next_session_clocks(
                    decision_at=f"{day}T15:02:00+08:00", mark_at=f"{day}T15:00:00+08:00",
                    metadata=s["metadata"]),
                 "price_domain": "none", "source_version": "synthetic-market-v1",
                 "eligibility_version": "synthetic-v1", "corporate_actions": [],
                 "market": [{"instrument": f"I{i:03}", "execution_symbol": f"I{i:03}.SYN", "reference_price": 10,
                             "buy_eligible": True, "buy_reason": "explicit test eligibility",
                             "sell_eligible": True, "sell_reason": "explicit test eligibility",
                             "eligibility_available_at": f"{day}T15:00:00+08:00"} for i in range(80)]}
                for day in days]
    return s, sessions


def generate(s, sessions):
    return rules.generate_plans(s["scores"], s["initial_state"], sessions, s["metadata"])


def split_scores(scores):
    return {
        "control": [{k: r[k] for k in ("date", "instrument", "score", "score_available_at", "source_version", "recorder_id")}
                    for r in scores],
        "universe": [{k: r[k] for k in ("date", "instrument", "candidate_present")} | {"recorder_id": CANDIDATE_RECORDER}
                     for r in scores],
        "anti": [{k: r[k] for k in ("date", "instrument", "anti_rank", "anti_available_at", "source_version")}
                 | {"source_sha256": SIDECAR_SHA256} for r in scores],
        "labels": [{k: r[k] for k in ("date", "instrument", "label", "source_version")} for r in scores],
    }


@pytest.mark.parametrize("topk,n_drop", PAIRS)
def test_three_sizes_build_churn_and_independent_state_recursion(snapshot, topk, n_drop):
    s, sessions = inputs(snapshot, topk, n_drop)
    original = deepcopy((s, sessions))
    out = generate(s, sessions)
    assert (s, sessions) == original
    base, chase = out["reference_states"][:2]
    assert set(base["after"]["positions"]) == {f"I{i:03}" for i in range(topk)}
    assert set(chase["after"]["positions"]) == {f"I{i:03}" for i in range(3, topk + 3)}
    quantity = int((1_000_000 * 0.95 / topk) // 1000) * 100
    assert all(p["quantity"] == quantity for p in base["after"]["positions"].values())
    assert base["after"]["cash"] == 1_000_000 - topk * quantity * 10
    assert out["plans"][2]["pre_state_hash"] == base["after_hash"]
    assert out["plans"][3]["pre_state_hash"] == chase["after_hash"]
    assert base["after_hash"] != chase["after_hash"]
    assert out["plans"][2]["sells"] == []  # no forced n_drop when all old scores dominate
    assert len(out["plans"][3]["sells"]) == 3
    for record in out["reference_states"]:
        assert len(record["after"]["positions"]) <= topk
        assert record["after"]["cash"] >= 0
        assert len(record["source_plan"]["sells"]) <= n_drop
    s["plans"] = out["plans"]
    product = build_portfolio(seal(s))
    assert product["final_states"] == out["final_states"]
    assert product["pref_check"]["daily"][0]["t0"] == [f"I{i:03}" for i in range(10)]
    assert product["pref_check"]["status"] == "SYNTHETIC_PASS"
    assert all(row["original_target_quantity"] % 100 == 0 for row in product["intents"])
    # Input order is not a source of selection randomness.
    s["scores"].reverse()
    assert generate(s, list(reversed(sessions)))["plans"] == out["plans"]


@pytest.mark.parametrize("topk,n_drop", PAIRS)
def test_topk_core_full_dropout_and_vacant_slots(snapshot, topk, n_drop):
    s, _ = inputs(snapshot, topk, n_drop)
    ranked = next(iter(score_days(s["scores"]).values()))
    held = {f"I{i:03}" for i in range(80 - topk, 80)}
    sells, today = rules.topk_dropout(ranked, held, topk=topk, n_drop=n_drop)
    assert sells == [f"I{i:03}" for i in range(80 - n_drop, 80)]
    assert today == [f"I{i:03}" for i in range(n_drop)]
    held.remove(f"I{80 - topk:03}")
    _, today = rules.topk_dropout(ranked, held, topk=topk, n_drop=n_drop)
    assert len(today) == n_drop + 1
    assert rules.topk_dropout(ranked, held, topk=topk, n_drop=0)[0] == []


@pytest.mark.parametrize("topk,n_drop", PAIRS)
def test_underfilled_nonempty_state_can_fill_more_than_n_drop(snapshot, topk, n_drop):
    s, sessions = inputs(snapshot, topk, n_drop)
    s["initial_state"]["positions"] = {"I079": {"quantity": 100, "lot_id": "old-lot",
                                                "instance_id": "old-instance", "holding_days": 1}}
    out = generate(s, sessions)
    assert len(out["plans"][0]["buys"]) == topk > n_drop
    assert [o["instrument"] for o in out["plans"][0]["sells"]] == ["I079"]
    assert len(out["reference_states"][0]["after"]["positions"]) == topk


def test_ties_and_per_instrument_quantity_do_not_use_future_labels(snapshot):
    s, sessions = inputs(snapshot, 20, 3)
    for row in s["scores"]:
        row["score"] = 1
        row["label"] = 999 if row["instrument"] == "I079" else -999
    s["scores"].reverse()
    for session in sessions:
        session["market"][0]["reference_price"] = 5
        session["market"][1]["reference_price"] = 20
    out = generate(s, sessions)
    plan = out["plans"][0]
    assert plan["buys"] == [f"I{i:03}" for i in range(20)]
    quantities = {o["instrument"]: o["original_target_quantity"] for o in plan["buy_candidates"]}
    assert quantities["I000"] == 9500
    assert quantities["I001"] == 2300
    assert quantities["I002"] == 4700


def test_hold_threshold_sell_rejection_and_buy_qualification(snapshot):
    s, sessions = inputs(snapshot, 10, 3)
    s["metadata"]["strategy"]["rule_parameters"]["hold_thresh"] = 2
    s["initial_state"]["positions"] = {
        f"I{i:03}": {"quantity": 100, "lot_id": f"lot-{i}", "instance_id": f"instance-{i}", "holding_days": 0}
        for i in range(70, 80)}
    sessions[2]["market"][79].update(sell_eligible=False, sell_reason="SUSPENDED")
    sessions[2]["market"][0].update(buy_eligible=False, buy_reason="ST_GATE")
    out = generate(s, sessions)
    for plan in out["plans"][:4]:
        assert len(plan["sells"]) == 3 and all(not o["approved"] for o in plan["sells"])
        assert plan["buys"] == []
    third_base = out["plans"][4]
    assert [o["instrument"] for o in third_base["sells"] if o["approved"]] == ["I077", "I078"]
    assert third_base["buys"] == ["I001"]
    assert "I079" in out["reference_states"][4]["after"]["positions"]
    assert any(o["eligibility_reason"] == "ST_GATE" and not o["eligible"] for o in third_base["buy_candidates"])


def test_whole_lot_zero_and_rejected_buys_are_audited(snapshot):
    s, sessions = inputs(snapshot, 10, 3)
    s["initial_state"]["cash"] = 1
    out = generate(s, sessions)
    assert all(not p["buys"] and len(p["rule_trace"]["rejected_buys"]) == 80 for p in out["plans"])
    s["plans"] = out["plans"]
    product = build_portfolio(seal(s))
    assert product["intents"] == []
    assert sum(r["status"] == "RULE_BUY_BLOCKED" for r in product["constraints"]) == 800


@pytest.mark.parametrize("change,match", [
    (lambda s, d: d[0]["market"][0].pop("reference_price"), "missing"),
    (lambda s, d: d[0]["market"][0].pop("buy_eligible"), "missing"),
    (lambda s, d: d[0]["market"][0].pop("sell_eligible"), "missing"),
    (lambda s, d: d[0]["market"].pop(), "market rows missing"),
    (lambda s, d: d[0].pop("corporate_actions"), "missing"),
    (lambda s, d: d.pop(), "missing/extra rule sessions"),
    (lambda s, d: d.append(d[0]), "duplicate rule session"),
    (lambda s, d: d[0]["market"][0].update(eligibility_available_at="2026-09-07T16:00:00+08:00"), "future eligibility"),
    (lambda s, d: s["scores"][0].update(score_available_at="2026-09-07T16:00:00+08:00"), "not available"),
    (lambda s, d: s["scores"][0].update(anti_available_at="2026-09-07T16:00:00+08:00"), "not available"),
    (lambda s, d: s["scores"][0].update(recorder_id=CANDIDATE_RECORDER), "candidate score source"),
    (lambda s, d: d[0].update(corporate_actions=[{"factor": 2}]), "SEMANTICS_BLOCKED"),
    (lambda s, d: d[1]["market"][0].update(execution_symbol="CHANGED"), "mapping drift"),
    (lambda s, d: d[0]["market"][0].update(execution_symbol="I001.SYN"), "mapping drift"),
    (lambda s, d: s["metadata"]["strategy"].update(source="frozen_original_intents"), "backtest rule intents required"),
    (lambda s, d: s["metadata"]["strategy"].update(source="PortAna_positions"), "backtest rule intents required"),
    (lambda s, d: s["metadata"]["strategy"]["rule_parameters"].update(only_tradable=True), "unsupported TopkDropout"),
    (lambda s, d: s["metadata"]["strategy"]["rule_parameters"].pop("hold_thresh"), "missing"),
    (lambda s, d: s["metadata"]["fees"].update(minimum=100_000), "cash including fees"),
])
def test_rule_missing_inputs_and_semantic_drift_fail_closed(snapshot, change, match):
    s, sessions = inputs(snapshot)
    change(s, sessions)
    with pytest.raises(ContractError, match=match):
        generate(s, sessions)


@pytest.mark.parametrize("topk,n_drop", [(True, 1), (0, 0), (-1, 0), (10.0, 3), (10, -1), (10, 11), (10, False)])
def test_invalid_parameters(snapshot, topk, n_drop):
    s, sessions = inputs(snapshot, topk, n_drop)
    with pytest.raises(ContractError, match="INPUT_BLOCKED"):
        generate(s, sessions)


def test_initial_age_and_held_score_are_required(snapshot):
    s, sessions = inputs(snapshot)
    s["initial_state"]["positions"] = {"I079": {"quantity": 100, "lot_id": "lot", "instance_id": "instance"}}
    with pytest.raises(ContractError, match="holding_days"):
        generate(s, sessions)
    s["initial_state"]["positions"]["I079"]["holding_days"] = 1
    s["scores"] = [r for r in s["scores"] if r["instrument"] != "I079"]
    with pytest.raises(ContractError, match="held score missing"):
        generate(s, sessions)


@pytest.mark.parametrize("section,column", [("control", "score"), ("control", "score_available_at"),
    ("control", "recorder_id"), ("universe", "candidate_present"), ("anti", "anti_rank"),
    ("anti", "anti_available_at"), ("anti", "source_sha256"), ("labels", "label")])
def test_merge_missing_columns_are_input_blocked(snapshot, section, column):
    s, _ = inputs(snapshot)
    parts = split_scores(s["scores"])
    parts[section][0].pop(column)
    with pytest.raises(ContractError, match="INPUT_BLOCKED.*missing"):
        merge.merge_scores(**parts)


@pytest.mark.parametrize("section", ["control", "anti", "labels"])
def test_merge_does_not_silently_inner_join_missing_keys(snapshot, section):
    s, _ = inputs(snapshot)
    parts = split_scores(s["scores"])
    parts[section].pop()
    with pytest.raises(ContractError, match="missing common keys"):
        merge.merge_scores(**parts)


def test_merge_audits_outside_common_keys_and_preserves_null_days(snapshot):
    s, _ = inputs(snapshot)
    parts = split_scores(s["scores"])
    parts["control"].append({**parts["control"][0], "instrument": "OUTSIDE"})
    for row in parts["labels"][:80]:
        row["label"] = None
    rows, audit = merge.merge_scores(**parts)
    assert len(rows) == 400 and all(r["label"] is None for r in rows[:80])
    assert audit["outside_common_keys"]["control"] == [["2026-09-07", "OUTSIDE"]]
    parts["labels"][0]["label"] = 0
    with pytest.raises(ContractError, match="partial label coverage"):
        merge.merge_scores(**parts)


@pytest.mark.parametrize("change,match", [
    (lambda p: p["control"].append(p["control"][0]), "duplicate key"),
    (lambda p: p["control"][0].update(recorder_id=CANDIDATE_RECORDER), "control recorder"),
    (lambda p: p["universe"][0].update(score=99), "membership only"),
    (lambda p: p["control"][0].update(candidate_score=99), "candidate score"),
    (lambda p: p["anti"][0].update(source_sha256="0" * 64), "sidecar source hash"),
    (lambda p: p["anti"][0].update(anti_rank=float("nan")), "finite number"),
])
def test_merge_provenance_duplicates_and_values(snapshot, change, match):
    s, _ = inputs(snapshot)
    parts = split_scores(s["scores"])
    change(parts)
    with pytest.raises(ContractError, match=match):
        merge.merge_scores(**parts)


def write(path, value):
    path.write_bytes(canonical_bytes(value) + b"\n")


@pytest.mark.parametrize("cache", [False, True])
@pytest.mark.parametrize("topk,n_drop", PAIRS)
def test_merge_rule_freeze_cli_end_to_end_and_default(snapshot, tmp_path, capsys, topk, n_drop, cache):
    s, sessions = inputs(snapshot, topk, n_drop)
    parts = split_scores(s["scores"])
    args = []
    for name, value in parts.items():
        path = tmp_path / f"{name}.json"
        write(path, value)
        args += [f"--{name}", str(path)]
    scores_dir = tmp_path / "merged"
    assert merge.main([*args, "--output-dir", str(scores_dir)]) == 0
    capsys.readouterr()
    s["scores"] = json.loads((scores_dir / "scores.json").read_bytes())
    paths = {"scores": scores_dir / "scores.json", "initial_state": tmp_path / "initial.json",
             "pref": tmp_path / "pref.json"}
    for name, path in paths.items():
        write(path, s[name])
        s["metadata"]["inputs"][name] = {"uri": str(path), "raw_sha256": raw_hash(path.read_bytes()),
            "content_sha256": content_hash(s[name]), "coverage": "synthetic five days", "version": "synthetic-v1"}
    for key in ("topk", "n_drop", "source", "rule_version"):
        s["metadata"]["strategy"].pop(key)
    write(tmp_path / "sessions.json", sessions)
    write(tmp_path / "metadata.json", s["metadata"])
    rule_dir = tmp_path / "rules"
    rule_args = ["--scores", str(paths["scores"]), "--initial-state", str(paths["initial_state"]),
                 "--sessions", str(tmp_path / "sessions.json"), "--metadata", str(tmp_path / "metadata.json"),
                 "--output-dir", str(rule_dir)]
    if cache:
        rule_args += ["--cache-plan-hash"]
    if topk != 50:
        rule_args += ["--topk", str(topk), "--n-drop", str(n_drop)]
    assert rules.main(rule_args) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert (receipt["topk"], receipt["n_drop"]) == (topk, n_drop)
    freeze_args = [arg for name, path in paths.items() for arg in (f"--{name.replace('_', '-')}", str(path))]
    frozen_path = tmp_path / "snapshot.json"
    assert freeze.main([*freeze_args, "--plans", str(rule_dir / "plans.json"),
                        "--metadata", str(rule_dir / "metadata.json"), "--output", str(frozen_path)]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["input_status"] == "INPUT_BLOCKED" and receipt["execution_status"] == "NOT_RUN"
    frozen, _ = load_snapshot(frozen_path)
    assert ("research_acceleration" in frozen["metadata"]) is cache
    with pytest.raises(ContractError, match="MQ-PJSON reference content drift"):
        build_portfolio(frozen)
    frozen["kind"] = "synthetic"  # explicit test only: frozen above must not bypass P-REF
    product = build_portfolio(frozen)
    assert all(len(s["positions"]) <= topk for s in product["final_states"].values())
    before = (rule_dir / "plans.json").read_bytes()
    assert rules.main(rule_args) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "OUTPUT_BLOCKED"
    assert (rule_dir / "plans.json").read_bytes() == before
    frozen["metadata"]["strategy"]["n_drop"] = 0
    with pytest.raises(ContractError, match="rule strategy drift"):
        build_portfolio(frozen)
    metadata_path = rule_dir / "metadata.json"
    changed = json.loads(metadata_path.read_bytes())
    changed["strategy"]["n_drop"] = 0
    write(metadata_path, changed)
    blocked_path = tmp_path / "blocked-snapshot.json"
    assert freeze.main([*freeze_args, "--plans", str(rule_dir / "plans.json"),
                        "--metadata", str(metadata_path), "--output", str(blocked_path)]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "PAIR_INVALID"
    assert not blocked_path.exists()
    # A required market column missing must produce a CLI INPUT_BLOCKED, without
    # creating a directory or replacing the earlier generated files.
    sessions[0]["market"][0].pop("buy_eligible")
    write(tmp_path / "sessions.json", sessions)
    rule_args[rule_args.index(str(rule_dir))] = str(tmp_path / "blocked-rules")
    assert rules.main(rule_args) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "INPUT_BLOCKED"
    assert not (tmp_path / "blocked-rules").exists()
    assert (rule_dir / "plans.json").read_bytes() == before


def test_cli_missing_fields_and_files_leave_no_output(tmp_path, capsys):
    for module, names in ((rules, ("scores", "initial-state", "sessions", "metadata")),
                          (merge, ("control", "universe", "anti", "labels"))):
        args = [arg for name in names for arg in (f"--{name}", str(tmp_path / f"{name}.json"))]
        assert module.main([*args, "--output-dir", str(tmp_path / "out")]) == 2
        assert json.loads(capsys.readouterr().out)["status"] == "INPUT_BLOCKED"
        assert not (tmp_path / "out").exists()
        assert module.main([]) == 2
        assert json.loads(capsys.readouterr().out)["status"] == "INPUT_BLOCKED"


def test_bundle_failed_readback_rolls_back_without_overwriting(tmp_path, monkeypatch):
    from pathlib import Path

    output = tmp_path / "new"
    original = Path.read_bytes

    def bad_read(path):
        return b"corrupt" if path.name == "manifest.json" else original(path)

    monkeypatch.setattr(Path, "read_bytes", bad_read)
    with pytest.raises(ContractError, match="readback drift"):
        merge.write_bundle(output, {"scores.json": [], "manifest.json": {"status": "test"}})
    assert not output.exists()


def test_new_modules_have_no_trading_imports_and_real_help():
    script = """
import sys
import my_scripts.joint_return_rule_intents
import my_scripts.joint_return_merge_scores
for name in ('qlib', 'backtrader', 'mlflow', 'host_env', 'analysis_export', 'numpy', 'pandas'):
    assert name not in sys.modules, name
"""
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True)
    for module in (rules, merge):
        result = subprocess.run([sys.executable, "-m", module.__name__, "--help"], check=True, capture_output=True, text=True)
        assert "--output-dir" in result.stdout
        if module is rules:
            assert "--topk" in result.stdout and "default 50" in result.stdout and "--n-drop" in result.stdout
