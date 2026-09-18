# -*- coding: utf-8 -*-
"""Replay the 'looks higher' 2026 combos on the current aligned ruler.

E: ST PIT, qlib bins / official 5/15bp, PortAna path only (BT is a separate
CLI). Does not write 8a061ea4 / 55c5bf77 recorders or their original analysis
packages. Does not replay the leading-zero bug or lake front prices.
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
OUT_ROOT = ROOT / "exports" / "analysis" / "replay_20260917_current_ruler"
PRED_DUMP = ROOT / "exports" / "replay_20260917_current_ruler"
FORBIDDEN = {
    "8a061ea428e04bb3a199a485ade49d0e",
    "55c5bf773ea34ef797355e94113c1962",
}

COMBOS = (
    {
        "id": "lgb_8a061ea4_20n3_nofilter",
        "label": "8a061ea4 20/3 全关",
        "exp": "alpha158_cost_kdj_lgb",
        "rec": "8a061ea428e04bb3a199a485ade49d0e",
        "topk": 20,
        "n_drop": 3,
        "st": False,
        "age": False,
        "ret15": False,
        "old": "+25.0% qlib / +28.2% zero",
    },
    {
        "id": "lgb_8a061ea4_50n5_st_age",
        "label": "8a061ea4 50/5 ST+年龄",
        "exp": "alpha158_cost_kdj_lgb",
        "rec": "8a061ea428e04bb3a199a485ade49d0e",
        "topk": 50,
        "n_drop": 5,
        "st": True,
        "age": True,
        "ret15": False,
        "old": "+23.2% qlib",
    },
    {
        "id": "lgb_8a061ea4_50n5_stag15",
        "label": "8a061ea4 50/5 ST+年龄+15%",
        "exp": "alpha158_cost_kdj_lgb",
        "rec": "8a061ea428e04bb3a199a485ade49d0e",
        "topk": 50,
        "n_drop": 5,
        "st": True,
        "age": True,
        "ret15": True,
        "old": "current-gate set, not in old table",
    },
    {
        "id": "cat_4233a65a_50n5_nofilter",
        "label": "Cat 4233a65a 50/5 全关",
        "exp": "alpha158_cost_kdj_cat_all",
        "rec": "4233a65a0ae346698fc6822905950469",
        "topk": 50,
        "n_drop": 5,
        "st": False,
        "age": False,
        "ret15": False,
        "old": "+21.0% qlib",
    },
)


def _score_frame(pred) -> pd.Series:
    if hasattr(pred, "columns") and "score" in getattr(pred, "columns", []):
        return pred["score"]
    return pred


def _dump_pred_csv(rec_id: str, pred) -> Path:
    PRED_DUMP.mkdir(parents=True, exist_ok=True)
    path = PRED_DUMP / f"{rec_id[:8]}_pred.csv"
    frame = _score_frame(pred)
    if isinstance(frame, pd.Series):
        out = frame.rename("score").reset_index()
    else:
        out = frame.reset_index()
    cols = {out.columns[0]: "datetime", out.columns[1]: "instrument"}
    out = out.rename(columns=cols)
    if "score" not in out.columns:
        raise SystemExit(f"pred dump missing score: {list(out.columns)}")
    out[["datetime", "instrument", "score"]].to_csv(path, index=False, encoding="utf-8")
    print(f"[dump] {path} rows={len(out)}", flush=True)
    return path


def _run_one(combo: dict, score) -> dict:
    out_dir = OUT_ROOT / combo["id"]
    if out_dir.resolve() in {ROOT / "exports" / "analysis" / rid for rid in FORBIDDEN}:
        raise SystemExit(f"refusing to write forbidden dir {out_dir}")
    ns = SimpleNamespace(
        exp_name=combo["exp"],
        recorder_id=combo["rec"],
        test_window=("2026-01-01", "2026-09-14"),
        benchmark="SH000300",
        account=1e8,
        topk=combo["topk"],
        n_drop=combo["n_drop"],
        hold_thresh=1,
        no_limit_threshold=False,
        buy_state_filter=False,
        st_filter=combo["st"],
        age_filter=combo["age"],
        age_days=60,
        extra_exclude_file=None,
        st_daily_file=ST if combo["st"] else None,
        winner_ratio_file=None,
        return_threshold_filter=combo["ret15"],
        pred_score=score,
    )
    print(
        f"[run] {combo['id']} topk={combo['topk']}/{combo['n_drop']} "
        f"st={combo['st']} age={combo['age']} 15%={combo['ret15']}",
        flush=True,
    )
    report, positions = backtest_daily(
        start_time="2026-01-01",
        end_time="2026-09-14",
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
        "pred": combo["rec"],
        "topk": combo["topk"],
        "n_drop": combo["n_drop"],
        "st_filter": combo["st"],
        "age_filter": combo["age"],
        "return_threshold_filter": combo["ret15"],
        "old": combo["old"],
        "nav_end": nav_end,
        "excess_ann": exc["annualized_return"],
        "excess_ir": exc["information_ratio"],
        "excess_mdd": exc["max_drawdown"],
        "abs_ann": abs_m["annualized_return"],
        "abs_mdd": abs_m["max_drawdown"],
        "interval_ret": nav_end / 1e8 - 1.0,
    }
    print(json.dumps({k: row[k] for k in ("id", "nav_end", "excess_ann", "abs_ann", "interval_ret")}, ensure_ascii=False), flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_analysis_bundle(
        positions=positions,
        out_dir=out_dir,
        open_rate=0.0005,
        close_rate=0.0015,
        account=1e8,
        pred=score.to_frame("score") if isinstance(score, pd.Series) else score,
        report=report,
        topk=combo["topk"],
        use_qlib_close=True,
        extra_summary={
            "source": "replay_highwater_current_ruler",
            "pred_recorder_id": combo["rec"],
            "st_filter": combo["st"],
            "age_filter": combo["age"],
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
    cache: dict[str, object] = {}
    dumped: set[str] = set()
    rows: list[dict] = []
    for combo in COMBOS:
        rec = combo["rec"]
        if rec not in cache:
            _recorder, pred = load_pred(combo["exp"], rec)
            cache[rec] = _score_frame(pred)
            if rec not in dumped:
                _dump_pred_csv(rec, cache[rec])
                dumped.add(rec)
        rows.append(_run_one(combo, cache[rec]))
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    board = {"ruler": "E ST PIT + qlib close + 5/15bp + PortAna", "rows": rows}
    (OUT_ROOT / "leaderboard.json").write_text(
        json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(board, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
