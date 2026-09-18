# -*- coding: utf-8 -*-
"""T3/T4: 2024 OOS 10/3 全关 / ST+年龄 / +15% on current ruler.

Reads a finished recorder's pred.pkl. Does not write 8a061ea4 / 55c5bf77.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace

import host_env  # noqa: F401
import qlib
from qlib.config import REG_CN
from qlib.contrib.evaluate import backtest_daily

from data_root import resolve_st_daily
from analysis_export import write_analysis_bundle
from rebacktest_cost_tiers import (
    COST_TIERS,
    EXECUTOR_CONFIG,
    build_exchange_kwargs,
    build_strategy_config,
    load_pred,
    metrics,
)

ST = str(resolve_st_daily())
ROOT = Path(__file__).resolve().parents[1]
START, END = "2024-01-02", "2024-12-31"
GATES = (
    {"tag": "nofilter", "st": False, "age": False, "ret15": False},
    {"tag": "st_age", "st": True, "age": True, "ret15": False},
    {"tag": "stag15", "st": True, "age": True, "ret15": True},
)


def _series(pred):
    if hasattr(pred, "columns") and "score" in getattr(pred, "columns", []):
        return pred["score"]
    return pred if hasattr(pred, "iloc") and getattr(pred, "ndim", 2) == 1 else pred.iloc[:, 0]


def run_one(exp_name: str, rec_id: str, gate: dict, score, out_root: Path) -> dict:
    cid = f"2024_10n3_{gate['tag']}"
    ns = SimpleNamespace(
        exp_name=exp_name,
        recorder_id=rec_id,
        test_window=(START, END),
        benchmark="SH000300",
        account=1e8,
        topk=10,
        n_drop=3,
        hold_thresh=1,
        no_limit_threshold=False,
        buy_state_filter=False,
        st_filter=gate["st"],
        age_filter=gate["age"],
        age_days=60,
        extra_exclude_file=None,
        st_daily_file=ST if gate["st"] else None,
        winner_ratio_file=None,
        return_threshold_filter=gate["ret15"],
        pred_score=score,
    )
    print(f"[run] {cid}", flush=True)
    report, positions = backtest_daily(
        start_time=START,
        end_time=END,
        strategy=build_strategy_config(ns),
        executor=EXECUTOR_CONFIG,
        account=1e8,
        benchmark="SH000300",
        exchange_kwargs=build_exchange_kwargs(COST_TIERS["qlib_default"]),
    )
    net = report["return"] - report["cost"]
    exc = metrics(net - report["bench"])
    abs_m = metrics(net)
    nav_end = float(report["account"].iloc[-1])
    row = {
        "id": cid,
        "year": 2024,
        "topk": 10,
        "n_drop": 3,
        "st_filter": gate["st"],
        "age_filter": gate["age"],
        "return_threshold_filter": gate["ret15"],
        "nav_end": nav_end,
        "excess_ann": exc["annualized_return"],
        "excess_ir": exc["information_ratio"],
        "excess_mdd": exc["max_drawdown"],
        "abs_ann": abs_m["annualized_return"],
        "abs_mdd": abs_m["max_drawdown"],
        "interval_ret": nav_end / 1e8 - 1.0,
        "pred_recorder_id": rec_id,
        "exp_name": exp_name,
    }
    print(json.dumps({k: row[k] for k in ("id", "nav_end", "excess_ann", "interval_ret")}, ensure_ascii=False), flush=True)
    out_dir = out_root / cid
    out_dir.mkdir(parents=True, exist_ok=True)
    write_analysis_bundle(
        positions=positions,
        out_dir=out_dir,
        open_rate=0.0005,
        close_rate=0.0015,
        account=1e8,
        pred=score.to_frame("score"),
        report=report,
        topk=10,
        use_qlib_close=True,
        extra_summary={"source": "replay_2024_oos_gates", "pred_recorder_id": rec_id, **{k: gate[k] for k in ("st", "age", "ret15")}},
    )
    (out_dir / "combo_summary.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    return row


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--exp-name", required=True)
    p.add_argument("--recorder-id", default=None)
    p.add_argument("--out-name", required=True, help="exports/analysis/<out-name>/")
    args = p.parse_args()
    os.environ.pop("OSKH_DATA_ROOT", None)
    qlib.init(
        provider_uri=os.path.expanduser("~/.qlib/qlib_data/my_data"),
        region=REG_CN,
        kernels=1,
        exp_manager={
            "class": "MLflowExpManager",
            "module_path": "qlib.workflow.expm",
            "kwargs": {"uri": "mlruns", "default_exp_name": "MyExperiment"},
        },
    )
    rec, pred = load_pred(args.exp_name, args.recorder_id)
    score = _series(pred)
    out_root = ROOT / "exports" / "analysis" / args.out_name
    rows = [run_one(args.exp_name, rec.id, gate, score, out_root) for gate in GATES]
    board = {
        "ruler": "E ST PIT + qlib close + 5/15bp + PortAna",
        "exp_name": args.exp_name,
        "pred_recorder_id": rec.id,
        "rows": rows,
    }
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "leaderboard.json").write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(board, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
