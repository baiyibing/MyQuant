# -*- coding: utf-8 -*-
"""Cat monthly expanding walk-forward on the 2020-24 / 2025 / 2026 split.

Fold 0 = original: train 2020-01-01:2024-12-31, valid 2025, test 2026-01.
Each later fold expands train by one calendar month, slides the 12-month
valid window, and tests the next month. Last test month clips at 2026-09-14.

Handler is the pinned all-universe cache (RobustZScoreNorm stays 2020-2024).
Does not write 8a061ea4 / 55c5bf77 recorders.
"""
from __future__ import annotations

import argparse
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

HANDLER_DIGEST = "25badc30f01216cf990faf7100033790208e4d2602ac20108d37ee2a33e70cf2"
FORBIDDEN_RECORDERS = (
    "8a061ea428e04bb3a199a485ade49d0e",
    "55c5bf773ea34ef797355e94113c1962",
)
TRAIN_START = "2020-01-01"
LAST_TEST_END = "2026-09-14"
PROVIDER = "~/.qlib/qlib_data/my_data"
DEFAULT_OUT_DIR = _SCRIPT_DIR.parent / "exports" / "analysis" / "cat_roll_monthly_2026"


def monthly_folds(
    *,
    train_start: str = TRAIN_START,
    last_test_end: str = LAST_TEST_END,
) -> list[dict[str, tuple[str, str]]]:
    """Expanding train + 12-month valid + 1-month test, calendar month ends."""
    last = pd.Timestamp(last_test_end)
    test_months = pd.date_range("2026-01-01", last, freq="MS")
    folds: list[dict[str, tuple[str, str]]] = []
    for test_start in test_months:
        test_end = min(test_start + pd.offsets.MonthEnd(0), last)
        valid_start = test_start - pd.DateOffset(years=1)
        valid_end = test_start - pd.Timedelta(days=1)
        train_end = valid_start - pd.Timedelta(days=1)
        folds.append(
            {
                "train": (_ymd(train_start), _ymd(train_end)),
                "valid": (_ymd(valid_start), _ymd(valid_end)),
                "test": (_ymd(test_start), _ymd(test_end)),
            }
        )
    return folds


def _ymd(value) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _clip_to_calendar(start: str, end: str, cal: list[pd.Timestamp]) -> tuple[str, str]:
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    inside = [d for d in cal if lo <= d <= hi]
    if not inside:
        raise ValueError(f"no trading days in {start}..{end}")
    return _ymd(inside[0]), _ymd(inside[-1])


def _score_frame(pred) -> pd.DataFrame:
    from predict_extended import pred_series_to_frame

    return pred_series_to_frame(pred)


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Monthly expanding walk-forward (Cat/LGB)")
    p.add_argument("--model", default="cat", help="configs/models/<name>.yaml (cat or lgb)")
    p.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="artifact dir (default exports/analysis/<model>_roll_monthly_2026)",
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    import qlib
    from qlib.config import REG_CN
    from qlib.contrib.evaluate import backtest_daily
    from qlib.data import D
    from qlib.data.dataset import DatasetH
    from qlib.utils import init_instance_by_config

    from analysis_export import write_analysis_bundle
    from handler_frame_cache import resolve_lgb_num_threads, try_load_handler
    from rebacktest_cost_tiers import (
        COST_TIERS,
        EXECUTOR_CONFIG,
        build_exchange_kwargs,
        build_strategy_config,
        metrics,
    )
    from train_wiring import build_fit_kwargs, build_model_task

    cli = _parse_args(argv)
    model_name = str(cli.model).strip().lower()
    out_dir = Path(cli.out_dir) if cli.out_dir else (
        _SCRIPT_DIR.parent / "exports" / "analysis" / f"{model_name}_roll_monthly_2026"
    )

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
    cal = [pd.Timestamp(d).normalize() for d in D.calendar()]
    handler = try_load_handler(HANDLER_DIGEST)
    if handler is None:
        raise SystemExit(f"missing pinned handler {HANDLER_DIGEST[:16]}; refuse rebuild")
    print(f"[roll] loaded handler {HANDLER_DIGEST[:16]}", flush=True)

    args = SimpleNamespace(
        model=model_name,
        model_config=None,
        num_boost_round=1000,
        early_stopping_rounds=50,
    )
    model_cfg = build_model_task(args, resolve_lgb_num_threads())
    fit_kwargs = build_fit_kwargs(args)

    raw_folds = monthly_folds()
    folds = []
    for raw in raw_folds:
        folds.append(
            {k: _clip_to_calendar(a, b, cal) for k, (a, b) in raw.items()}
        )
    print(f"[roll] {len(folds)} folds", flush=True)
    for i, seg in enumerate(folds):
        print(f"[roll] fold {i} train={seg['train']} valid={seg['valid']} test={seg['test']}", flush=True)

    pieces: list[pd.DataFrame] = []
    fold_rows: list[dict] = []
    for i, seg in enumerate(folds):
        print(f"[roll] fit fold {i}", flush=True)
        dataset = DatasetH(handler=handler, segments=seg)
        model = init_instance_by_config(model_cfg)
        model.fit(dataset, **fit_kwargs)
        pred = model.predict(dataset, "test")
        frame = _score_frame(pred)
        n = len(frame)
        span = (
            f"{frame['datetime'].min().date()}..{frame['datetime'].max().date()}"
            if n
            else "empty"
        )
        print(f"[roll] fold {i} pred rows={n} {span}", flush=True)
        if n == 0:
            raise SystemExit(f"fold {i} produced empty pred")
        pieces.append(frame)
        fold_rows.append({"fold": i, "segments": seg, "pred_rows": n, "span": span})

    cat = pd.concat(pieces, ignore_index=True)
    cat["datetime"] = pd.to_datetime(cat["datetime"]).dt.normalize()
    cat = cat.sort_values(["datetime", "instrument"], kind="mergesort")
    cat = cat.drop_duplicates(["datetime", "instrument"], keep="last")
    score = cat.set_index(["datetime", "instrument"])["score"].sort_index()
    print(f"[roll] concat rows={len(score)} days={score.index.get_level_values(0).nunique()}", flush=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    pred_csv = out_dir / f"预测结果_{model_name}_roll_monthly_2026.csv"
    cat.to_csv(pred_csv, index=False, encoding="utf-8")

    ns = SimpleNamespace(
        exp_name=f"alpha158_cost_kdj_{model_name}_roll_m",
        recorder_id="local_roll",
        test_window=("2026-01-01", LAST_TEST_END),
        benchmark="SH000300",
        account=1e8,
        topk=50,
        n_drop=5,
        hold_thresh=1,
        no_limit_threshold=False,
        buy_state_filter=False,
        st_filter=False,
        age_filter=False,
        extra_exclude_file=None,
        st_daily_file=None,
        winner_ratio_file=None,
        return_threshold_filter=False,
        pred_score=score,
    )
    strategy = build_strategy_config(ns)
    report, positions = backtest_daily(
        start_time="2026-01-01",
        end_time=LAST_TEST_END,
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
    summary = {
        "model": model_name,
        "style": "expanding_train_roll_12m_valid_1m_test",
        "handler": HANDLER_DIGEST[:16],
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
        out_dir=out_dir,
        open_rate=0.0005,
        close_rate=0.0015,
        account=1e8,
        pred=score.to_frame("score"),
        report=report,
        topk=50,
        use_qlib_close=True,
        extra_summary={
            "source": "roll_monthly",
            "model": model_name,
            "handler": HANDLER_DIGEST[:16],
        },
    )
    (out_dir / "roll_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
