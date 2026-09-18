# -*- coding: utf-8 -*-
"""2025 valid-year replay: 8a061ea4 50/5 ST+age vs ST+age+15% on current ruler.

Uses the existing 2025 complementary pred CSV (no retrain). Does not write
8a061ea4 / 55c5bf77 recorders.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import host_env  # noqa: F401
import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.contrib.evaluate import backtest_daily

from analysis_export import write_analysis_bundle
from rebacktest_cost_tiers import (
    COST_TIERS,
    EXECUTOR_CONFIG,
    build_exchange_kwargs,
    build_strategy_config,
    metrics,
)

ST = r"E:\stock_data\vendor_wind_st_status\st_daily.parquet"
ROOT = Path(__file__).resolve().parents[1]
PRED_CSV = ROOT / "my_scripts" / "预测结果_8a061ea4_2025valid.csv"
OUT_ROOT = ROOT / "exports" / "analysis" / "replay_2025_st_age_vs_15"
REC = "8a061ea428e04bb3a199a485ade49d0e"
START, END = "2025-01-01", "2025-12-31"

COMBOS = (
    {
        "id": "lgb_8a061ea4_50n5_st_age",
        "label": "8a061ea4 50/5 ST+年龄",
        "ret15": False,
    },
    {
        "id": "lgb_8a061ea4_50n5_stag15",
        "label": "8a061ea4 50/5 ST+年龄+15%",
        "ret15": True,
    },
)


def load_score() -> pd.Series:
    frame = pd.read_csv(PRED_CSV, dtype={"instrument": str})
    frame["datetime"] = pd.to_datetime(frame["datetime"]).dt.normalize()
    score = frame.set_index(["datetime", "instrument"])["score"].sort_index()
    print(f"[pred] {PRED_CSV.name} rows={len(score)} {score.index.get_level_values(0).min().date()}..{score.index.get_level_values(0).max().date()}", flush=True)
    return score


def run_one(combo: dict, score: pd.Series) -> dict:
    ns = SimpleNamespace(
        exp_name="alpha158_cost_kdj_lgb",
        recorder_id=REC,
        test_window=(START, END),
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
        return_threshold_filter=combo["ret15"],
        pred_score=score,
    )
    print(f"[run] {combo['id']} 15%={combo['ret15']}", flush=True)
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
        "id": combo["id"],
        "label": combo["label"],
        "pred_csv": str(PRED_CSV),
        "pred": REC,
        "year": 2025,
        "topk": 50,
        "n_drop": 5,
        "st_filter": True,
        "age_filter": True,
        "return_threshold_filter": combo["ret15"],
        "nav_end": nav_end,
        "excess_ann": exc["annualized_return"],
        "excess_ir": exc["information_ratio"],
        "excess_mdd": exc["max_drawdown"],
        "abs_ann": abs_m["annualized_return"],
        "abs_mdd": abs_m["max_drawdown"],
        "interval_ret": nav_end / 1e8 - 1.0,
    }
    print(json.dumps({k: row[k] for k in ("id", "nav_end", "excess_ann", "abs_ann", "interval_ret")}, ensure_ascii=False), flush=True)
    out_dir = OUT_ROOT / combo["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    write_analysis_bundle(
        positions=positions,
        out_dir=out_dir,
        open_rate=0.0005,
        close_rate=0.0015,
        account=1e8,
        pred=score.to_frame("score"),
        report=report,
        topk=50,
        use_qlib_close=True,
        extra_summary={
            "source": "replay_2025_st_age_vs_15",
            "pred_recorder_id": REC,
            "st_filter": True,
            "age_filter": True,
            "return_threshold_filter": combo["ret15"],
        },
    )
    (out_dir / "combo_summary.json").write_text(
        json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return row


def main() -> int:
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
    score = load_score()
    rows = [run_one(combo, score) for combo in COMBOS]
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    board = {"ruler": "E ST PIT + qlib close + 5/15bp + PortAna", "year": 2025, "rows": rows}
    (OUT_ROOT / "leaderboard.json").write_text(
        json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(board, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
