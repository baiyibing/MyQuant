"""Frozen-snapshot P-REF / P-BASE / P-CHASE research producer, without backtests.

Run from the repository root: python -m my_scripts.joint_return_portfolio --help
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
import math
from pathlib import Path
import re
from statistics import mean, median

from my_scripts.joint_return_contract import (
    ARMS, CANDIDATE_RECORDER, CONSTRAINT_FIELDS, INTENT_FIELDS, ORDER_POLICY, PJSON_HASH,
    RECORDER, SCHEMA_VERSION,
    ContractError, canonical_bytes, content_hash, contract_hash, csv_bytes, date_string,
    fields, load_snapshot, number, raw_hash, require, sort_intents, timestamp,
    validate_intents, validate_plan_source, validate_snapshot,
)

PREF_ATOL = 1e-8
STATE_ATOL = 1e-8
BOOTSTRAP = {"block": 5, "reps": 10000, "seed": 20260919}
PREF_METRICS = (
    "n_days_calendar", "n_days_top10", "n_rows_mean", "top10_t0", "top10_t1", "d_top10",
    "d_top10_share_pos", "d_top10_share_neg", "d_top10_share_zero", "jaccard_mean",
    "turnover_mean", "overlap_mean", "share_identical", "n_relax_sum", "n_relax_days",
    "share_relaxed", "n_t0_below_median_mean", "t0_feat", "t1_feat", "univ_feat",
    "mean_n_at_kth", "share_kth_tied", "n_days_rankic", "rankic_ctrl",
    "added_feat", "dropped_feat", "added_label", "dropped_label", "swap_label_gap",
)


def score_days(rows):
    require(isinstance(rows, list) and rows, "scores snapshot missing")
    grouped = defaultdict(list)
    seen = set()
    for row in rows:
        fields(row, ("date", "instrument", "score", "score_available_at", "source_version",
                     "anti_rank", "anti_available_at", "candidate_present", "label"), "score")
        date_string(row["date"])
        require(isinstance(row["instrument"], str) and bool(row["instrument"]), "invalid instrument")
        key = row["date"], row["instrument"]
        require(key not in seen, f"duplicate score key: {key}")
        seen.add(key)
        number(row["score"], "score")
        require(0 <= number(row["anti_rank"], "anti_rank") <= 1, "anti-rank outside [0,1]")
        timestamp(row["score_available_at"])
        timestamp(row["anti_available_at"])
        require(bool(row["source_version"]) and row["candidate_present"] is True,
                "P-REF requires the frozen common universe; candidate scores are not inputs")
        require("candidate_score" not in row, "candidate score is forbidden")
        require(row.get("recorder_id", RECORDER) == RECORDER
                and CANDIDATE_RECORDER not in str(row["source_version"]), "candidate score source is forbidden")
        if row["label"] is not None:
            number(row["label"], "label")
        grouped[row["date"]].append(deepcopy(row))
    # Python's stable sort is byte-for-byte equivalent to mergesort on these unique keys.
    return {day: sorted(grouped[day], key=lambda r: (-r["score"], r["instrument"]))
            for day in sorted(grouped)}


def select_pref(ranked):
    require(len(ranked) >= 10, "P-REF common universe has fewer than ten instruments")
    t0 = ranked[:10]
    threshold = median(r["anti_rank"] for r in t0)
    qualified = [r for r in ranked if r["anti_rank"] >= threshold]
    relaxed = [r for r in ranked if r["anti_rank"] < threshold][:max(0, 10 - len(qualified))]
    t1 = qualified[:10] + relaxed
    return t0, t1, threshold, relaxed


def _bootstrap(values):
    # Local import keeps contract/portfolio generation independent of the numerical stack.
    import numpy as np

    require(len(values) >= BOOTSTRAP["block"], "P-REF bootstrap needs at least five usable days")
    sample = np.asarray(values, dtype=float)
    rng = np.random.default_rng(BOOTSTRAP["seed"])
    count = math.ceil(len(sample) / BOOTSTRAP["block"])
    starts = rng.integers(0, len(sample) - BOOTSTRAP["block"] + 1,
                          size=(BOOTSTRAP["reps"], count))
    indices = (starts[:, :, None] + np.arange(BOOTSTRAP["block"])).reshape(BOOTSTRAP["reps"], -1)
    means = sample[indices[:, :len(sample)]].mean(axis=1)
    lo, hi = np.quantile(means, [0.025, 0.975])
    return {**BOOTSTRAP, "point": float(sample.mean()), "lo": float(lo), "hi": float(hi)}


def _spearman(rows):
    def ranks(values):
        indices = sorted(range(len(values)), key=values.__getitem__)
        result = [0.0] * len(values)
        start = 0
        while start < len(values):
            end = start + 1
            while end < len(values) and values[indices[end]] == values[indices[start]]:
                end += 1
            for i in indices[start:end]:
                result[i] = (start + end - 1) / 2
            start = end
        center = mean(result)
        return [x - center for x in result]

    x, y = (ranks([r[key] for r in rows]) for key in ("score", "label"))
    denominator = math.sqrt(sum(a * a for a in x) * sum(b * b for b in y))
    return sum(a * b for a, b in zip(x, y)) / denominator if denominator else None


def _compare(actual, expected, path, mismatches):
    """Compare every computed field, preserving undefined statistics as explicit nulls."""
    if isinstance(actual, dict):
        fields(expected, actual, f"expected {path}")
        for key, value in actual.items():
            _compare(value, expected[key], f"{path}.{key}", mismatches)
    elif isinstance(actual, list):
        require(isinstance(expected, list) and len(expected) == len(actual), f"expected {path}: list coverage drift")
        for i, (value, target) in enumerate(zip(actual, expected)):
            _compare(value, target, f"{path}[{i}]", mismatches)
    elif type(actual) in (float, int):
        number(expected, f"expected {path}")
        if abs(actual - expected) > PREF_ATOL:
            mismatches.append({"field": path, "actual": actual, "expected": expected})
    elif actual != expected:
        mismatches.append({"field": path, "actual": actual, "expected": expected})


def check_pref(grouped, spec, *, synthetic):
    """Recheck original Top10Spread, rank/selection and time-slice statistics, not PnL."""
    fields(spec, ("calendar", "windows", "expected", "label", "bootstrap"), "pref")
    require(spec["label"] == "Ref($close,-2)/Ref($close,-1)-1", "P-REF label drift")
    require(spec["bootstrap"] == BOOTSTRAP, "P-REF bootstrap drift")
    require(spec["calendar"] == list(grouped), "P-REF missing/extra calendar days")
    require(isinstance(spec["windows"], dict) and bool(spec["windows"]), "P-REF windows missing")
    if not synthetic:
        require(content_hash(spec["expected"]) == PJSON_HASH, "MQ-PJSON reference content drift")
        require(spec["windows"] == {"2025_valid": {"start": "2025-01-03", "end": "2025-12-31"},
                                    "2026_oos": {"start": "2026-01-01", "end": "2026-09-14"}},
                "P-REF original windows required")
    fields(spec["expected"], ("windows",), "P-REF expected")
    require(set(spec["expected"]["windows"]) == set(spec["windows"]), "P-REF expected window coverage drift")
    for window in spec["windows"].values():
        fields(window, ("start", "end"), "P-REF window")
        require(date_string(window["start"]) <= date_string(window["end"]), "reversed P-REF window")
    for day in spec["calendar"]:
        require(sum(w["start"] <= day <= w["end"] for w in spec["windows"].values()) == 1,
                "P-REF calendar outside/disjoint window coverage")
    daily = []
    for day, ranked in grouped.items():
        t0, t1, threshold, relaxed = select_pref(ranked)
        present = [r["label"] is not None for r in ranked]
        require(all(present) or not any(present), f"{day}: partial label coverage needs source reconciliation")
        a, b = ({r["instrument"] for r in chosen} for chosen in (t0, t1))
        row = {"date": day, "t0": [r["instrument"] for r in t0],
               "t1": [r["instrument"] for r in t1], "median": threshold,
               "relaxed": [r["instrument"] for r in relaxed], "n_rows": len(ranked),
               "status": "USABLE" if all(present) else "LABEL_MISSING"}
        if all(present):
            universe_label = mean(r["label"] for r in ranked)
            spread0, spread1 = (mean(r["label"] for r in chosen) - universe_label for chosen in (t0, t1))
            row.update(top10_t0=spread0, top10_t1=spread1, d_top10=spread1 - spread0,
                       overlap=len(a & b), jaccard=len(a & b) / len(a | b),
                       turnover=1 - len(a & b) / 10, n_relax=len(relaxed),
                       below=sum(r["anti_rank"] < threshold for r in t0),
                       t0_feat=mean(r["anti_rank"] for r in t0),
                       t1_feat=mean(r["anti_rank"] for r in t1),
                       univ_feat=mean(r["anti_rank"] for r in ranked),
                       n_at_kth=sum(r["score"] == t0[-1]["score"] for r in ranked),
                       rankic=_spearman(ranked))
            for prefix, names in (("added", b - a), ("dropped", a - b)):
                subset = [r for r in ranked if r["instrument"] in names]
                for suffix, field in (("feat", "anti_rank"), ("label", "label")):
                    row[f"{prefix}_{suffix}"] = mean(r[field] for r in subset) if subset else None
            row["swap_label_gap"] = row["added_label"] - row["dropped_label"] if b != a else None
        daily.append(row)
    windows, mismatches = {}, []
    for name, window in spec["windows"].items():
        fields(window, ("start", "end"), f"window {name}")
        require(date_string(window["start"]) <= date_string(window["end"]), "reversed P-REF window")
        dates = [r for r in daily if window["start"] <= r["date"] <= window["end"]]
        usable = [r for r in dates if r["status"] == "USABLE"]
        require(len(usable) >= 5, f"{name}: insufficient P-REF days")
        stats = {"n_days_calendar": len(dates), "n_days_top10": len(usable),
                 "n_rows_mean": mean(r["n_rows"] for r in dates)}
        for key in ("top10_t0", "top10_t1", "d_top10", "t0_feat", "t1_feat", "univ_feat"):
            stats[key] = mean(r[key] for r in usable)
        for output, key in (("jaccard_mean", "jaccard"), ("turnover_mean", "turnover"),
                            ("overlap_mean", "overlap"), ("n_t0_below_median_mean", "below"),
                            ("mean_n_at_kth", "n_at_kth")):
            stats[output] = mean(r[key] for r in usable)
        for suffix, predicate in (("pos", lambda x: x > 0), ("neg", lambda x: x < 0),
                                   ("zero", lambda x: x == 0)):
            stats[f"d_top10_share_{suffix}"] = mean(predicate(r["d_top10"]) for r in usable)
        stats.update(share_identical=mean(r["overlap"] == 10 for r in usable),
                     n_relax_sum=sum(r["n_relax"] for r in usable),
                     n_relax_days=sum(r["n_relax"] > 0 for r in usable),
                     share_relaxed=mean(r["n_relax"] > 0 for r in usable),
                     share_kth_tied=mean(r["n_at_kth"] > 1 for r in usable),
                     bootstrap=_bootstrap([r["d_top10"] for r in usable]))
        rankics = [r["rankic"] for r in usable if r["rankic"] is not None]
        stats.update(n_days_rankic=len(rankics), rankic_ctrl=mean(rankics) if rankics else None)
        for key in ("added_feat", "dropped_feat", "added_label", "dropped_label", "swap_label_gap"):
            values = [r[key] for r in usable if r[key] is not None]
            stats[key] = mean(values) if values else None
        quarters = defaultdict(list)
        months = defaultdict(list)
        for row in usable:
            quarters[f"{row['date'][:4]}Q{(int(row['date'][5:7]) - 1) // 3 + 1}"].append(row["d_top10"])
            months[row["date"][:7]].append(row)
        stats["quarters"] = {q: mean(values) for q, values in quarters.items()}
        stats["months"] = [dict(month=month, n_days=len(rows), d_top10=mean(r["d_top10"] for r in rows),
                                d_top10_sum=sum(r["d_top10"] for r in rows),
                                d_top10_share_neg=mean(r["d_top10"] < 0 for r in rows),
                                turnover=mean(r["turnover"] for r in rows),
                                n_relax_mean=mean(r["n_relax"] for r in rows),
                                share_relaxed=mean(r["n_relax"] > 0 for r in rows))
                           for month, rows in months.items()]
        require(name in spec["expected"]["windows"], f"missing P-REF expected window {name}")
        expected = spec["expected"]["windows"][name]
        fields(expected, ("t0_vs_frozen_ctrl",), f"expected {name}")
        fields(expected["t0_vs_frozen_ctrl"], ("frozen_top10_ctrl",), "frozen control")
        frozen_control = number(expected["t0_vs_frozen_ctrl"]["frozen_top10_ctrl"], "frozen control")
        stats["t0_vs_frozen_ctrl"] = {"top10_t0": stats["top10_t0"], "frozen_top10_ctrl": frozen_control,
                                      "abs_diff": abs(stats["top10_t0"] - frozen_control)}
        _compare(stats, expected, name, mismatches)
        windows[name] = stats
    return {"status": "PREF_MISMATCH" if mismatches else ("SYNTHETIC_PASS" if synthetic else "PREF_PASS"),
            "absolute_tolerance": PREF_ATOL, "relative_tolerance": 0, "windows": windows,
            "mismatches": mismatches, "daily": daily, "expected_hash": content_hash(spec["expected"]),
            "numeric_scope": list(PREF_METRICS) + ["bootstrap", "months", "quarters", "t0_vs_frozen_ctrl"],
            "not_checked": ["lgb_frozen_d_top10 (external candidate model result; no candidate scores consumed)"],
            "semantics": "equal-weight Top10 minus common-universe equal-weight label; not PnL"}


def validate_state(state, *, topk):
    fields(state, ("cash", "positions", "quantity_unit", "native_stop"), "reference state")
    number(state["cash"], "cash", minimum=0)
    require(state["quantity_unit"] == "share" and state["native_stop"] == "N/A", "state unit/stop drift")
    positions = state["positions"]
    require(isinstance(positions, dict) and len(positions) <= topk, "invalid position count")
    lots = set()
    for instrument, position in positions.items():
        require(isinstance(instrument, str) and bool(instrument), "empty position instrument")
        fields(position, ("quantity", "lot_id", "instance_id"), "position")
        require(number(position["quantity"], "position quantity", minimum=0) > 0, "empty position")
        require(bool(position["lot_id"]) and bool(position["instance_id"]), "position identity missing")
        require(position["lot_id"] not in lots, "duplicate lot id")
        lots.add(position["lot_id"])


def _intent(arm, plan, order, side, reason):
    fields(order, ("instrument", "execution_symbol", "instance_id", "lot_id", "target_weight",
                   "original_target_quantity", "reference_price", "reference_price_at",
                   "quantity_unit", "quantity_conversion"), "frozen quantity")
    row = {key: order[key] for key in ("instrument", "execution_symbol", "instance_id", "lot_id",
                                     "target_weight", "original_target_quantity", "reference_price",
                                     "reference_price_at", "quantity_unit", "quantity_conversion")}
    row.update(arm_id=arm, decision_at=plan["decision_at"], available_at=plan["available_at"],
               side=side, reason=reason, reference_state_hash=plan["pre_state_hash"],
               source_plan_hash=content_hash(plan), effective_at=plan["effective_at"],
               expires_at=plan["expires_at"], native_stop="N/A", **ORDER_POLICY)
    row["intent_id"] = content_hash(row)
    validate_intents([row])
    return row


def _fee(intent, fees):
    value = intent["original_target_quantity"] * intent["reference_price"]
    return max(fees["minimum"], value * fees["buy_rate" if intent["side"] == "BUY" else "sell_rate"])


def _step(arm, state, plan, ranked, metadata):
    fields(plan, ("date", "arm_id", "pre_state_hash", "decision_at", "available_at", "effective_at",
                  "expires_at", "source", "marks", "mark_at", "sells", "buys", "buy_candidates",
                  "corporate_actions"), "frozen plan")
    validate_plan_source(plan, metadata["strategy"])
    if "rule_trace" in plan:
        require(plan["rule_trace"]["scores_hash"] == content_hash(ranked), "rule scores drift", "PAIR_INVALID")
    topk, n_drop = (metadata["strategy"][k] for k in ("topk", "n_drop"))
    require(plan["corporate_actions"] == [], "company-action mapping not implemented in MQ R1", "SEMANTICS_BLOCKED")
    require(plan["pre_state_hash"] == content_hash(state), f"{arm}/{plan['date']}: reference state discontinuity",
            "PAIR_INVALID")
    decision = timestamp(plan["decision_at"])
    require(decision.date().isoformat() == plan["date"], "decision date mismatch")
    require(timestamp(plan["mark_at"]) <= decision, "future marks", "PAIR_INVALID")
    require(decision <= timestamp(plan["available_at"]) <= timestamp(plan["effective_at"]) < timestamp(plan["expires_at"]),
            "plan clock violation", "PAIR_INVALID")
    require(all(timestamp(r[key]) <= decision for r in ranked for key in ("score_available_at", "anti_available_at")),
            "score/anti-rank not available at decision", "PAIR_INVALID")
    by_name = {r["instrument"]: r for r in ranked}
    _, _, threshold, _ = select_pref(ranked)
    audit = []

    def record(inst, status, reason):
        source = by_name.get(inst, {})
        audit.append(dict(date=plan["date"], arm_id=arm, instrument=inst, status=status, reason=reason,
                          score=source.get("score"), anti_rank=source.get("anti_rank"), t0_median=threshold,
                          reference_state_hash=plan["pre_state_hash"]))

    for rejected in plan.get("rule_trace", {}).get("rejected_buys", []):
        fields(rejected, ("instrument", "reason"), "rule rejection")
        record(rejected["instrument"], "RULE_BUY_BLOCKED", rejected["reason"])

    positions = state["positions"]
    marks = plan["marks"]
    require(isinstance(marks, dict) and set(positions) <= marks.keys(), "held position mark missing")
    for price in marks.values():
        require(number(price, "mark", minimum=0) > 0, "nonpositive mark")
    nav = state["cash"] + sum(p["quantity"] * marks[i] for i, p in positions.items())
    require(nav > 0, "nonpositive reference NAV", "PAIR_INVALID")
    drift = {i: p["quantity"] * marks[i] / nav for i, p in positions.items()}
    drift["CASH"] = state["cash"] / nav
    candidates = plan["buy_candidates"]
    require(isinstance(candidates, list) and isinstance(plan["buys"], list) and isinstance(plan["sells"], list),
            "plan lists required")
    options = {}
    for order in candidates:
        fields(order, ("eligible", "eligibility_reason"), "candidate eligibility")
        require(type(order["eligible"]) is bool and bool(order["eligibility_reason"]), "unknown eligibility")
        row = _intent(arm, plan, order, "BUY", "VALIDATE_CANDIDATE")
        inst = row["instrument"]
        require(inst not in options and inst in by_name and inst not in positions, "invalid/duplicate buy candidate")
        options[inst] = order
        if not order["eligible"]:
            record(inst, "ELIGIBILITY_BLOCKED", order["eligibility_reason"])
    buys = plan["buys"]
    require(len(buys) == len(set(buys)), "duplicate original buy")
    require(all(i in options and options[i]["eligible"] for i in buys), "original buy has missing/rejected eligibility")
    selected_sells, sell_seen = [], set()
    for order in plan["sells"]:
        fields(order, ("approved", "approval_reason"), "sell approval")
        require(type(order["approved"]) is bool and bool(order["approval_reason"]), "unknown sell approval")
        row = _intent(arm, plan, order, "SELL", "TOPK_DROPOUT_SELL")
        inst = row["instrument"]
        require(inst in positions and inst not in sell_seen, "sell absent/duplicated in reference state", "PAIR_INVALID")
        sell_seen.add(inst)
        held = positions[inst]
        require(row["original_target_quantity"] == held["quantity"] and row["lot_id"] == held["lot_id"]
                and row["instance_id"] == held["instance_id"] and row["target_weight"] == 0,
                "sell quantity/lot/target mismatch", "PAIR_INVALID")
        if order["approved"]:
            selected_sells.append(row)
        else:
            record(inst, "KEEP_UNAPPROVED_SELL", order["approval_reason"])
    require(len(plan["sells"]) <= n_drop, "rule sell count exceeds n_drop")
    require(len(positions) - len(selected_sells) + len(buys) <= topk, "rule plan expands topk")
    choices = [(i, "TOPK_DROPOUT_BUY") for i in buys]
    if arm == "P-CHASE":
        choices = []
        for inst in buys:
            if by_name[inst]["anti_rank"] < threshold:
                record(inst, "SKIP_BELOW_MEDIAN", "strictly below daily T0 median")
            else:
                choices.append((inst, "TOPK_DROPOUT_BUY"))
        selected = {i for i, _ in choices}
        remaining = [r for r in ranked if r["instrument"] in options
                     and options[r["instrument"]]["eligible"] and r["instrument"] not in selected]
        for qualified, reason in ((True, "BACKFILL_SCORE"), (False, "RELAX_BELOW_MEDIAN")):
            for row in remaining:
                if len(choices) == len(buys):
                    break
                if (row["anti_rank"] >= threshold) == qualified:
                    choices.append((row["instrument"], reason))
                    record(row["instrument"], reason, "P-REF preference; frozen eligible candidate quantity")
        require(len(choices) == len(buys), "insufficient frozen backfill quantities")
    intents = selected_sells + [_intent(arm, plan, options[i], "BUY", reason) for i, reason in choices]
    next_state = deepcopy(state)
    target = dict(drift)
    fees_total = 0
    for row in intents:
        inst = row["instrument"]
        require(inst in marks and marks[inst] == row["reference_price"]
                and row["reference_price_at"] == plan["mark_at"], "quantity/mark domain mismatch", "PAIR_INVALID")
        value = row["original_target_quantity"] * row["reference_price"]
        fee = _fee(row, metadata["fees"])
        fees_total += fee
        if row["side"] == "SELL":
            next_state["cash"] += value - fee
            del next_state["positions"][inst]
            target.pop(inst)
        else:
            require(value + fee <= next_state["cash"] + STATE_ATOL, "reference plan exceeds cash including fees", "PAIR_INVALID")
            next_state["cash"] -= value + fee
            next_state["positions"][inst] = {"quantity": row["original_target_quantity"],
                                              "lot_id": row["lot_id"], "instance_id": row["instance_id"]}
            # Audit the supplied conversion, never replace the supplied order quantity.
            quantity_budget = row["target_weight"] * nav
            expected_quantity = math.floor((quantity_budget + STATE_ATOL) / (row["reference_price"] * 100)) * 100
            require(row["original_target_quantity"] == expected_quantity,
                    "snapshot quantity disagrees with whole-lot target conversion", "PAIR_INVALID")
            target[inst] = row["target_weight"]
        require(next_state["cash"] >= -STATE_ATOL, "reference order exceeds cash including fees", "PAIR_INVALID")
        record(inst, "INTENT_EMITTED", row["reason"])
    if abs(next_state["cash"]) <= STATE_ATOL:
        next_state["cash"] = 0
    if intents:
        target["CASH"] = 1 - math.fsum(w for i, w in target.items() if i != "CASH")
    require(target["CASH"] >= -STATE_ATOL, "target weights exceed one", "PAIR_INVALID")
    require(1 - target["CASH"] <= metadata["risk_budget"] + STATE_ATOL, "target exceeds registered risk budget", "PAIR_INVALID")
    sold = {r["instrument"] for r in selected_sells}
    for inst in sorted(set(positions) - sold - sell_seen):
        record(inst, "KEEP_OLD_POSITION", "no approved original sell")
    validate_state(next_state, topk=topk)
    turnover = 0.5 * sum(abs(target.get(i, 0) - drift.get(i, 0)) for i in set(target) | set(drift))
    state_record = dict(date=plan["date"], arm_id=arm, before=deepcopy(state), after=deepcopy(next_state),
                        before_hash=content_hash(state), after_hash=content_hash(next_state),
                        source_plan=deepcopy(plan), pre_drift_weights=drift, target_weights=target,
                        target_turnover=turnover, initial_build=not bool(positions),
                        reference_fees=fees_total, reference_nav=nav, native_stop="N/A")
    return next_state, intents, audit, state_record


def build_portfolio(snapshot):
    validate_snapshot(snapshot)
    grouped = score_days(snapshot["scores"])
    pref = check_pref(grouped, snapshot["pref"], synthetic=snapshot["kind"] == "synthetic")
    require(pref["status"] != "PREF_MISMATCH", "P-REF numeric recheck failed", "PAIR_INVALID")
    metadata = snapshot["metadata"]
    validate_state(snapshot["initial_state"], topk=metadata["strategy"]["topk"])
    states = {arm: deepcopy(snapshot["initial_state"]) for arm in ARMS}
    plans = {}
    for plan in snapshot["plans"]:
        fields(plan, ("date", "arm_id"), "plan identity")
        key = plan["date"], plan["arm_id"]
        require(key not in plans, "duplicate daily arm plan")
        plans[key] = plan
    expected = {(day, arm) for day in metadata["calendar"] for arm in ARMS}
    require(set(plans) == expected, "missing/extra arm-days; explicit empty plans also required")
    intents, constraints, history = [], [], []
    symbols, reverse_symbols = {}, {}
    for day in metadata["calendar"]:
        require(day in grouped, f"missing scores: {day}")
        for arm in ARMS:
            state, rows, audit, record = _step(arm, states[arm], plans[day, arm], grouped[day], metadata)
            states[arm] = state
            intents.extend(rows)
            constraints.extend(audit)
            history.append(record)
            for row in rows:
                inst, symbol = row["instrument"], row["execution_symbol"]
                require(symbols.setdefault(inst, symbol) == symbol and reverse_symbols.setdefault(symbol, inst) == inst,
                        "instrument mapping drift/collision", "SEMANTICS_BLOCKED")
    intents = sort_intents(intents)
    validate_intents(intents)
    constraints.sort(key=lambda r: (r["date"], r["arm_id"], r["instrument"], r["status"], r["reason"]))
    return {"intents": intents, "constraints": constraints, "pref_check": pref,
            "reference_states": history, "final_states": states}


def run_snapshot(snapshot_path, output_root, run_id):
    require(isinstance(run_id, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", run_id), "unsafe run_id")
    snapshot, source = load_snapshot(snapshot_path)
    product = build_portfolio(snapshot)
    intent_bytes = csv_bytes(product["intents"], INTENT_FIELDS)
    constraint_bytes = csv_bytes(product["constraints"], CONSTRAINT_FIELDS)
    pref_bytes = canonical_bytes(product["pref_check"]) + b"\n"
    manifest = {
        "schema_version": SCHEMA_VERSION, "run_id": run_id, "kind": snapshot["kind"],
        "status": "MQ_DATA_FREE_PASS" if snapshot["kind"] == "synthetic" else "INPUT_BLOCKED",
        "input_status": "SYNTHETIC_ONLY" if snapshot["kind"] == "synthetic" else "INPUT_BLOCKED",
        "real_input_blockers": ["original source raw hashes and PIT/coverage require host verification"],
        "execution_status": "NOT_RUN", "return_status": "待实测", "contract_hash": contract_hash(),
        "metadata": snapshot["metadata"], "snapshot": source,
        "input_raw_hashes_verified": False,  # bundled source declarations are not original file checks
        "intent_hash": content_hash(product["intents"]),
        "arm_intent_hashes": {a: content_hash([r for r in product["intents"] if r["arm_id"] == a]) for a in ARMS},
        "artifacts": {"intents.csv": {"raw_sha256": raw_hash(intent_bytes), "content_sha256": content_hash(product["intents"])},
                      "constraints.csv": {"raw_sha256": raw_hash(constraint_bytes), "content_sha256": content_hash(product["constraints"])},
                      "pref_check.json": {"raw_sha256": raw_hash(pref_bytes), "content_sha256": content_hash(product["pref_check"])}},
        "reference_states": product["reference_states"], "initial_state": snapshot["initial_state"],
        "pairing": {"arms": list(ARMS), "fills": ["M-REF", "M-LAG"], "bt_acceptance": "NOT_RUN"},
    }
    path = Path(output_root) / run_id
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir(exist_ok=False)  # a run is immutable; never overwrite even an empty directory
    for name, data in (("intents.csv", intent_bytes), ("constraints.csv", constraint_bytes),
                       ("pref_check.json", pref_bytes), ("manifest.json", canonical_bytes(manifest) + b"\n")):
        (path / name).write_bytes(data)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path, help="explicit immutable JSON snapshot; no resolver")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path, default=Path("exports/analysis/joint-return-v1"))
    args = parser.parse_args(argv)
    try:
        path = run_snapshot(args.snapshot, args.output_root, args.run_id)
    except (ContractError, OSError) as exc:
        print(canonical_bytes({"status": getattr(exc, "status", "OUTPUT_BLOCKED"), "detail": str(exc)}).decode())
        return 2
    print(canonical_bytes({"manifest": str(path / "manifest.json"), "execution_status": "NOT_RUN"}).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
