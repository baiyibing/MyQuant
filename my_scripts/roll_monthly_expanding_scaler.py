# -*- coding: utf-8 -*-
"""Monthly walk-forward with per-fold RobustZScoreNorm (textbook option 1).

Alpha158 is computed once (no z-score in the cached handler). Each fold fits
median/MAD on that fold's train dates only, then transforms valid/test.
Does not write 8a061ea4 / 55c5bf77. Does not rebuild 11G nine times.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import host_env  # noqa: E402,F401

from roll_cat_monthly import (  # noqa: E402
    FORBIDDEN_RECORDERS,
    LAST_TEST_END,
    PROVIDER,
    _clip_to_calendar,
    _score_frame,
    monthly_folds,
)

OUT_DIR = _SCRIPT_DIR.parent / "exports" / "analysis" / "lgb_roll_monthly_expanding_scaler"


def apply_robust_zscore(df: pd.DataFrame, train_start: str, train_end: str) -> pd.DataFrame:
    """Fit qlib RobustZScoreNorm on [train_start, train_end], apply to the whole frame."""
    from qlib.data.dataset.processor import RobustZScoreNorm

    proc = RobustZScoreNorm(
        fit_start_time=train_start,
        fit_end_time=train_end,
        fields_group="feature",
        clip_outlier=True,
    )
    out = df.copy()
    proc.fit(out)
    return proc(out)


def _relabel_learn(handler, infer_df: pd.DataFrame) -> pd.DataFrame:
    learn = infer_df.copy()
    return handler._run_proc_l(
        learn, handler.learn_processors, with_fit=True, check_for_infer=False
    )


def main() -> int:
    import qlib
    from qlib.config import REG_CN
    from qlib.contrib.evaluate import backtest_daily
    from qlib.data import D
    from qlib.data.dataset import DatasetH
    from qlib.utils import init_instance_by_config

    from analysis_export import write_analysis_bundle
    from custom_handler import Alpha158CostKDJ, build_learn_processors
    from handler_frame_cache import (
        attach_calendar_fingerprint,
        load_or_build_handler,
        make_handler_cache_payload,
        resolve_lgb_num_threads,
    )
    from rebacktest_cost_tiers import (
        COST_TIERS,
        EXECUTOR_CONFIG,
        build_exchange_kwargs,
        build_strategy_config,
        metrics,
    )
    from train_wiring import EXCLUDE_STOCKS_DEFAULT, build_filtered_instruments, build_fit_kwargs, build_model_task

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
    start_time, end_time = "2020-01-01", "2026-09-14"
    instruments = build_filtered_instruments(
        start_time=start_time,
        end_time=end_time,
        exclude_stocks=EXCLUDE_STOCKS_DEFAULT,
        use_exclude=False,
        limit_up=False,
        market="all",
    )
    handler_cfg = {
        "start_time": start_time,
        "end_time": end_time,
        "fit_start_time": "2020-01-01",
        "fit_end_time": "2024-12-31",
        "infer_processors": [
            {"class": "ProcessInf"},
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
    payload = make_handler_cache_payload(
        start_time=start_time,
        end_time=end_time,
        fit_start_time="2020-01-01",
        fit_end_time="2024-12-31",
        segments={"train": ("2020-01-01", "2024-12-31"), "valid": ("2025-01-01", "2025-12-31"), "test": ("2026-01-01", "2026-09-14")},
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
    payload["robust_zscore"] = "per_fold"
    payload = attach_calendar_fingerprint(payload)
    print("[roll1] load/build pre-zscore handler (once)", flush=True)
    handler, hit, obs = load_or_build_handler(
        payload=payload,
        builder=lambda: Alpha158CostKDJ(**handler_cfg),
        enabled=True,
    )
    print(f"[roll1] handler cache_hit={hit} key={obs.get('digest')}", flush=True)
    base_infer = handler._infer.copy()
    print(f"[roll1] base infer rows={len(base_infer)} cols={base_infer.shape[1]}", flush=True)

    cal = [pd.Timestamp(d).normalize() for d in D.calendar()]
    folds = [{k: _clip_to_calendar(a, b, cal) for k, (a, b) in raw.items()} for raw in monthly_folds()]
    args = SimpleNamespace(model="lgb", model_config=None, num_boost_round=1000, early_stopping_rounds=50)
    model_cfg = build_model_task(args, resolve_lgb_num_threads())
    fit_kwargs = build_fit_kwargs(args)

    pieces: list[pd.DataFrame] = []
    fold_rows: list[dict] = []
    for i, seg in enumerate(folds):
        train_start, train_end = seg["train"]
        print(f"[roll1] fold {i} scaler fit {train_start}..{train_end}", flush=True)
        infer = apply_robust_zscore(base_infer, train_start, train_end)
        handler._infer = infer
        handler._learn = _relabel_learn(handler, infer)
        dataset = DatasetH(handler=handler, segments=seg)
        model = init_instance_by_config(model_cfg)
        print(f"[roll1] fit LGB fold {i}", flush=True)
        model.fit(dataset, **fit_kwargs)
        frame = _score_frame(model.predict(dataset, "test"))
        n = len(frame)
        span = f"{frame['datetime'].min().date()}..{frame['datetime'].max().date()}" if n else "empty"
        print(f"[roll1] fold {i} pred rows={n} {span}", flush=True)
        if n == 0:
            raise SystemExit(f"fold {i} empty pred")
        pieces.append(frame)
        fold_rows.append({"fold": i, "segments": seg, "pred_rows": n, "span": span})

    cat = pd.concat(pieces, ignore_index=True)
    cat["datetime"] = pd.to_datetime(cat["datetime"]).dt.normalize()
    cat = cat.sort_values(["datetime", "instrument"], kind="mergesort")
    cat = cat.drop_duplicates(["datetime", "instrument"], keep="last")
    score = cat.set_index(["datetime", "instrument"])["score"].sort_index()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pred_csv = OUT_DIR / "预测结果_lgb_roll_expanding_scaler.csv"
    cat.to_csv(pred_csv, index=False, encoding="utf-8")

    ns = SimpleNamespace(
        pred_score=score,
        topk=50,
        n_drop=5,
        hold_thresh=1,
        buy_state_filter=False,
        st_filter=False,
        age_filter=False,
        extra_exclude_file=None,
        st_daily_file=None,
        winner_ratio_file=None,
        return_threshold_filter=False,
        test_window=("2026-01-01", LAST_TEST_END),
    )
    report, positions = backtest_daily(
        start_time="2026-01-01",
        end_time=LAST_TEST_END,
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
    summary = {
        "model": "lgb",
        "style": "expanding_train_and_scaler_1m_test",
        "handler": obs.get("digest"),
        "forbidden_recorders": list(FORBIDDEN_RECORDERS),
        "nav_end": nav_end,
        "excess_ann": exc["annualized_return"],
        "excess_ir": exc["information_ratio"],
        "excess_mdd": exc["max_drawdown"],
        "abs_ann": abs_m["annualized_return"],
        "abs_mdd": abs_m["max_drawdown"],
        "folds": fold_rows,
        "pred_csv": str(pred_csv),
    }
    print(json.dumps({k: summary[k] for k in ("nav_end", "excess_ann", "excess_ir", "excess_mdd", "abs_ann")}, ensure_ascii=False), flush=True)
    write_analysis_bundle(
        positions=positions,
        out_dir=OUT_DIR,
        open_rate=0.0005,
        close_rate=0.0015,
        account=1e8,
        pred=score.to_frame("score"),
        report=report,
        topk=50,
        use_qlib_close=True,
        extra_summary={"source": "roll_monthly_expanding_scaler", "model": "lgb"},
    )
    (OUT_DIR / "roll_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
