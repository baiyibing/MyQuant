# -*- coding: utf-8 -*-
"""工单 4：同一 pred 上扫 topk×n_drop，不重训。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace

import host_env  # noqa: F401

import qlib
from qlib.config import REG_CN
from qlib.workflow import R

from custom_utils import TimerRecorder, install_features_probe, set_global_timer_recorder
from rebacktest_cost_tiers import load_pred, parse_segment, run_tiers

GRID = ((10, 3), (10, 5), (20, 3), (20, 5), (30, 3), (30, 5), (50, 3), (50, 5))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--recorder-id", default="8a061ea428e04bb3a199a485ade49d0e")
    p.add_argument("--exp-name", default="alpha158_cost_kdj_lgb")
    p.add_argument("--test", default="2026-01-01:2026-09-14")
    p.add_argument(
        "--out",
        default=str(
            Path(__file__).resolve().parents[1]
            / "docs/reviews/2026-09-15-qlib-perf-brainstorm/runs/2026-09-15-same-pred-width-grid.json"
        ),
    )
    args = p.parse_args()

    t_rec = TimerRecorder()
    set_global_timer_recorder(t_rec)
    qlib.init(
        provider_uri=os.path.expanduser("~/.qlib/qlib_data/my_data"),
        region=REG_CN,
        kernels=int(os.environ.get("QLIB_KERNELS", "1")),
        exp_manager={
            "class": "MLflowExpManager",
            "module_path": "qlib.workflow.expm",
            "kwargs": {"uri": "mlruns", "default_exp_name": "MyExperiment"},
        },
    )
    uninstall = install_features_probe(t_rec)
    rec, pred = load_pred(args.exp_name, args.recorder_id)
    score = pred["score"] if hasattr(pred, "columns") and "score" in getattr(pred, "columns", []) else pred
    window = parse_segment(args.test, "test")

    rows = []
    for topk, n_drop in GRID:
        print(f"=== grid topk={topk} n_drop={n_drop} ===", flush=True)
        ns = SimpleNamespace(
            exp_name=args.exp_name,
            recorder_id=rec.id,
            test_window=window,
            benchmark="SH000300",
            account=1e8,
            topk=topk,
            n_drop=n_drop,
            hold_thresh=1,
            no_limit_threshold=False,
            buy_state_filter=False,
            st_filter=False,
            age_filter=False,
            age_days=60,
            extra_exclude_file=None,
            st_daily_file=None,
            winner_ratio_file=None,
            pred_score=score,
        )
        summary = run_tiers(ns)
        rows.append(summary)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"recorder_id": rec.id, "test": list(window), "grid": rows}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"=== grid saved {out} ===", flush=True)
    try:
        uninstall()
        t_rec.print_summary()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
