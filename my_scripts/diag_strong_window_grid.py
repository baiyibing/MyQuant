# -*- coding: utf-8 -*-
"""工单 5 能做的部分：同 pred 强窗 2026-04～08，对照 10/3、20/3、50/5。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import host_env  # noqa: F401

import qlib
from qlib.config import REG_CN

from custom_utils import TimerRecorder, install_features_probe, set_global_timer_recorder
from rebacktest_cost_tiers import load_pred, parse_segment, run_tiers

GRID = ((10, 3), (20, 3), (50, 5))
TEST = "2026-04-01:2026-08-31"
REC = "8a061ea428e04bb3a199a485ade49d0e"


def main() -> int:
    t_rec = TimerRecorder()
    set_global_timer_recorder(t_rec)
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
    uninstall = install_features_probe(t_rec)
    rec, pred = load_pred("alpha158_cost_kdj_lgb", REC)
    score = pred["score"] if hasattr(pred, "columns") and "score" in getattr(pred, "columns", []) else pred
    window = parse_segment(TEST, "test")
    rows = []
    for topk, n_drop in GRID:
        print(f"=== strong {TEST} topk={topk} n_drop={n_drop} ===", flush=True)
        ns = SimpleNamespace(
            exp_name="alpha158_cost_kdj_lgb",
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
        rows.append(run_tiers(ns))
    out = (
        Path(__file__).resolve().parents[1]
        / "docs/reviews/2026-09-15-qlib-perf-brainstorm/runs/2026-09-15-strong-window-202604-202608.json"
    )
    out.write_text(
        json.dumps({"recorder_id": rec.id, "test": list(window), "note": "2025 weak window skipped: pred has no 2025", "grid": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"=== strong window saved {out} ===", flush=True)
    try:
        uninstall()
        t_rec.print_summary()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
