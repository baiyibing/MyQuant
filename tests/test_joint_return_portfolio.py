"""Pure synthetic vectors: no recorder, lake, PortAna, BT, network or real return data."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from my_scripts.joint_return_contract import (
    ARMS, BASE_BT, BASE_MQ, CANDIDATE_RECORDER, INTENT_FIELDS, ORDER_POLICY, RECORDER,
    SCHEMA_VERSION, SIDECAR_SHA256, ContractError, canonical_bytes, content_hash,
    contract_hash, csv_bytes, load_json_bytes, load_snapshot, raw_hash, read_intents,
)
from my_scripts.joint_return_portfolio import (
    BOOTSTRAP, build_portfolio, check_pref, main, run_snapshot, score_days, select_pref,
)


def seal(snapshot):
    for key in ("scores", "initial_state", "plans", "pref"):
        snapshot["metadata"]["inputs"][key] = {
            "uri": f"synthetic://{key}", "raw_sha256": raw_hash(canonical_bytes(snapshot[key]) + b"\n"),
            "content_sha256": content_hash(snapshot[key]), "coverage": "five synthetic sessions",
            "version": "synthetic-v1",
        }
    return snapshot


def frozen_order(instrument, *, quantity=100, weight=1 / 15):
    return {"instrument": instrument, "execution_symbol": f"{instrument}.SYN",
            "instance_id": f"instance-{instrument}", "lot_id": f"lot-{instrument}",
            "target_weight": weight, "original_target_quantity": quantity,
            "reference_price": 10, "reference_price_at": "2026-09-07T15:00:00+08:00",
            "quantity_unit": "share", "quantity_conversion": "SNAPSHOT_FIXED"}


@pytest.fixture
def snapshot():
    days = [f"2026-09-{d:02d}" for d in range(7, 12)]
    scores = [{"date": day, "instrument": chr(65 + i), "score": 100 - i,
               "score_available_at": f"{day}T15:01:00+08:00", "source_version": "synthetic-v1",
               "anti_rank": 0.1 if i < 2 else (0.5 if i < 10 else 0.8),
               "anti_available_at": f"{day}T15:00:00+08:00", "candidate_present": True,
               "label": i / 100} for day in days for i in range(15)]
    initial = {"cash": 5000, "quantity_unit": "share", "native_stop": "N/A",
               "positions": {chr(i): {"quantity": 100, "lot_id": f"lot-{chr(i)}",
                                       "instance_id": f"instance-{chr(i)}"} for i in range(80, 90)}}
    plans = []
    for arm in ARMS:
        first = {"date": days[0], "arm_id": arm, "pre_state_hash": content_hash(initial),
                 "decision_at": f"{days[0]}T15:02:00+08:00", "available_at": f"{days[1]}T09:30:00+08:00",
                 "effective_at": f"{days[1]}T09:30:00+08:00", "expires_at": f"{days[1]}T15:00:00+08:00",
                 "source": "backtest_rule_intents", "marks": {chr(i): 10 for i in range(65, 90)},
                 "mark_at": f"{days[0]}T15:00:00+08:00", "corporate_actions": [],
                 "sells": [{**frozen_order(i, weight=0), "approved": i != "R",
                            "approval_reason": "allowed" if i != "R" else "holding gate"} for i in "PQR"],
                 "buys": ["A", "B"],
                 "buy_candidates": [{**frozen_order(chr(i)), "eligible": True,
                                     "eligibility_reason": "frozen eligible"} for i in range(65, 80)]}
        plans.append(first)
        after = deepcopy(initial)
        for inst in "PQ":
            del after["positions"][inst]
        for inst in ("AB" if arm == "P-BASE" else "CD"):
            after["positions"][inst] = {"quantity": 100, "lot_id": f"lot-{inst}", "instance_id": f"instance-{inst}"}
        second = deepcopy(first)
        second.update(date=days[1], pre_state_hash=content_hash(after),
                      decision_at=f"{days[1]}T15:02:00+08:00", available_at=f"{days[2]}T09:30:00+08:00",
                      effective_at=f"{days[2]}T09:30:00+08:00", expires_at=f"{days[2]}T15:00:00+08:00",
                      mark_at=f"{days[1]}T15:00:00+08:00", sells=[], buys=[], buy_candidates=[])
        plans.append(second)
    expected = {"n_days_calendar": 5, "n_days_top10": 5, "n_rows_mean": 15,
                "top10_t0": -0.025, "top10_t1": -0.005, "d_top10": 0.02,
                "d_top10_share_pos": 1, "d_top10_share_neg": 0, "d_top10_share_zero": 0,
                "jaccard_mean": 2 / 3, "turnover_mean": 0.2, "overlap_mean": 8,
                "share_identical": 0, "n_relax_sum": 0, "n_relax_days": 0, "share_relaxed": 0,
                "n_t0_below_median_mean": 2, "t0_feat": 0.42, "t1_feat": 0.56,
                "univ_feat": 8.2 / 15, "mean_n_at_kth": 1, "share_kth_tied": 0,
                "n_days_rankic": 5, "rankic_ctrl": -1, "added_feat": 0.8, "dropped_feat": 0.1,
                "added_label": 0.105, "dropped_label": 0.005, "swap_label_gap": 0.1,
                "quarters": {"2026Q3": 0.02},
                "months": [{"month": "2026-09", "n_days": 5, "d_top10": 0.02, "d_top10_sum": 0.1,
                            "d_top10_share_neg": 0, "turnover": 0.2, "n_relax_mean": 0, "share_relaxed": 0}],
                "t0_vs_frozen_ctrl": {"top10_t0": -0.025, "frozen_top10_ctrl": -0.025, "abs_diff": 0},
                "bootstrap": {**BOOTSTRAP, "point": 0.02, "lo": 0.02, "hi": 0.02}}
    return seal({"schema_version": SCHEMA_VERSION, "kind": "synthetic", "scores": scores,
                 "initial_state": initial, "plans": plans,
                 "pref": {"calendar": days, "windows": {"hand": {"start": days[0], "end": days[-1]}},
                          "expected": {"windows": {"hand": expected}},
                          "label": "Ref($close,-2)/Ref($close,-1)-1", "bootstrap": BOOTSTRAP.copy()},
                 "metadata": {"code_shas": {"MQ": BASE_MQ, "BT": BASE_BT},
                              "implementation_bases": {"MQ": BASE_MQ, "BT": BASE_BT},
                              "contract_hash": contract_hash(), "pred_recorder_id": RECORDER,
                              "candidate_recorder_id": CANDIDATE_RECORDER, "sidecar_sha256": SIDECAR_SHA256,
                              "generated_at": "2026-09-12T10:00:00+08:00",
                              "window": {"start": days[0], "end": days[1]}, "calendar": days[:2], "execution_calendar": days,
                              "timezone": "Asia/Shanghai", "price_domain": "none",
                              "strategy": {"topk": 10, "n_drop": 3, "source": "backtest_rule_intents",
                                           "rule_version": "topk-dropout-reference-v1",
                                           "rule_parameters": {"method_buy": "top", "method_sell": "bottom",
                                                               "only_tradable": False, "hold_thresh": 1, "risk_degree": 0.95},
                                           "eligibility_version": "synthetic-v1",
                                           "eligibility_rules": {"synthetic_only": "explicit per-order decisions"},
                                           "native_stop": "N/A"},
                              "fees": {"model": "commission_only", "buy_rate": 0, "sell_rate": 0,
                                       "minimum": 0, "granularity": "per_order", "source": "synthetic-zero"},
                              "risk_budget": 1, "valuation_version": "synthetic-none-mark-v1",
                              "benchmark_version": "same-fill-P-BASE-v1", "order_policy": ORDER_POLICY.copy(),
                              "quantity_policy": {"unit": "share", "buy_lot": 100, "sell": "FULL_LOT_EXIT",
                                                  "corporate_actions": "EXPLICIT_ONLY"}, "inputs": {}}})


def first_day_only(snapshot):
    snapshot["metadata"]["calendar"] = snapshot["metadata"]["calendar"][:1]
    snapshot["plans"] = [p for p in snapshot["plans"] if p["date"] == "2026-09-07"]
    return seal(snapshot)


def test_pref_hand_calculation_and_original_metric_scope(snapshot):
    out = check_pref(score_days(snapshot["scores"]), snapshot["pref"], synthetic=True)
    assert out["status"] == "SYNTHETIC_PASS"
    assert out["windows"]["hand"]["d_top10"] == pytest.approx(0.02)
    assert out["daily"][0]["t0"] == list("ABCDEFGHIJ")
    assert out["daily"][0]["t1"] == list("CDEFGHIJKL")
    assert "not PnL" in out["semantics"]
    assert out["windows"]["hand"]["rankic_ctrl"] == -1
    assert out["windows"]["hand"]["months"][0]["d_top10_sum"] == pytest.approx(0.1)


def test_pref_retains_a_whole_day_of_missing_labels(snapshot):
    day = "2026-09-14"
    snapshot["scores"] += [{**r, "date": day, "label": None} for r in snapshot["scores"][:15]]
    snapshot["pref"]["calendar"].append(day)
    snapshot["pref"]["windows"]["hand"]["end"] = day
    snapshot["pref"]["expected"]["windows"]["hand"]["n_days_calendar"] = 6
    out = check_pref(score_days(snapshot["scores"]), snapshot["pref"], synthetic=True)
    assert out["status"] == "SYNTHETIC_PASS"
    assert out["daily"][-1]["status"] == "LABEL_MISSING"
    assert out["windows"]["hand"]["n_days_top10"] == 5


def test_pref_degenerate_rankic_is_null_not_zero(snapshot):
    for row in snapshot["scores"]:
        row["score"] = 1
    snapshot["pref"]["expected"]["windows"]["hand"].update(
        n_days_rankic=0, rankic_ctrl=None, mean_n_at_kth=15, share_kth_tied=1)
    out = check_pref(score_days(snapshot["scores"]), snapshot["pref"], synthetic=True)
    assert out["status"] == "SYNTHETIC_PASS"
    assert out["windows"]["hand"]["rankic_ctrl"] is None


def test_ties_and_median_equality_are_deterministic(snapshot):
    rows = deepcopy(snapshot["scores"][:15])
    for row in rows:
        row["score"] = 1
    ranked = score_days(list(reversed(rows)))["2026-09-07"]
    t0, t1, threshold, relaxed = select_pref(ranked)
    assert [r["instrument"] for r in t0] == list("ABCDEFGHIJ")
    assert threshold == 0.5 and t1[0]["instrument"] == "C" and not relaxed


def test_pref_qualified_shortfall_relaxes_by_original_score(snapshot):
    rows = deepcopy(snapshot["scores"][:10])
    for i, row in enumerate(rows):
        row["anti_rank"] = i / 10
    t0, t1, threshold, relaxed = select_pref(score_days(rows)["2026-09-07"])
    assert threshold == pytest.approx(0.45)
    assert [r["instrument"] for r in t1] == list("FGHIJABCDE")
    assert [r["instrument"] for r in relaxed] == list("ABCDE")


def test_independent_recursion_preserves_old_holdings_and_fixed_quantities(snapshot):
    before = deepcopy(snapshot)
    out = build_portfolio(snapshot)
    assert snapshot == before
    assert set(out["final_states"]["P-BASE"]["positions"]) == set("ABRSTUVWXY")
    assert set(out["final_states"]["P-CHASE"]["positions"]) == set("CDRSTUVWXY")
    assert len(out["intents"]) == 8  # no daily whole-portfolio replacement
    assert all(r["original_target_quantity"] == 100 for r in out["intents"])
    assert all(r["target_turnover"] == pytest.approx(2 / 15) for r in out["reference_states"][:2])
    assert all(r["target_turnover"] == 0 for r in out["reference_states"][2:])
    assert any(r["instrument"] == "R" and r["status"] == "KEEP_UNAPPROVED_SELL" for r in out["constraints"])
    assert {r["instrument"] for r in out["constraints"] if r["status"] == "SKIP_BELOW_MEDIAN"} == {"A", "B"}


def test_chase_retains_original_equal_median_buy_and_backfills_score(snapshot):
    first_day_only(snapshot)
    for plan in snapshot["plans"]:
        plan["buys"] = ["A", "F"]
    out = build_portfolio(seal(snapshot))
    chosen = {r["instrument"]: r["reason"] for r in out["intents"] if r["arm_id"] == "P-CHASE" and r["side"] == "BUY"}
    assert chosen == {"C": "BACKFILL_SCORE", "F": "TOPK_DROPOUT_BUY"}


def test_chase_relaxation_does_not_bypass_eligibility(snapshot):
    first_day_only(snapshot)
    for plan in snapshot["plans"]:
        plan["buy_candidates"] = [r for r in plan["buy_candidates"] if r["instrument"] in "ABC"]
        plan["buy_candidates"][-1]["eligible"] = False
    out = build_portfolio(seal(snapshot))
    rows = [r for r in out["intents"] if r["arm_id"] == "P-CHASE" and r["side"] == "BUY"]
    assert [r["instrument"] for r in rows] == ["A", "B"]
    assert all(r["reason"] == "RELAX_BELOW_MEDIAN" for r in rows)
    assert sum(r["status"] == "RELAX_BELOW_MEDIAN" for r in out["constraints"]) == 2


def test_state_reset_to_control_is_rejected(snapshot):
    base = next(p for p in snapshot["plans"] if p["date"] == "2026-09-08" and p["arm_id"] == "P-BASE")
    chase = next(p for p in snapshot["plans"] if p["date"] == "2026-09-08" and p["arm_id"] == "P-CHASE")
    chase["pre_state_hash"] = base["pre_state_hash"]
    with pytest.raises(ContractError, match="PAIR_INVALID.*discontinuity"):
        build_portfolio(seal(snapshot))


@pytest.mark.parametrize("mutation,match", [
    (lambda s: s.update(plans=[]), "backtest rule plans missing"),
    (lambda s: s["plans"].pop(), "missing/extra arm-days"),
    (lambda s: s["plans"].append(deepcopy(s["plans"][0])), "duplicate daily arm plan"),
    (lambda s: s["scores"].append(deepcopy(s["scores"][0])), "duplicate score key"),
    (lambda s: s["scores"][0].update(score=float("nan")), "finite JSON"),
    (lambda s: s["scores"][0].update(candidate_score=999), "candidate score is forbidden"),
    (lambda s: s["scores"][0].update(candidate_present=False), "common universe"),
    (lambda s: s["scores"][0].update(label=None), "partial label coverage"),
    (lambda s: s["scores"][0].update(score_available_at="2026-09-07T16:00:00+08:00"), "not available"),
    (lambda s: s["scores"][0].update(anti_available_at="2026-09-07T16:00:00+08:00"), "not available"),
    (lambda s: s["plans"][0].update(source="PortAna_positions"), "cannot reconstruct intent"),
    (lambda s: s["plans"][0].update(corporate_actions=[{"factor": 2}]), "SEMANTICS_BLOCKED"),
    (lambda s: s["plans"][0].update(available_at="2026-09-07T15:00:00+08:00"), "clock violation"),
    (lambda s: s["plans"][0].update(expires_at="2026-09-07T15:03:00+08:00"), "clock violation"),
    (lambda s: s["plans"][0].update(decision_at="2026-09-07T15:02:00"), "Asia/Shanghai"),
    (lambda s: s["plans"][0]["marks"].pop("R"), "held position mark missing"),
    (lambda s: s["plans"][0]["sells"][0].update(original_target_quantity=200), "sell quantity/lot/target"),
    (lambda s: s["plans"][0]["buy_candidates"][0].update(eligible=False), "original buy"),
    (lambda s: s["plans"][0]["buy_candidates"][0].update(original_target_quantity=150), "whole 100-share"),
    (lambda s: s["plans"][0]["buy_candidates"][0].update(quantity_unit="lot"), "SEMANTICS_BLOCKED"),
    (lambda s: s["metadata"]["strategy"].update(topk=0), "topk must be a positive integer"),
    (lambda s: s["metadata"]["strategy"].update(eligibility_rules={}), "eligibility rules missing"),
    (lambda s: s["metadata"].update(pred_recorder_id="8a061ea4"), "full recorder mismatch"),
    (lambda s: s["metadata"].update(sidecar_sha256="0" * 64), "sidecar hash mismatch"),
    (lambda s: s["metadata"].update(price_domain="front"), "domain drift"),
    (lambda s: s["metadata"].update(contract_hash="0" * 64), "contract hash drift"),
    (lambda s: s["metadata"]["strategy"].update(native_stop="r2"), "added stops"),
    (lambda s: s["metadata"]["order_policy"].update(retry_policy="SAME_BAR"), "policy drift"),
    (lambda s: s["pref"]["expected"]["windows"]["hand"].update(top10_t0=0), "numeric recheck failed"),
    (lambda s: s["pref"].update(calendar=s["pref"]["calendar"][:-1]), "missing/extra calendar"),
])
def test_fail_closed_snapshot_boundaries(snapshot, mutation, match):
    mutation(snapshot)
    with pytest.raises(ContractError, match=match):
        build_portfolio(seal(snapshot))


def test_fees_are_once_per_order_and_reference_cash_is_independent(snapshot):
    first_day_only(snapshot)
    snapshot["metadata"]["fees"].update(buy_rate=0.001, sell_rate=0.002, minimum=5)
    out = build_portfolio(seal(snapshot))
    for arm in ARMS:
        assert out["final_states"][arm]["cash"] == 4980
    assert [r["reference_fees"] for r in out["reference_states"]] == [20, 20]


def test_reference_cash_including_fee_cannot_be_negative(snapshot):
    first_day_only(snapshot)
    snapshot["metadata"]["fees"]["minimum"] = 3000
    with pytest.raises(ContractError, match="cash including fees"):
        build_portfolio(seal(snapshot))


def test_each_reference_sell_must_fund_its_fee_without_later_proceeds(snapshot):
    first_day_only(snapshot)
    snapshot["initial_state"]["cash"] = 0
    snapshot["metadata"]["fees"]["minimum"] = 200
    for plan in snapshot["plans"]:
        plan["pre_state_hash"] = content_hash(snapshot["initial_state"])
        plan["buys"] = []
        plan["marks"]["P"] = 1
        plan["sells"][0]["reference_price"] = 1
    with pytest.raises(ContractError, match="reference order exceeds cash including fees"):
        build_portfolio(seal(snapshot))


def test_initial_build_turnover_includes_cash_and_is_flagged(snapshot):
    first_day_only(snapshot)
    snapshot["initial_state"].update(cash=10000, positions={})
    for plan in snapshot["plans"]:
        plan.update(pre_state_hash=content_hash(snapshot["initial_state"]), sells=[], buys=list("ABCDEFGHIJ"))
        for order in plan["buy_candidates"]:
            order["target_weight"] = 0.1
    out = build_portfolio(seal(snapshot))
    assert len(out["intents"]) == 20
    assert all(r["initial_build"] and r["target_turnover"] == 1 for r in out["reference_states"])
    assert all(s["cash"] == 0 and len(s["positions"]) == 10 for s in out["final_states"].values())


def test_more_than_three_approved_sells_or_eleven_holdings_rejected(snapshot):
    first_day_only(snapshot)
    plan = snapshot["plans"][0]
    for order in plan["sells"]:
        order["approved"] = True
    plan["sells"].append({**frozen_order("S", weight=0), "approved": True, "approval_reason": "allowed"})
    with pytest.raises(ContractError, match="sell count exceeds n_drop"):
        build_portfolio(seal(snapshot))
    plan["sells"] = []
    with pytest.raises(ContractError, match="expands topk"):
        build_portfolio(seal(snapshot))


def test_quantity_conversion_drift_rejected(snapshot):
    first_day_only(snapshot)
    snapshot["plans"][0]["buy_candidates"][0]["target_weight"] = 0.001
    with pytest.raises(ContractError, match="quantity disagrees"):
        build_portfolio(seal(snapshot))
    snapshot["plans"][0]["buy_candidates"][0]["target_weight"] = 2 / 15
    with pytest.raises(ContractError, match="quantity disagrees"):
        build_portfolio(seal(snapshot))  # exact whole-lot boundary must not accept one lot too few


def test_numeric_synthetic_expected_cannot_pass_as_real(snapshot):
    snapshot["kind"] = "frozen"
    with pytest.raises(ContractError, match="MQ-PJSON reference content drift"):
        build_portfolio(snapshot)


def test_hashes_detect_score_mutation_and_roundtrip_all_intent_fields(snapshot, tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_bytes(canonical_bytes(snapshot) + b"\n")
    loaded, source = load_snapshot(path)
    assert source["raw_sha256"] != source["content_sha256"]
    out = build_portfolio(loaded)
    csv_path = tmp_path / "intents.csv"
    csv_path.write_bytes(csv_bytes(out["intents"], INTENT_FIELDS))
    assert read_intents(csv_path) == out["intents"]
    assert all(set(r) == set(INTENT_FIELDS) for r in read_intents(csv_path))
    loaded["scores"][0]["score"] += 1
    with pytest.raises(ContractError, match="scores content drift"):
        build_portfolio(loaded)


def test_csv_rejects_dropped_column_or_duplicate_intent(snapshot, tmp_path):
    rows = build_portfolio(snapshot)["intents"]
    path = tmp_path / "bad.csv"
    path.write_bytes(csv_bytes(rows + rows[:1], INTENT_FIELDS))
    with pytest.raises(ContractError, match="duplicate intent"):
        read_intents(path)
    path.write_bytes(csv_bytes(rows, INTENT_FIELDS[:-1]))
    with pytest.raises(ContractError, match="column drift"):
        read_intents(path)
    rows[0]["original_target_quantity"] = 200
    path.write_bytes(csv_bytes(rows, INTENT_FIELDS))
    with pytest.raises(ContractError, match="identity/content mismatch"):
        read_intents(path)


def test_stable_serialization_and_strict_json():
    assert canonical_bytes({"乙": 2, "a": 1}) == b'{"a":1,"\xe4\xb9\x99":2}'
    assert content_hash({"b": 2, "a": 1}) == content_hash({"a": 1, "b": 2})
    for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'\xef\xbb\xbf{}', b'\0', b'\xff'):
        with pytest.raises(ContractError):
            load_json_bytes(raw)


def test_artifacts_are_reproducible_immutable_and_pair_hashes_bind_full_intents(snapshot, tmp_path):
    source = tmp_path / "input.json"
    source.write_bytes(canonical_bytes(snapshot))
    root = tmp_path / "exports/analysis/joint-return-v1"
    first = run_snapshot(source, root, "synthetic-a")
    second = run_snapshot(source, root, "synthetic-b")
    assert {p.name for p in first.iterdir()} == {"manifest.json", "intents.csv", "constraints.csv", "pref_check.json"}
    manifest = json.loads((first / "manifest.json").read_text())
    assert manifest["status"] == "MQ_DATA_FREE_PASS"
    assert manifest["execution_status"] == "NOT_RUN" and manifest["return_status"] == "待实测"
    assert manifest["input_raw_hashes_verified"] is False
    assert manifest["intent_hash"] == content_hash(read_intents(first / "intents.csv"))
    assert manifest["arm_intent_hashes"]["P-BASE"] != manifest["arm_intent_hashes"]["P-CHASE"]
    for name, hashes in manifest["artifacts"].items():
        assert hashes["raw_sha256"] == raw_hash((first / name).read_bytes())
        assert (first / name).read_bytes() == (second / name).read_bytes()
    with pytest.raises(FileExistsError):
        run_snapshot(source, root, "synthetic-a")
    with pytest.raises(ContractError, match="unsafe run_id"):
        run_snapshot(source, root, "../escape")


def test_missing_snapshot_cli_reports_input_blocked_and_creates_no_run(tmp_path, capsys):
    assert main(["--snapshot", str(tmp_path / "missing.json"), "--run-id", "missing",
                 "--output-root", str(tmp_path / "out")]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "INPUT_BLOCKED"
    assert not (tmp_path / "out").exists()


def test_import_fence_and_help_are_data_free():
    script = """
import sys
import my_scripts.joint_return_contract
import my_scripts.joint_return_portfolio
for name in ('qlib', 'host_env', 'backtrader', 'mlflow', 'data_root', 'analysis_export'):
    assert name not in sys.modules, name
"""
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)
    help_result = subprocess.run([sys.executable, "-m", "my_scripts.joint_return_portfolio", "--help"],
                                 check=True, capture_output=True, text=True)
    assert "--snapshot" in help_result.stdout
