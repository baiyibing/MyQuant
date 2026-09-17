# -*- coding: utf-8 -*-
"""全宇宙 pred：买入挡 ST+年龄+15%。不重训。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import host_env  # noqa: F401
from qlib.config import REG_CN
from qlib.contrib.evaluate import backtest_daily
import qlib

from analysis_export import write_analysis_bundle
from rebacktest_cost_tiers import (
    COST_TIERS,
    EXECUTOR_CONFIG,
    build_exchange_kwargs,
    build_strategy_config,
    load_pred,
    metrics,
)

EXP = os.environ.get("REPLAY_EXP", "alpha158_cost_kdj_cat_all")
REC = os.environ.get("REPLAY_REC", "4233a65a0ae346698fc6822905950469")
ST = r"E:\stock_data\vendor_wind_st_status\st_daily.parquet"
_out = os.environ.get("REPLAY_OUT")
OUT = Path(_out) if _out else Path(__file__).resolve().parents[1] / "exports/analysis/4233a65a_replay_buy_stag15"


def main() -> int:
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
    rec, pred = load_pred(EXP, REC)
    score = pred["score"] if hasattr(pred, "columns") and "score" in getattr(pred, "columns", []) else pred
    ns = SimpleNamespace(
        exp_name=EXP,
        recorder_id=rec.id,
        test_window=("2026-01-01", "2026-09-14"),
        benchmark="SH000300",
        account=1e8,
        topk=50,
        n_drop=5,
        hold_thresh=1,
        no_limit_threshold=False,
        buy_state_filter=False,
        st_filter=True,
        age_filter=True,
        age_days=60,
        extra_exclude_file=None,
        st_daily_file=ST,
        winner_ratio_file=None,
        return_threshold_filter=True,
        pred_score=score,
    )
    print(f"[run] pred={rec.id} rows={len(score)} st=ON age=ON return_threshold=ON", flush=True)
    strategy = build_strategy_config(ns)
    report, positions = backtest_daily(
        start_time="2026-01-01",
        end_time="2026-09-14",
        strategy=strategy,
        executor=EXECUTOR_CONFIG,
        account=1e8,
        benchmark="SH000300",
        exchange_kwargs=build_exchange_kwargs(COST_TIERS["qlib_default"], no_limit_threshold=False),
    )
    net = report["return"] - report["cost"]
    exc = metrics(net - report["bench"])
    abs_m = metrics(net)
    nav_end = float(report["account"].iloc[-1])
    out = {
        "model": "cat",
        "pred": rec.id,
        "nav_end": nav_end,
        "excess_ann": exc["annualized_return"],
        "excess_ir": exc["information_ratio"],
        "excess_mdd": exc["max_drawdown"],
        "abs_ann": abs_m["annualized_return"],
        "abs_mdd": abs_m["max_drawdown"],
    }
    print(json.dumps(out, ensure_ascii=False), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    write_analysis_bundle(
        positions=positions,
        out_dir=OUT,
        open_rate=0.0005,
        close_rate=0.0015,
        account=1e8,
        pred=pred,
        report=report,
        topk=50,
        use_qlib_close=True,
        extra_summary={
            "source": "replay_same_pred_buy_st_age_15",
            "pred_recorder_id": rec.id,
            "st_filter": True,
            "age_filter": True,
            "return_threshold_filter": True,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
