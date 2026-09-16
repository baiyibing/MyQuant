# -*- coding: utf-8 -*-
"""工单 5 弱窗：复用 50/5 recorder 的 trained_model，只对 2025 valid 出分。

不重训、不写 recorder、不碰 预测结果.csv。
handler 与今早 50/5 同窗同闸门，尽量打中 handler cache。
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
from qlib.data.dataset import DatasetH
from qlib.workflow import R

from custom_handler import Alpha158CostKDJ, build_learn_processors
from custom_utils import TimerRecorder, install_features_probe, set_global_timer_recorder
from handler_frame_cache import (
    attach_calendar_fingerprint,
    load_or_build_handler,
    make_handler_cache_payload,
)
from rebacktest_cost_tiers import parse_segment, run_tiers
from train_wiring import EXCLUDE_STOCKS_DEFAULT, build_filtered_instruments

REC = "8a061ea428e04bb3a199a485ade49d0e"
EXP = "alpha158_cost_kdj_lgb"
PROVIDER = "~/.qlib/qlib_data/my_data"
SEGMENTS = {
    "train": ("2020-01-01", "2024-12-31"),
    "valid": ("2025-01-01", "2025-12-31"),
    "test": ("2026-01-01", "2026-09-14"),
}
WEAK = "2025-01-01:2025-12-31"
GRID = ((10, 3), (20, 3), (50, 5))
PRED_CSV = "预测结果_8a061ea4_2025valid.csv"
OUT_JSON = (
    Path(__file__).resolve().parents[1]
    / "docs/reviews/2026-09-15-qlib-perf-brainstorm/runs/2026-09-15-weak-window-2025.json"
)


def _score_from_pred(pred) -> pd.Series:
    if isinstance(pred, pd.DataFrame):
        if "score" in pred.columns:
            return pred["score"].dropna()
        return pred.iloc[:, 0].dropna()
    return pred.dropna()


def predict_valid_2025(t_rec: TimerRecorder) -> pd.Series:
    start_time, end_time = SEGMENTS["train"][0], SEGMENTS["test"][1]
    fit_start, fit_end = SEGMENTS["train"]
    with t_rec.timer("instruments"):
        instruments = build_filtered_instruments(
            start_time=start_time,
            end_time=end_time,
            exclude_stocks=EXCLUDE_STOCKS_DEFAULT,
            use_exclude=False,
            limit_up=False,
            market="all",
        )
    data_handler_config = {
        "start_time": start_time,
        "end_time": end_time,
        "fit_start_time": fit_start,
        "fit_end_time": fit_end,
        "infer_processors": [
            {"class": "ProcessInf"},
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature"}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        "learn_processors": build_learn_processors(drop_limit_up=False),
        "instruments": instruments,
        "include_alpha158": True,
        "include_cost_kdj": True,
        "include_signal": False,
        "include_lz": True,
        "drop_raw": True,
    }
    payload = attach_calendar_fingerprint(
        make_handler_cache_payload(
            start_time=start_time,
            end_time=end_time,
            fit_start_time=fit_start,
            fit_end_time=fit_end,
            segments=SEGMENTS,
            include_alpha158=True,
            include_cost_kdj=True,
            include_signal=False,
            include_lz=True,
            drop_raw=True,
            exclude_filter_on=False,
            limit_up_filter_on=False,
            tradable_universe_on=False,
            drop_limit_up_learn_on=False,
            provider_uri=PROVIDER,
        )
    )
    print(f"[weak] handler cache digest={payload.get('digest', '')}", flush=True)
    with t_rec.timer("handler_init"):
        handler, hit, obs = load_or_build_handler(
            payload=payload,
            builder=lambda: Alpha158CostKDJ(**data_handler_config),
            enabled=True,
        )
    print(f"[weak] handler cache_hit={hit} key={obs.get('digest')}", flush=True)
    with t_rec.timer("dataset_init"):
        dataset = DatasetH(handler=handler, segments=dict(SEGMENTS))
    rec = R.get_recorder(recorder_id=REC, experiment_name=EXP)
    with t_rec.timer("load_trained_model"):
        model = rec.load_object("trained_model")
    print("[weak] loaded trained_model; predict valid 2025 (read-only, no save)", flush=True)
    with t_rec.timer("model_predict_valid"):
        pred = model.predict(dataset, "valid")
    score = _score_from_pred(pred)
    print(f"[weak] 2025 pred rows={len(score)}", flush=True)
    if len(score) == 0:
        raise RuntimeError("2025 valid pred is empty")
    idx = score.index
    if isinstance(idx, pd.MultiIndex):
        dates = pd.to_datetime(idx.get_level_values(0))
        print(f"[weak] pred span {dates.min().date()} .. {dates.max().date()}", flush=True)
    return score


def main() -> int:
    t_rec = TimerRecorder()
    set_global_timer_recorder(t_rec)
    qlib.init(
        provider_uri=os.path.expanduser(PROVIDER),
        region=REG_CN,
        kernels=1,
        exp_manager={
            "class": "MLflowExpManager",
            "module_path": "qlib.workflow.expm",
            "kwargs": {"uri": "mlruns", "default_exp_name": "MyExperiment"},
        },
    )
    uninstall = install_features_probe(t_rec)
    score = predict_valid_2025(t_rec)
    out_csv = Path(PRED_CSV)
    if out_csv.exists():
        raise SystemExit(f"refuse overwrite existing {out_csv}")
    frame = score.rename("score").to_frame()
    frame.to_csv(out_csv, encoding="utf-8")
    print(f"[weak] wrote {out_csv.resolve()} (not 预测结果.csv)", flush=True)

    window = parse_segment(WEAK, "test")
    rows = []
    for topk, n_drop in GRID:
        print(f"=== weak {WEAK} topk={topk} n_drop={n_drop} ===", flush=True)
        ns = SimpleNamespace(
            exp_name=EXP,
            recorder_id=REC,
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
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "recorder_id": REC,
        "model_source": "trained_model (same recorder, no retrain)",
        "pred_csv": PRED_CSV,
        "test": list(window),
        "note": "2025 is valid-year / early-stop window; weak evidence",
        "grid": rows,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"=== weak window saved {OUT_JSON} ===", flush=True)
    try:
        uninstall()
        t_rec.print_summary()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
