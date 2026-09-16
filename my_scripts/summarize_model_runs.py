"""Roll train manifests into a model-sweep comparison table.

Reads ``manifests/train_*.json`` (and optional analysis ``timing.json``).
Does not retrain. Historical manifests without PortAna cells still show timings.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from run_manifest import load_manifest  # noqa: E402

REPO_ROOT = _SCRIPT_DIR.parent


def _node_seconds(man: dict, name: str) -> float | None:
    timings = man.get("timings") or {}
    for row in timings.get("rollup") or []:
        if row.get("name") == name:
            return float(row.get("seconds") or 0)
    total = 0.0
    hit = False
    for node in timings.get("nodes") or []:
        if node.get("name") == name:
            total += float(node.get("seconds") or 0)
            hit = True
    return total if hit else None


def _prepare_seconds(man: dict) -> float | None:
    timings = man.get("timings") or {}
    total = 0.0
    hit = False
    for node in timings.get("nodes") or []:
        if str(node.get("name") or "").startswith("dataset.prepare."):
            total += float(node.get("seconds") or 0)
            hit = True
    return total if hit else None


def collect_rows(
    manifests_dir: Path,
    *,
    models: set[str] | None = None,
    topk: int | None = None,
) -> list[dict]:
    rows = []
    for path in sorted(manifests_dir.glob("train_*.json")):
        try:
            man = load_manifest(path)
        except Exception:
            continue
        cfg = man.get("config") or {}
        data = man.get("data") or {}
        timings = man.get("timings") or {}
        model = cfg.get("model") or "lgb"
        if models is not None and model not in models:
            continue
        if topk is not None and cfg.get("topk") != topk:
            continue
        rows.append(
            {
                "manifest": path.name,
                "created_utc": man.get("created_utc"),
                "model": model,
                "topk": cfg.get("topk"),
                "n_drop": cfg.get("n_drop"),
                "test": (cfg.get("segments") or {}).get("test"),
                "recorder_id": (cfg.get("recorder_id") or "")[:8],
                "handler_cache_hit": data.get("handler_cache_hit"),
                "excess_ann_with_cost": data.get("excess_ann_with_cost"),
                "excess_ir_with_cost": data.get("excess_ir_with_cost"),
                "excess_mdd_with_cost": data.get("excess_mdd_with_cost"),
                "handler_init_s": _node_seconds(man, "handler_init"),
                "model_fit_s": _node_seconds(man, "model_fit"),
                "prepare_s": _prepare_seconds(man),
                "predict_s": _node_seconds(man, "SignalRecord.generate"),
                "portana_s": _node_seconds(man, "PortAnaRecord.generate"),
                "total_s": timings.get("total_seconds"),
            }
        )
    return rows


def format_table(rows: list[dict]) -> str:
    headers = (
        "model",
        "topk",
        "hit",
        "excess",
        "IR",
        "fit_s",
        "portana_s",
        "total_s",
        "recorder",
    )
    lines = [" | ".join(headers), " | ".join("---" for _ in headers)]
    for row in rows:
        hit = row.get("handler_cache_hit")
        hit_s = "HIT" if hit is True else ("MISS" if hit is False else "-")
        excess = row.get("excess_ann_with_cost")
        ir = row.get("excess_ir_with_cost")
        lines.append(
            " | ".join(
                [
                    str(row.get("model") or ""),
                    f"{row.get('topk')}/{row.get('n_drop')}",
                    hit_s,
                    f"{excess:+.1%}" if isinstance(excess, (int, float)) else "-",
                    f"{ir:.2f}" if isinstance(ir, (int, float)) else "-",
                    f"{row.get('model_fit_s'):.1f}" if row.get("model_fit_s") is not None else "-",
                    f"{row.get('portana_s'):.1f}" if row.get("portana_s") is not None else "-",
                    f"{row.get('total_s'):.1f}" if row.get("total_s") is not None else "-",
                    str(row.get("recorder_id") or ""),
                ]
            )
        )
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Summarize train manifests for model sweeps")
    parser.add_argument(
        "--manifests-dir",
        default=str(REPO_ROOT / "manifests"),
        help="Directory of train_*.json",
    )
    parser.add_argument("--json-out", default=None, help="Optional JSON dump path")
    parser.add_argument("--models", default=None, help="Comma-separated model names to keep")
    parser.add_argument("--topk", type=int, default=None, help="Keep only this topk (e.g. 50)")
    args = parser.parse_args(argv)
    model_set = {m.strip() for m in str(args.models).split(",") if m.strip()} if args.models else None
    rows = collect_rows(Path(args.manifests_dir), models=model_set, topk=args.topk)
    print(format_table(rows))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"=== wrote {args.json_out} ({len(rows)} rows) ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
