# -*- coding: utf-8 -*-
"""Rebuild handler with expanding scaler for Cat fold 8 only; compare to frozen.

Does not overwrite 8a061ea4 / 55c5bf77. Writes a new handler-cache key.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import host_env  # noqa: E402,F401

FORBIDDEN = (
    "8a061ea428e04bb3a199a485ade49d0e",
    "55c5bf773ea34ef797355e94113c1962",
)
FROZEN_PRED = (
    _SCRIPT_DIR.parent
    / "exports"
    / "analysis"
    / "cat_roll_monthly_2026"
    / "预测结果_cat_roll_monthly_2026.csv"
)
OUT_DIR = _SCRIPT_DIR.parent / "exports" / "analysis" / "cat_roll_lastfold_refit_scaler"
SEGMENTS = {
    "train": ("2020-01-02", "2025-08-29"),
    "valid": ("2025-09-01", "2026-08-31"),
    "test": ("2026-09-01", "2026-09-14"),
}
FIT_END = "2025-08-29"
PROVIDER = "~/.qlib/qlib_data/my_data"


def _score_frame(pred) -> pd.DataFrame:
    from predict_extended import pred_series_to_frame

    return pred_series_to_frame(pred)


def compare_scores(frozen: pd.DataFrame, refit: pd.DataFrame) -> dict:
    a = frozen.copy()
    b = refit.copy()
    a["datetime"] = pd.to_datetime(a["datetime"]).dt.normalize()
    b["datetime"] = pd.to_datetime(b["datetime"]).dt.normalize()
    a["instrument"] = a["instrument"].astype(str)
    b["instrument"] = b["instrument"].astype(str)
    merged = a.merge(b, on=["datetime", "instrument"], suffixes=("_frozen", "_refit"))
    if merged.empty:
        raise SystemExit("no overlapping scores to compare")
    daily = []
    for day, g in merged.groupby("datetime", sort=True):
        spe = g["score_frozen"].corr(g["score_refit"], method="spearman")
        pea = g["score_frozen"].corr(g["score_refit"], method="pearson")
        top_a = set(g.nlargest(50, "score_frozen")["instrument"])
        top_b = set(g.nlargest(50, "score_refit")["instrument"])
        daily.append(
            {
                "date": str(pd.Timestamp(day).date()),
                "spearman": float(spe) if pd.notna(spe) else None,
                "pearson": float(pea) if pd.notna(pea) else None,
                "top50_overlap": int(len(top_a & top_b)),
            }
        )
    spearmans = [d["spearman"] for d in daily if d["spearman"] is not None]
    overlaps = [d["top50_overlap"] for d in daily]
    return {
        "overlap_rows": int(len(merged)),
        "days": len(daily),
        "spearman_mean": float(np.mean(spearmans)) if spearmans else None,
        "top50_overlap_mean": float(np.mean(overlaps)) if overlaps else None,
        "daily": daily,
    }


def main() -> int:
    import qlib
    from qlib.config import REG_CN
    from qlib.data.dataset import DatasetH
    from qlib.utils import init_instance_by_config

    from custom_handler import Alpha158CostKDJ, build_learn_processors
    from handler_frame_cache import (
        attach_calendar_fingerprint,
        load_or_build_handler,
        make_handler_cache_payload,
        resolve_lgb_num_threads,
    )
    from train_wiring import EXCLUDE_STOCKS_DEFAULT, build_filtered_instruments, build_model_task, build_fit_kwargs

    if not FROZEN_PRED.is_file():
        raise SystemExit(f"missing frozen pred {FROZEN_PRED}")

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
        "fit_end_time": FIT_END,
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
            fit_start_time="2020-01-01",
            fit_end_time=FIT_END,
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
    print(f"[refit] building/loading handler fit_end={FIT_END}", flush=True)
    handler, hit, obs = load_or_build_handler(
        payload=payload,
        builder=lambda: Alpha158CostKDJ(**handler_cfg),
        enabled=True,
    )
    print(f"[refit] handler cache_hit={hit} key={obs.get('digest')}", flush=True)

    args = SimpleNamespace(
        model="cat",
        model_config=None,
        num_boost_round=1000,
        early_stopping_rounds=50,
    )
    model_cfg = build_model_task(args, resolve_lgb_num_threads())
    dataset = DatasetH(handler=handler, segments=dict(SEGMENTS))
    model = init_instance_by_config(model_cfg)
    print("[refit] fit Cat on expanding-scaler handler", flush=True)
    model.fit(dataset, **build_fit_kwargs(args))
    frame = _score_frame(model.predict(dataset, "test"))
    print(
        f"[refit] pred rows={len(frame)} {frame['datetime'].min()} .. {frame['datetime'].max()}",
        flush=True,
    )

    frozen = pd.read_csv(FROZEN_PRED)
    frozen["datetime"] = pd.to_datetime(frozen["datetime"])
    frozen = frozen[frozen["datetime"] >= "2026-09-01"]
    cmp = compare_scores(frozen, frame)
    print(json.dumps({k: cmp[k] for k in ("overlap_rows", "days", "spearman_mean", "top50_overlap_mean")}, ensure_ascii=False), flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUT_DIR / "预测结果_cat_fold8_refit_scaler.csv", index=False, encoding="utf-8")
    (OUT_DIR / "compare.json").write_text(
        json.dumps(
            {
                "handler_digest": obs.get("digest"),
                "cache_hit": hit,
                "fit_end": FIT_END,
                "segments": SEGMENTS,
                "forbidden": list(FORBIDDEN),
                **cmp,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
