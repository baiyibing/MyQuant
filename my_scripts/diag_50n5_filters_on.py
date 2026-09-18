# -*- coding: utf-8 -*-
"""同 pred 50/5，打开买入状态 + ST + 上市满 60 日。不重训，不覆盖原分析包。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import host_env  # noqa: F401

import qlib
from qlib.config import REG_CN

from data_root import resolve_source_parquet, resolve_st_daily
from analysis_export import write_analysis_bundle
from custom_utils import TimerRecorder, install_features_probe, set_global_timer_recorder
from rebacktest_cost_tiers import (
    COST_TIERS,
    EXECUTOR_CONFIG,
    build_exchange_kwargs,
    build_strategy_config,
    equal_weight_daily_returns,
    load_pred,
    metrics,
    parse_segment,
)
from qlib.contrib.evaluate import backtest_daily

REC = "8a061ea428e04bb3a199a485ade49d0e"
EXP = "alpha158_cost_kdj_lgb"
TEST = "2026-01-01:2026-09-14"
ST_DAILY = str(resolve_st_daily())
WINNER = str(resolve_source_parquet("cyq_winner_ratio/cyq_winner_ratio_daily_2026.parquet"))
OUT_JSON = (
    Path(__file__).resolve().parents[1]
    / "docs/reviews/2026-09-15-qlib-perf-brainstorm/runs/2026-09-15-50n5-filters-on.json"
)
OUT_ANALYSIS = (
    Path(__file__).resolve().parents[1]
    / "exports/analysis/8a061ea4_50n5_filters_on"
)


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
    rec, pred = load_pred(EXP, REC)
    score = pred["score"] if hasattr(pred, "columns") and "score" in getattr(pred, "columns", []) else pred
    window = parse_segment(TEST, "test")
    ns = SimpleNamespace(
        exp_name=EXP,
        recorder_id=rec.id,
        test_window=window,
        benchmark="SH000300",
        account=1e8,
        topk=50,
        n_drop=5,
        hold_thresh=1,
        no_limit_threshold=False,
        buy_state_filter=True,
        st_filter=True,
        age_filter=True,
        age_days=60,
        extra_exclude_file=None,
        st_daily_file=ST_DAILY,
        winner_ratio_file=WINNER,
        pred_score=score,
    )
    print("[filters-on] ST/age/buy-state ON; same pred; no overwrite of 8a061ea4 analysis", flush=True)
    with t_rec.timer("equal_weight"):
        ew = equal_weight_daily_returns(*window)
    with t_rec.timer("strategy_config"):
        strategy = build_strategy_config(ns)
    summary = {
        "recorder_id": rec.id,
        "pred_source": "same pred.pkl, no retrain",
        "test": list(window),
        "topk": 50,
        "n_drop": 5,
        "buy_state_filter": True,
        "st_filter": True,
        "st_daily_file": ST_DAILY,
        "age_filter": "60d",
        "winner_ratio_file": WINNER,
        "analysis_dir": str(OUT_ANALYSIS),
        "tiers": {},
    }
    qlib_report = None
    qlib_positions = None
    for tier, costs in COST_TIERS.items():
        print(f"[filters-on] tier={tier} {costs}", flush=True)
        with t_rec.timer(f"backtest.{tier}"):
            report, positions = backtest_daily(
                start_time=window[0],
                end_time=window[1],
                strategy=strategy,
                executor=EXECUTOR_CONFIG,
                account=1e8,
                benchmark="SH000300",
                exchange_kwargs=build_exchange_kwargs(costs, no_limit_threshold=False),
            )
        net = report["return"] - report["cost"]
        ew_aligned = ew.reindex(report.index)
        summary["tiers"][tier] = {
            "abs_net_after_cost": metrics(net),
            "abs_gross_before_cost": metrics(report["return"]),
            "excess_vs_bench_net": metrics(net - report["bench"]),
            "excess_vs_equal_weight_net": metrics(net - ew_aligned),
            "annualized_cost_drag": float(report["cost"].mean() * 252),
            "total_cost_rate": float(report["cost"].sum()),
            "total_turnover": float(report["turnover"].sum()),
            "trading_days": int(len(report)),
        }
        print(json.dumps(summary["tiers"][tier], indent=2, ensure_ascii=False), flush=True)
        if tier == "qlib_default":
            qlib_report, qlib_positions = report, positions

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[filters-on] json {OUT_JSON}", flush=True)

    OUT_ANALYSIS.mkdir(parents=True, exist_ok=True)
    with t_rec.timer("export_analysis"):
        write_analysis_bundle(
            positions=qlib_positions,
            out_dir=OUT_ANALYSIS,
            open_rate=COST_TIERS["qlib_default"]["open_cost"],
            close_rate=COST_TIERS["qlib_default"]["close_cost"],
            account=1e8,
            pred=pred,
            report=qlib_report,
            topk=50,
            use_qlib_close=True,
            extra_summary={
                "source": "replay_filters_on",
                "recorder_id": rec.id,
                "buy_state_filter": True,
                "st_filter": True,
                "age_filter": True,
            },
        )
    print(f"[filters-on] analysis {OUT_ANALYSIS}", flush=True)
    try:
        uninstall()
        t_rec.print_summary()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
