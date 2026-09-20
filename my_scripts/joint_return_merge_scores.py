"""Merge explicit JSON control/common-universe/anti/label exports without prediction.

Run: python -m my_scripts.joint_return_merge_scores --help
"""
from __future__ import annotations

from pathlib import Path

from my_scripts.joint_return_contract import (
    CANDIDATE_RECORDER, RECORDER, SIDECAR_SHA256, ContractError, canonical_bytes,
    content_hash, date_string, fields, raw_hash, require,
)
from my_scripts.joint_return_freeze_snapshot import _Parser, _read_json
from my_scripts.joint_return_portfolio import score_days


def _index(rows, required, name):
    require(isinstance(rows, list) and rows, f"{name}: nonempty row array required")
    result = {}
    for row in rows:
        fields(row, ("date", "instrument", *required), name)
        date_string(row["date"])
        require(isinstance(row["instrument"], str) and bool(row["instrument"]),
                f"{name}: instrument required")
        key = row["date"], row["instrument"]
        require(key not in result, f"{name}: duplicate key {key}")
        require("candidate_score" not in row, "candidate score is forbidden")
        result[key] = row
    return result


def merge_scores(control, universe, anti, labels):
    """Use the declared common universe as the denominator; never an inner join.

    Control/anti/labels may cover more instruments. Every declared common key
    must exist in all three, including an explicit null for a missing label.
    """
    c = _index(control, ("score", "score_available_at", "source_version", "recorder_id"), "control")
    u = _index(universe, ("candidate_present", "recorder_id"), "common universe")
    a = _index(anti, ("anti_rank", "anti_available_at", "source_version", "source_sha256"), "anti")
    lab = _index(labels, ("label", "source_version"), "labels")
    require(all(r["recorder_id"] == RECORDER for r in c.values()), "control recorder mismatch")
    require(all(r["recorder_id"] == CANDIDATE_RECORDER and r["candidate_present"] is True
                and "score" not in r for r in u.values()), "common universe must be membership only")
    require(all(r["source_sha256"] == SIDECAR_SHA256 for r in a.values()), "sidecar source hash mismatch")
    for name, table in (("control", c), ("anti", a), ("labels", lab)):
        missing = u.keys() - table.keys()
        require(not missing, f"{name}: missing common keys {sorted(missing)[:10]}")
    rows = []
    for key in sorted(u):
        score, rank, label = c[key], a[key], lab[key]
        require(all(isinstance(r["source_version"], str) and r["source_version"]
                    for r in (score, rank, label)), "source version missing")
        require(CANDIDATE_RECORDER not in score["source_version"], "candidate score source is forbidden")
        rows.append({k: score[k] for k in ("date", "instrument", "score", "score_available_at",
                                         "source_version", "recorder_id")}
                    | {k: rank[k] for k in ("anti_rank", "anti_available_at")}
                    | {"candidate_present": True, "label": label["label"],
                       "anti_source_version": rank["source_version"],
                       "label_source_version": label["source_version"],
                       "anti_source_sha256": rank["source_sha256"]})
    grouped = score_days(rows)
    for day, daily in grouped.items():
        present = [r["label"] is not None for r in daily]
        require(all(present) or not any(present), f"{day}: partial label coverage needs source reconciliation")
    merged = [row for daily in grouped.values() for row in daily]
    audit = {"calendar": list(grouped), "common_rows": len(merged),
             "outside_common_keys": {name: [list(k) for k in sorted(table.keys() - u.keys())]
                                     for name, table in (("control", c), ("anti", a), ("labels", lab))}}
    return merged, audit


def write_bundle(output_dir, files):
    """Validate all bytes before creating an immutable directory; rollback our writes."""
    encoded = {name: canonical_bytes(value) + b"\n" for name, value in files.items()}
    output_dir = Path(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(exist_ok=False)
    created = []
    try:
        for name, data in encoded.items():
            path = output_dir / name
            with path.open("xb") as stream:
                created.append(path)
                stream.write(data)
            require(path.read_bytes() == data, "generated file readback drift", "PAIR_INVALID")
    except BaseException:
        for path in created:
            path.unlink()
        output_dir.rmdir()
        raise


def main(argv=None):
    parser = _Parser(description=__doc__)
    for name in ("control", "universe", "anti", "labels"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    try:
        args = parser.parse_args(argv)
        values, sources = {}, {}
        for name in ("control", "universe", "anti", "labels"):
            values[name], sources[name] = _read_json(getattr(args, name).resolve())
        rows, audit = merge_scores(**values)
        manifest = {"status": "SCORES_MERGED", "input_status": "INPUT_BLOCKED",
                    "execution_status": "NOT_RUN", "inputs": sources, "coverage": audit,
                    "scores": {"uri": str((args.output_dir / "scores.json").resolve()),
                               "content_sha256": content_hash(rows),
                               "raw_sha256": raw_hash(canonical_bytes(rows) + b"\n")},
                    "verification_scope": "explicit JSON exports only; upstream provenance/PIT require host verification"}
        write_bundle(args.output_dir, {"scores.json": rows, "merge-manifest.json": manifest})
    except (ContractError, OSError, TypeError, ValueError, KeyError) as exc:
        print(canonical_bytes({"status": getattr(exc, "status", "OUTPUT_BLOCKED" if isinstance(exc, OSError)
                                                else "INPUT_BLOCKED"), "detail": str(exc)}).decode())
        return 2
    print(canonical_bytes(manifest).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
