"""Versioned, data-free joint-return wire format; no data resolver or trading imports."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA_VERSION = "joint-return-v1"
BASE_MQ = "4e4368b274ada2e27da5902f7420aa5a8ae5950c"
BASE_BT = "1049b904bdd818dbb79f51f1830a008c8f83b141"
RECORDER = "8a061ea428e04bb3a199a485ade49d0e"
CANDIDATE_RECORDER = "d03e8ffcb6d14668b4d6fc2b192bc8c7"
SIDECAR_SHA256 = "27320f8b7f6de3854802f97325f682039732470ce387f21bc9cd6c3083b7b348"
PJSON_HASH = "d9b503fa40937c6b870fc4b0bf9285e2ca53f0465af223f529f2e854712ae6f8"
ARMS = ("P-BASE", "P-CHASE")
RULE_SOURCE = "backtest_rule_intents"
RULE_VERSION = "topk-dropout-reference-v1"
DEFAULT_TOPK = 50
DEFAULT_N_DROP = 5
INTENT_FIELDS = (
    "arm_id", "intent_id", "instance_id", "lot_id", "instrument", "execution_symbol",
    "decision_at", "available_at", "side", "target_weight", "original_target_quantity",
    "quantity_unit", "quantity_conversion", "reference_price", "reference_price_at",
    "reason", "reference_state_hash", "source_plan_hash", "effective_at", "expires_at",
    "retry_policy", "conflict_policy", "expiry_policy", "native_stop",
)
CONSTRAINT_FIELDS = (
    "date", "arm_id", "instrument", "status", "reason", "score", "anti_rank",
    "t0_median", "reference_state_hash",
)
ORDER_POLICY = {
    "retry_policy": "NEXT_LEGAL_BAR_LIMIT_DOWN_NEXT_SESSION",
    "conflict_policy": "CANCEL_OLDER_REMAINDER_SELL_FIRST",
    "expiry_policy": "CANCEL_REMAINDER_EXPIRY_EXIT_DEFER_NO_BAR",
}
ORDER_STATES = (
    "CREATED", "WAITING", "ACTIVE", "PARTIAL", "FILLED", "REJECTED", "EXPIRED", "CANCELLED",
)
REASONS = (
    "NOT_AVAILABLE", "T_PLUS_ONE", "LIMIT_UP", "LIMIT_DOWN", "SUSPENDED", "NO_BAR",
    "CASH_INSUFFICIENT", "SELLABLE_INSUFFICIENT", "LOT_ROUNDING", "EXPIRED",
    "SUPERSEDED", "UNIT_MAPPING_BLOCKED", "STALE_MARK",
)


class ContractError(ValueError):
    def __init__(self, status: str, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(f"{status}: {detail}")


def require(condition, detail, status="INPUT_BLOCKED"):
    if not condition:
        raise ContractError(status, detail)


def validate_topk(topk, n_drop):
    require(type(topk) is int and topk > 0, "topk must be a positive integer")
    require(type(n_drop) is int and 0 <= n_drop <= topk,
            "n_drop must be an integer in [0, topk]")


def validate_rule_strategy(strategy):
    fields(strategy, ("topk", "n_drop", "source", "rule_version", "rule_parameters",
                      "eligibility_version", "eligibility_rules", "native_stop"), "strategy")
    validate_topk(strategy["topk"], strategy["n_drop"])
    require(strategy["source"] == RULE_SOURCE and strategy["native_stop"] == "N/A",
            "backtest rule intents required; no live/PortAna intents or added stops")
    require(strategy["rule_version"] == RULE_VERSION, "unsupported rule version")
    rules = strategy["rule_parameters"]
    fields(rules, ("method_buy", "method_sell", "only_tradable", "hold_thresh", "risk_degree"), "rule parameters")
    require(set(rules) == {"method_buy", "method_sell", "only_tradable", "hold_thresh", "risk_degree"},
            "unknown rule parameters")
    require(rules["method_buy"] == "top" and rules["method_sell"] == "bottom"
            and rules["only_tradable"] is False, "unsupported TopkDropout variant")
    require(type(rules["hold_thresh"]) is int and rules["hold_thresh"] >= 0, "invalid hold_thresh")
    require(0 <= number(rules["risk_degree"], "risk_degree") <= 1, "risk_degree outside [0,1]")
    require(bool(strategy["eligibility_version"]), "eligibility provenance missing")
    require(isinstance(strategy["eligibility_rules"], dict) and bool(strategy["eligibility_rules"]),
            "explicit frozen eligibility rules missing")


def validate_plan_source(plan, strategy):
    require(plan["source"] == RULE_SOURCE, "cannot reconstruct intent from filled positions / PortAna")
    if any(key in plan for key in ("strategy_hash", "rule_version", "rule_trace")):
        fields(plan, ("strategy_hash", "rule_version", "rule_trace"), "generated rule plan")
        require(plan["strategy_hash"] == content_hash(strategy) and plan["rule_version"] == RULE_VERSION,
                "rule strategy drift", "PAIR_INVALID")
        fields(plan["rule_trace"], ("session_hash", "scores_hash", "holding_days", "ranked_sells", "today",
                                   "rejected_buys"), "rule trace")
        for key in ("session_hash", "scores_hash"):
            sha(plan["rule_trace"][key])


def fields(value, names, context):
    require(isinstance(value, dict), f"{context}: expected object")
    missing = set(names) - value.keys()
    require(not missing, f"{context}: missing {sorted(missing)}")


def number(value, name, *, minimum=None):
    require(type(value) in (int, float) and math.isfinite(value), f"{name}: finite number required")
    require(minimum is None or value >= minimum, f"{name}: below minimum {minimum}")
    return value


def timestamp(value):
    require(isinstance(value, str), "timestamp must be a string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ContractError("INPUT_BLOCKED", f"invalid timestamp: {value}") from exc
    require(parsed.utcoffset() == timedelta(hours=8), "timestamp must carry Asia/Shanghai +08:00")
    require(parsed.isoformat(timespec="seconds") == value, "timestamp requires seconds, no fractions")
    return parsed


def date_string(value):
    require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value), "invalid date")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ContractError("INPUT_BLOCKED", f"invalid date: {value}") from exc


def sha(value, length=64):
    require(isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{length}}}", value), "invalid full hash")
    return value


def canonical_bytes(value):
    """Object keys sorted; arrays retain semantic order; UTF-8, compact JSON, no LF."""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise ContractError("INPUT_BLOCKED", "value is not finite JSON") from exc


def raw_hash(data):
    return hashlib.sha256(data).hexdigest()


def content_hash(value):
    return raw_hash(canonical_bytes(value))


def contract_hash():
    """Normative document bytes bind definitions as well as the column list."""
    path = Path(__file__).resolve().parents[1] / "docs/reviews/joint-return-v1/contract.md"
    return raw_hash(path.read_bytes())


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_bytes(raw):
    require(not raw.startswith(b"\xef\xbb\xbf") and b"\0" not in raw, "BOM/NUL forbidden")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError("INPUT_BLOCKED", "invalid UTF-8 JSON") from exc
    canonical_bytes(value)  # also reject NaN/Infinity accepted by the JSON parser
    return value


def load_snapshot(path):
    """Only read the explicitly named file. Source URIs are never resolved here."""
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise ContractError("INPUT_BLOCKED", f"snapshot unavailable: {path}") from exc
    snapshot = load_json_bytes(raw)
    validate_snapshot(snapshot)
    return snapshot, {"uri": str(Path(path).resolve()), "raw_sha256": raw_hash(raw),
                      "content_sha256": content_hash(snapshot), "raw_verified": True}


def validate_snapshot(snapshot):
    fields(snapshot, ("schema_version", "kind", "metadata", "scores", "initial_state", "plans", "pref"),
           "snapshot")
    require(snapshot["schema_version"] == SCHEMA_VERSION, "schema version drift")
    require(snapshot["kind"] in ("synthetic", "frozen"), "unknown snapshot kind")
    m = snapshot["metadata"]
    fields(m, ("code_shas", "implementation_bases", "contract_hash", "pred_recorder_id",
               "candidate_recorder_id", "sidecar_sha256", "generated_at", "window", "calendar",
               "timezone", "price_domain", "strategy", "fees", "risk_budget", "valuation_version",
               "benchmark_version", "order_policy", "quantity_policy", "inputs"), "metadata")
    require(m["implementation_bases"] == {"MQ": BASE_MQ, "BT": BASE_BT}, "implementation base drift")
    fields(m["code_shas"], ("MQ", "BT"), "code_shas")
    for value in m["code_shas"].values():
        sha(value, 40)
    require(m["contract_hash"] == contract_hash(), "contract hash drift", "PAIR_INVALID")
    require(m["pred_recorder_id"] == RECORDER and m["candidate_recorder_id"] == CANDIDATE_RECORDER,
            "full recorder mismatch")
    require(m["sidecar_sha256"] == SIDECAR_SHA256, "existing sidecar hash mismatch")
    timestamp(m["generated_at"])
    require(m["timezone"] == "Asia/Shanghai" and m["price_domain"] == "none", "time/price domain drift")
    fields(m["window"], ("start", "end"), "window")
    start, end = (date_string(m["window"][key]) for key in ("start", "end"))
    require(start <= end, "reversed window")
    calendar = m["calendar"]
    require(isinstance(calendar, list) and calendar and calendar == sorted(set(calendar)), "calendar order/duplicates")
    require(all(start <= date_string(d) <= end for d in calendar), "calendar outside window")
    strategy = m["strategy"]
    validate_rule_strategy(strategy)
    require(m["order_policy"] == ORDER_POLICY, "lifecycle policy drift")
    require(m["quantity_policy"] == {"unit": "share", "buy_lot": 100, "sell": "FULL_LOT_EXIT",
                                     "corporate_actions": "EXPLICIT_ONLY"}, "quantity policy drift")
    fees = m["fees"]
    fields(fees, ("model", "buy_rate", "sell_rate", "minimum", "granularity", "source"), "fees")
    require(fees["model"] == "commission_only" and fees["granularity"] == "per_order",
            "unsupported reference fee model")
    for key in ("buy_rate", "sell_rate", "minimum"):
        number(fees[key], key, minimum=0)
    require(bool(fees["source"]), "fee provenance missing")
    number(m["risk_budget"], "risk_budget", minimum=0)
    require(m["risk_budget"] <= 1, "risk budget above one")
    require(bool(m["valuation_version"]) and bool(m["benchmark_version"]), "valuation/benchmark version missing")
    fields(m["inputs"], ("scores", "initial_state", "plans", "pref"), "input sources")
    for name in ("scores", "initial_state", "plans", "pref"):
        require(name in m["inputs"], f"missing source: {name}")
        source = m["inputs"][name]
        fields(source, ("uri", "raw_sha256", "content_sha256", "coverage", "version"), name)
        require(bool(source["uri"]) and bool(source["coverage"]) and bool(source["version"]), f"empty source: {name}")
        sha(source["raw_sha256"])
        require(source["content_sha256"] == content_hash(snapshot[name]), f"{name} content drift", "PAIR_INVALID")
    require(isinstance(snapshot["plans"], list) and snapshot["plans"], "backtest rule plans missing")


def validate_intents(rows):
    seen = set()
    for row in rows:
        fields(row, INTENT_FIELDS, "intent")
        require(set(row) == set(INTENT_FIELDS), "unknown intent fields")
        require(row["arm_id"] in ARMS and row["side"] in ("BUY", "SELL"), "invalid arm/side")
        require(row["intent_id"] not in seen, "duplicate intent id", "PAIR_INVALID")
        seen.add(row["intent_id"])
        for key in ("intent_id", "reference_state_hash", "source_plan_hash"):
            sha(row[key])
        require(row["intent_id"] == content_hash({k: v for k, v in row.items() if k != "intent_id"}),
                "intent identity/content mismatch", "PAIR_INVALID")
        for key in ("instrument", "execution_symbol", "instance_id", "lot_id", "reason"):
            require(isinstance(row[key], str) and bool(row[key]), f"empty {key}")
        decision, available, effective, expires = (timestamp(row[k]) for k in
                                                   ("decision_at", "available_at", "effective_at", "expires_at"))
        require(decision <= available <= effective < expires, "intent clock violation", "PAIR_INVALID")
        require(timestamp(row["reference_price_at"]) <= decision, "future quantity reference price", "PAIR_INVALID")
        require(row["quantity_unit"] == "share" and row["quantity_conversion"] == "SNAPSHOT_FIXED",
                "unproven quantity unit", "SEMANTICS_BLOCKED")
        require(row["native_stop"] == "N/A", "stop rule injection")
        for key, value in ORDER_POLICY.items():
            require(row[key] == value, "order policy drift")
        q = number(row["original_target_quantity"], "quantity", minimum=0)
        require(q > 0 and number(row["reference_price"], "price", minimum=0) > 0, "nonpositive quantity/price")
        require(0 <= number(row["target_weight"], "weight") <= 1, "weight outside [0,1]")
        if row["side"] == "BUY":
            require(q % 100 == 0, "new buys must be whole 100-share lots")


def sort_intents(rows):
    return sorted(rows, key=lambda r: (r["arm_id"], r["decision_at"], 0 if r["side"] == "SELL" else 1,
                                       r["instrument"], r["intent_id"]))


def csv_bytes(rows, columns):
    """RFC4180 quoting, LF; each cell contains a JSON scalar to preserve types exactly."""
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(canonical_bytes(row[key]).decode("utf-8") for key in columns)
    return stream.getvalue().encode("utf-8")


def read_intents(path):
    raw = Path(path).read_bytes()
    require(not raw.startswith(b"\xef\xbb\xbf") and b"\0" not in raw, "BOM/NUL forbidden")
    reader = csv.reader(io.StringIO(raw.decode("utf-8"), newline=""))
    require(next(reader, None) == list(INTENT_FIELDS), "intent column drift")
    result = []
    for values in reader:
        require(len(values) == len(INTENT_FIELDS), "intent row width drift")
        result.append(dict(zip(INTENT_FIELDS, (load_json_bytes(v.encode("utf-8")) for v in values))))
    validate_intents(result)
    require(result == sort_intents(result), "noncanonical intent order", "PAIR_INVALID")
    return result
