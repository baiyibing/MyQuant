# -*- coding: utf-8 -*-
"""T1: 10/3 全关 / ST+年龄 / ST+年龄+15% on 2025 and 2026, current ruler.

Same 8a061ea4 scores. No retrain. Does not write 8a061ea4 / 55c5bf77 recorders.
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
    load_pred,
    metrics,
)

ST = r"E:\stock_data\vendor_wind_st_status\st_daily.parquet"
ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "exports" / "analysis" / "replay_10n3_two_year"
REC = "8a061ea428e04bb3a199a485ade49d0e"
PRED_2025 = ROOT / "my_scripts" / "预测结果_8a061ea4_2025valid.csv"

GATES = (
    {"tag": "nofilter", "st": False, "age": False, "ret15": False},
    {"tag": "st_age", "st": True, "age": True, "ret15": False},
    {"tag": "stag15", "st": True, "age": True, "ret15": True},
)
YEARS = (
    {"year": 2026, "start": "2026-01-01", "end": "2026-09-14", "src": "recorder"},
    {"year": 2025, "start": "2025-01-01", "end": "2025-12-31", "src": "csv"},
)


def _series(pred) -> pd.Series:
    if hasattr(pred, "columns") and "score" in getattr(pred, "columns", []):
        return pred["score"]
    if isinstance(pred, pd.Series):
        return pred
    return pred.iloc[:, 0]


def load_scores() -> dict[int, pd.Series]:
    rec, pred = load_pred("alpha158_cost_kdj_lgb", REC)
    y2026 = _series(pred)
    frame = pd.read_csv(PRED_2025, dtype={"instrument": str})
    frame["datetime"] = pd.to_datetime(frame["datetime"]).dt.normalize()
    y2025 = frame.set_index(["datetime", "instrument"])["score"].sort_index()
    print(f"[pred] recorder={rec.id} 2026 rows={len(y2026)} 2025 rows={len(y2025)}", flush=True)
    return {2026: y2026, 2025: y2025}


def run_one(year: dict, gate: dict, score: pd.Series) -> dict:
    cid = f"{year['year']}_10n3_{gate['tag']}"
    ns = SimpleNamespace(
        exp_name="alpha158_cost_kdj_lgb",
        recorder_id=REC,
        test_window=(year["start"], year["end"]),
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
        start_time=year["start"],
        end_time=year["end"],
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
        "year": year["year"],
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
    }
    print(json.dumps({k: row[k] for k in ("id", "nav_end", "excess_ann", "interval_ret")}, ensure_ascii=False), flush=True)
    out_dir = OUT_ROOT / cid
    out_dir.mkdir(parents=True, exist_ok=True)
    write_analysis_bundle(
        positions=positions,
        out_dir=out_dir,
        open_rate=0.0005,
        close_rate=0.0015,
        account=1e8,
        pred=score.to_frame("score") if isinstance(score, pd.Series) else score,
        report=report,
        topk=10,
        use_qlib_close=True,
        extra_summary={"source": "replay_10n3_two_year", "pred_recorder_id": REC, **{k: gate[k] for k in ("st", "age", "ret15")}},
    )
    (out_dir / "combo_summary.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
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
    scores = load_scores()
    rows = []
    for year in YEARS:
        for gate in GATES:
            rows.append(run_one(year, gate, scores[year["year"]]))
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    board = {"ruler": "E ST PIT + qlib close + 5/15bp + PortAna", "rows": rows}
    (OUT_ROOT / "leaderboard.json").write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(board, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
