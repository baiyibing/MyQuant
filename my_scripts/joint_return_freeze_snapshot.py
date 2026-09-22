"""Assemble explicit local JSON files into a frozen snapshot; no data resolver.

The caller supplies metadata with predeclared source hashes, coverage and versions.
Assembly verifies those files, not upstream provenance or P-REF/portfolio results.
Run from the repository root: python -m my_scripts.joint_return_freeze_snapshot --help
"""
from __future__ import annotations

import argparse
from pathlib import Path

from my_scripts.joint_return_contract import (
    validate_mlag_window,
    CANDIDATE_RECORDER, RECORDER, SCHEMA_VERSION, ContractError, canonical_bytes,
    content_hash, date_string, fields, load_json_bytes, load_snapshot, raw_hash,
    require, sha, timestamp, validate_plan_source, validate_snapshot,
    input_sections, scores_mode, portfolio_arms, scope_status,
)
from my_scripts.joint_return_portfolio import score_days, validate_state

SECTIONS = ("scores", "initial_state", "plans", "pref")
PLAN_FIELDS = (
    "date", "arm_id", "source", "pre_state_hash", "decision_at", "available_at",
    "effective_at", "expires_at", "marks", "mark_at", "sells", "buys",
    "buy_candidates", "corporate_actions",
)
QUANTITY_FIELDS = (
    "instrument", "execution_symbol", "instance_id", "lot_id", "target_weight",
    "original_target_quantity", "reference_price", "reference_price_at",
    "quantity_unit", "quantity_conversion",
)


def _read_json(path):
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ContractError("INPUT_BLOCKED", f"declared input unavailable: {path}") from exc
    value = load_json_bytes(raw)
    return value, {"uri": str(path), "raw_sha256": raw_hash(raw),
                   "content_sha256": content_hash(value)}


def _validate_sections(snapshot):
    """Check source/shape at the boundary; portfolio retains numerical/causal gates."""
    metadata = snapshot["metadata"]
    arms = portfolio_arms(metadata)
    scores_source = metadata["inputs"]["scores"]
    require(scores_source.get("recorder_id", metadata["pred_recorder_id"]) == RECORDER,
            "scores must come from the control recorder, not candidate scores")
    require(CANDIDATE_RECORDER not in str(scores_source["version"]),
            "candidate score source is forbidden")
    grouped = score_days(snapshot["scores"], mode=scores_mode(metadata))
    for row in snapshot["scores"]:
        require(row.get("recorder_id", RECORDER) == RECORDER
                and CANDIDATE_RECORDER not in str(row["source_version"]),
                "candidate score source is forbidden")
    require(set(metadata["calendar"]) <= grouped.keys(), "portfolio calendar missing scores")
    validate_state(snapshot["initial_state"], topk=metadata["strategy"]["topk"])
    seen = set()
    for plan in snapshot["plans"]:
        fields(plan, PLAN_FIELDS, "frozen plan")
        validate_plan_source(plan, metadata["strategy"])
        date_string(plan["date"])
        require(plan["arm_id"] in arms, "unknown plan arm / requested arm INPUT_BLOCKED for scores_mode")
        key = (plan["date"], plan["arm_id"])
        require(key not in seen, "duplicate daily arm plan")
        seen.add(key)
        sha(plan["pre_state_hash"])
        decision, available, effective, expires = (
            timestamp(plan[k]) for k in ("decision_at", "available_at", "effective_at", "expires_at"))
        require(decision.date().isoformat() == plan["date"], "decision date mismatch")
        require(timestamp(plan["mark_at"]) <= decision <= available <= effective < expires,
                "plan clock violation", "PAIR_INVALID")
        validate_mlag_window(plan, metadata)
        require(isinstance(plan["marks"], dict), "plan marks must be an object")
        require(plan["corporate_actions"] == [],
                "company-action mapping not implemented in MQ R1", "SEMANTICS_BLOCKED")
        for name in ("sells", "buys", "buy_candidates"):
            require(isinstance(plan[name], list), f"plan {name} must be a list")
        require(all(isinstance(inst, str) and inst for inst in plan["buys"]),
                "original buys must be instrument names")
        for name, flag, reason in (("sells", "approved", "approval_reason"),
                                   ("buy_candidates", "eligible", "eligibility_reason")):
            for order in plan[name]:
                fields(order, (*QUANTITY_FIELDS, flag, reason), f"frozen {name} quantity")
                require(type(order[flag]) is bool and bool(order[reason]),
                        f"explicit {flag}/{reason} required")
    require(seen == {(day, arm) for day in metadata["calendar"] for arm in arms},
            "missing/extra arm-days; explicit empty plans also required")
    if scores_mode(metadata) == "control_only":
        return
    pref = snapshot["pref"]
    fields(pref, ("calendar", "windows", "expected", "label", "bootstrap"), "pref")
    fields(pref["expected"], ("windows",), "P-REF expected")
    require(pref["calendar"] == list(grouped), "P-REF missing/extra calendar days")
    # Do not run P-REF with synthetic=True to get a frozen package past its real gate.
    # The original expected hash, windows, numbers and state recursion are checked
    # by joint_return_portfolio with kind=frozen, unchanged by this assembler.


def freeze_snapshot(*, scores, initial_state, plans, metadata, output, pref=None):
    metadata_path = Path(metadata).resolve()
    m, metadata_source = _read_json(metadata_path)
    sections = input_sections(m)
    require(pref is not None if "pref" in sections else pref is None,
            "full mode: --pref required; control_only must omit --pref (P-REF-anti NOT_RUN)")
    paths = {name: Path(path).resolve() for name, path in (
        ("scores", scores), ("initial_state", initial_state), ("plans", plans), ("pref", pref)) if name in sections}
    output = Path(output).absolute()
    require(output.resolve() not in {*paths.values(), metadata_path},
            "output must not replace a declared input")
    fields(m, ("inputs",), "metadata")
    fields(m["inputs"], sections, "input sources")
    require(set(m["inputs"]) == set(sections), "declared input sections must match scores_mode")
    snapshot = {"schema_version": SCHEMA_VERSION, "kind": "frozen", "metadata": m}
    sources = {}
    for name, path in paths.items():
        declared = m["inputs"][name]
        fields(declared, ("uri", "raw_sha256", "content_sha256", "coverage", "version"), name)
        # URI is an assertion about the CLI path, never a path to resolve or read.
        require(declared["uri"] == str(path), f"{name} uri differs from explicit path", "PAIR_INVALID")
        sha(declared["raw_sha256"])
        sha(declared["content_sha256"])
        value, observed = _read_json(path)
        for key in ("raw_sha256", "content_sha256"):
            require(declared[key] == observed[key], f"{name} {key} drift", "PAIR_INVALID")
        snapshot[name] = value
        sources[name] = {**declared, **observed, "raw_verified": True}
    validate_snapshot(snapshot)  # includes all fixed contract metadata, with no defaults
    _validate_sections(snapshot)
    data = canonical_bytes(snapshot) + b"\n"
    # No output is created until every input has passed. Never overwrite an old
    # snapshot; a failed write/readback removes only the file created by this call.
    output.parent.mkdir(parents=True, exist_ok=True)
    stream = output.open("xb")
    try:
        with stream:
            stream.write(data)
        loaded, source = load_snapshot(output)
        require(loaded == snapshot and source["raw_sha256"] == raw_hash(data),
                "snapshot readback drift", "PAIR_INVALID")
    except BaseException:
        output.unlink()
        raise
    return {
        "schema_version": SCHEMA_VERSION, "kind": "frozen",
        "status": "FROZEN_SNAPSHOT_ASSEMBLED", "input_status": "INPUT_BLOCKED",
        "execution_status": "NOT_RUN", "return_status": "待实测",
        "scores_mode": scores_mode(m), "scope_status": scope_status(m, "FROZEN_SNAPSHOT_ASSEMBLED"),
        "snapshot": source, "metadata_source": metadata_source, "inputs": sources,
        "input_raw_hashes_verified": True,
        "verification_scope": "only the explicitly supplied JSON section files",
        "portfolio_status": "NOT_RUN",
        "real_input_blockers": [
            "upstream control provenance and PIT/coverage require host verification",
            "backtest rule provenance and reference state recursion require portfolio/host verification",
            *([] if scores_mode(m) == "control_only" else
               ["common universe/sidecar/labels provenance and frozen P-REF checks require verification"]),
        ],
    }


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ContractError("INPUT_BLOCKED", message)


def main(argv=None):
    parser = _Parser(description=__doc__)
    for name in SECTIONS:
        parser.add_argument(f"--{name.replace('_', '-')}", required=name != "pref", type=Path,
                            help=f"explicit {name} JSON file; no lookup or fallback")
    parser.add_argument("--metadata", required=True, type=Path,
                        help="full metadata JSON with expected source uri/raw/content hashes")
    parser.add_argument("--output", required=True, type=Path, help="new snapshot JSON path; never overwritten")
    try:
        args = parser.parse_args(argv)
        manifest = freeze_snapshot(**vars(args))
    except (ContractError, OSError, TypeError, ValueError, KeyError) as exc:
        status = getattr(exc, "status", "OUTPUT_BLOCKED" if isinstance(exc, OSError) else "INPUT_BLOCKED")
        print(canonical_bytes({"status": status, "detail": str(exc)}).decode("utf-8"))
        return 2
    print(canonical_bytes(manifest).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
