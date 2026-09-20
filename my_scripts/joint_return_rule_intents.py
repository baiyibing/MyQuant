"""Freeze TopkDropout backtest-rule plans (research default 50/5, also 20/3, 10/3).

Explicit JSON inputs only. No Qlib/Exchange/PortAna, prediction or live intents.
Run: python -m my_scripts.joint_return_rule_intents --help
"""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path

from my_scripts.joint_return_contract import (
    ARMS, DEFAULT_N_DROP, DEFAULT_TOPK, RULE_SOURCE, RULE_VERSION, ContractError,
    canonical_bytes, content_hash, date_string, fields, number, raw_hash, require,
    timestamp, validate_rule_strategy, validate_topk,
)
from my_scripts.joint_return_freeze_snapshot import _Parser, _read_json
from my_scripts.joint_return_merge_scores import write_bundle
from my_scripts.joint_return_portfolio import STATE_ATOL, _fee, _step, score_days, validate_state


def topk_dropout(ranked, held, *, topk=DEFAULT_TOPK, n_drop=DEFAULT_N_DROP):
    """Qlib top/bottom selection core, with explicit stable ties and n_drop=0.

    Qualification is applied after selection (only_tradable=False). Missing held
    scores block, instead of Qlib's implicit NaN placement.
    """
    validate_topk(topk, n_drop)
    names = [r["instrument"] for r in ranked]
    require(len(names) == len(set(names)), "duplicate ranked instrument")
    require(len(held) <= topk and set(held) <= set(names), "held score missing / position count exceeds topk")
    today = [i for i in names if i not in held][:n_drop + topk - len(held)]
    combined = [i for i in names if i in held or i in today]
    bottom = set(combined[-n_drop:]) if n_drop else set()
    sells = [i for i in names if i in held and i in bottom]
    return sells, today


def _market(session, ranked, state, strategy):
    fields(session, ("date", "decision_at", "available_at", "effective_at", "expires_at",
                     "mark_at", "price_domain", "source_version", "eligibility_version",
                     "market", "corporate_actions"), "rule session")
    day = session["date"]
    date_string(day)
    decision = timestamp(session["decision_at"])
    require(decision.date().isoformat() == day, "decision date mismatch")
    require(timestamp(session["mark_at"]) <= decision <= timestamp(session["available_at"])
            <= timestamp(session["effective_at"]) < timestamp(session["expires_at"]),
            "session clock violation", "PAIR_INVALID")
    require(session["price_domain"] == "none" and bool(session["source_version"]), "market source/domain missing")
    require(session["eligibility_version"] == strategy["eligibility_version"], "eligibility version drift")
    require(session["corporate_actions"] == [], "company-action mapping not implemented in MQ R1", "SEMANTICS_BLOCKED")
    require(isinstance(session["market"], list), "market rows required")
    market = {}
    for row in session["market"]:
        fields(row, ("instrument", "execution_symbol", "reference_price", "buy_eligible", "buy_reason",
                     "sell_eligible", "sell_reason", "eligibility_available_at"), "market row")
        for key in ("instrument", "execution_symbol", "buy_reason", "sell_reason"):
            require(isinstance(row[key], str) and bool(row[key]), f"market {key} required")
        require(row["instrument"] not in market, "duplicate market instrument")
        require(number(row["reference_price"], "reference_price", minimum=0) > 0, "nonpositive reference price")
        require(type(row["buy_eligible"]) is bool and type(row["sell_eligible"]) is bool, "explicit eligibility booleans required")
        require(timestamp(row["eligibility_available_at"]) <= decision, "future eligibility", "PAIR_INVALID")
        market[row["instrument"]] = row
    needed = {r["instrument"] for r in ranked} | state["positions"].keys()
    require(needed <= market.keys(), f"market rows missing: {sorted(needed - market.keys())[:10]}")
    return market


def make_rule_plan(arm, state, ages, ranked, session, metadata):
    strategy = metadata["strategy"]
    topk, n_drop = strategy["topk"], strategy["n_drop"]
    rules = strategy["rule_parameters"]
    market = _market(session, ranked, state, strategy)
    held = state["positions"]
    sell_names, today = topk_dropout(ranked, held, topk=topk, n_drop=n_drop)
    marks = {i: r["reference_price"] for i, r in market.items()}
    nav = state["cash"] + math.fsum(p["quantity"] * marks[i] for i, p in held.items())
    require(nav > 0, "nonpositive reference NAV", "PAIR_INVALID")
    plan = {key: deepcopy(session[key]) for key in ("date", "decision_at", "available_at", "effective_at",
                                                   "expires_at", "mark_at", "corporate_actions")}
    plan.update(arm_id=arm, source=RULE_SOURCE, pre_state_hash=content_hash(state), marks=marks,
                rule_version=RULE_VERSION, strategy_hash=content_hash(strategy),
                rule_trace={"session_hash": content_hash(session), "scores_hash": content_hash(ranked),
                            "holding_days": dict(ages), "ranked_sells": sell_names, "today": today,
                            "rejected_buys": []})

    def quantity(inst, amount, weight, *, selling=False):
        identity = held[inst] if selling else {
            "instance_id": content_hash([RULE_VERSION, arm, session["date"], inst, plan["pre_state_hash"]]),
            "lot_id": content_hash(["lot", RULE_VERSION, arm, session["date"], inst, plan["pre_state_hash"]])}
        return {"instrument": inst, "execution_symbol": market[inst]["execution_symbol"],
                "instance_id": identity["instance_id"], "lot_id": identity["lot_id"],
                "target_weight": weight, "original_target_quantity": amount,
                "reference_price": marks[inst], "reference_price_at": session["mark_at"],
                "quantity_unit": "share", "quantity_conversion": "SNAPSHOT_FIXED"}

    sells, cash = [], state["cash"]
    for inst in sell_names:
        approved = market[inst]["sell_eligible"] and ages[inst] >= rules["hold_thresh"]
        order = quantity(inst, held[inst]["quantity"], 0, selling=True)
        order.update(approved=approved, approval_reason=("HOLD_THRESHOLD" if ages[inst] < rules["hold_thresh"]
                                                        else market[inst]["sell_reason"]))
        sells.append(order)
        if approved:
            cash += order["original_target_quantity"] * marks[inst] - _fee({**order, "side": "SELL"}, metadata["fees"])
    # Reference contract keeps rejected sells and the topk cap. Unlike a fill
    # engine it never borrows an unfilled sell's slot or finances a buy.
    slots = min(len(today), sum(o["approved"] for o in sells) + topk - len(held))
    budget = cash * rules["risk_degree"] / slots if slots else 0
    options = []
    for row in ranked:
        inst = row["instrument"]
        if inst in held:
            continue
        amount = math.floor((budget + STATE_ATOL) / (marks[inst] * 100)) * 100
        if amount <= 0:
            plan["rule_trace"]["rejected_buys"].append({"instrument": inst, "reason": "LOT_ROUNDING_OR_NO_SLOT"})
            continue
        options.append({**quantity(inst, amount, budget / nav), "eligible": market[inst]["buy_eligible"],
                        "eligibility_reason": market[inst]["buy_reason"]})
    eligible = {o["instrument"] for o in options if o["eligible"]}
    plan.update(sells=sells, buys=[i for i in today[:slots] if i in eligible], buy_candidates=options)
    return plan


def generate_plans(scores, initial_state, sessions, metadata):
    """Generate both arms with independent ideal reference states, never fill feedback."""
    fields(metadata, ("strategy", "calendar", "fees", "risk_budget"), "rule metadata")
    validate_rule_strategy(metadata["strategy"])
    fees = metadata["fees"]
    fields(fees, ("model", "buy_rate", "sell_rate", "minimum", "granularity", "source"), "fees")
    require(fees["model"] == "commission_only" and fees["granularity"] == "per_order" and bool(fees["source"]),
            "unsupported reference fee model")
    for key in ("buy_rate", "sell_rate", "minimum"):
        number(fees[key], key, minimum=0)
    require(0 <= number(metadata["risk_budget"], "risk_budget") <= 1, "risk_budget outside [0,1]")
    topk = metadata["strategy"]["topk"]
    validate_state(initial_state, topk=topk)
    initial_ages = {}
    for inst, position in initial_state["positions"].items():
        fields(position, ("holding_days",), "initial position")
        age = position["holding_days"]
        require(type(age) is int and age >= 0, "initial holding_days must be a nonnegative integer")
        initial_ages[inst] = age
    calendar = metadata["calendar"]
    require(isinstance(calendar, list) and calendar and calendar == sorted(set(calendar)), "calendar order/duplicates")
    grouped = score_days(scores)
    require(set(calendar) <= grouped.keys(), "portfolio calendar missing scores")
    require(isinstance(sessions, list), "rule sessions must be a list")
    by_date = {}
    for session in sessions:
        fields(session, ("date",), "session")
        date_string(session["date"])
        require(session["date"] not in by_date, "duplicate rule session")
        by_date[session["date"]] = session
    require(set(by_date) == set(calendar), "missing/extra rule sessions")
    states = {arm: deepcopy(initial_state) for arm in ARMS}
    ages = {arm: dict(initial_ages) for arm in ARMS}
    plans, history = [], []
    symbols, reverse = {}, {}
    previous = None
    for day in calendar:
        decision = timestamp(by_date[day]["decision_at"]) if "decision_at" in by_date[day] else None
        require(decision is not None, "session: missing decision_at")
        require(previous is None or previous < decision, "nonmonotone decisions", "PAIR_INVALID")
        previous = decision
        for arm in ARMS:
            plan = make_rule_plan(arm, states[arm], ages[arm], grouped[day], by_date[day], metadata)
            for row in by_date[day]["market"]:
                inst, symbol = row["instrument"], row["execution_symbol"]
                require(symbols.setdefault(inst, symbol) == symbol and reverse.setdefault(symbol, inst) == inst,
                        "instrument mapping drift/collision", "SEMANTICS_BLOCKED")
            state, _, _, record = _step(arm, states[arm], plan, grouped[day], metadata)
            ages[arm] = {inst: ages[arm].get(inst, 0) + 1 for inst in state["positions"]}
            states[arm] = state
            plans.append(plan)
            history.append(record)
    return {"plans": plans, "reference_states": history, "final_states": states}


def main(argv=None):
    parser = _Parser(description=__doc__)
    for name in ("scores", "initial-state", "sessions", "metadata"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--topk", type=int, default=DEFAULT_TOPK, help="research default 50; no change to online 10/3 config")
    parser.add_argument("--n-drop", type=int, default=DEFAULT_N_DROP, help="research default 5; supports 50/5, 20/3, 10/3")
    parser.add_argument("--output-dir", required=True, type=Path)
    try:
        args = parser.parse_args(argv)
        values, sources = {}, {}
        for name in ("scores", "initial_state", "sessions", "metadata"):
            values[name], sources[name] = _read_json(getattr(args, name).resolve())
        metadata = deepcopy(values["metadata"])
        fields(metadata, ("strategy", "inputs"), "metadata")
        strategy = metadata["strategy"]
        require(isinstance(strategy, dict), "strategy: expected object")
        for key, value in (("topk", args.topk), ("n_drop", args.n_drop), ("source", RULE_SOURCE), ("rule_version", RULE_VERSION)):
            require(key not in strategy or (type(strategy[key]) is type(value) and strategy[key] == value),
                    f"CLI/metadata {key} drift")
            strategy[key] = value
        for name in ("scores", "initial_state"):
            fields(metadata["inputs"], (name,), "input sources")
            declared = metadata["inputs"][name]
            fields(declared, ("uri", "raw_sha256", "content_sha256", "coverage", "version"), name)
            for key in ("uri", "raw_sha256", "content_sha256"):
                require(declared[key] == sources[name][key], f"{name} {key} drift", "PAIR_INVALID")
        product = generate_plans(values["scores"], values["initial_state"], values["sessions"], metadata)
        plans = product["plans"]
        metadata["inputs"]["plans"] = {"uri": str((args.output_dir / "plans.json").resolve()),
            "raw_sha256": raw_hash(canonical_bytes(plans) + b"\n"), "content_sha256": content_hash(plans),
            "coverage": {"calendar": metadata["calendar"], "arms": list(ARMS), "rows": len(plans)},
            "version": RULE_VERSION, "rule_inputs": sources, "strategy_hash": content_hash(strategy)}
        manifest = {"status": "BACKTEST_RULE_PLANS_GENERATED", "input_status": "INPUT_BLOCKED",
                    "execution_status": "NOT_RUN", "return_status": "待实测", "strategy": strategy,
                    "inputs": sources, "plans": metadata["inputs"]["plans"],
                    "reference_states": product["reference_states"],
                    "verification_scope": "reference rule recursion only; upstream provenance/PIT and frozen P-REF require verification"}
        write_bundle(args.output_dir, {"plans.json": plans, "metadata.json": metadata, "rule-manifest.json": manifest})
    except (ContractError, OSError, TypeError, ValueError, KeyError) as exc:
        print(canonical_bytes({"status": getattr(exc, "status", "OUTPUT_BLOCKED" if isinstance(exc, OSError)
                                                else "INPUT_BLOCKED"), "detail": str(exc)}).decode())
        return 2
    print(canonical_bytes({"status": manifest["status"], "manifest": str(args.output_dir / "rule-manifest.json"),
                          "topk": args.topk, "n_drop": args.n_drop, "execution_status": "NOT_RUN"}).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
