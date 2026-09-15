# -*- coding: utf-8 -*-
"""M5 二轮：扩展窗预测（只出 pred，不跑 PortAna / 不对齐自检）。

阶段机（eng-perf P1-5）：``predict_extended|train → pred 产物 → export /
sweep --pred-from``。本脚本是上游 pred 写出端；下游只用产物续跑。

复用 ``sweep_live_adapter`` 的构建模式：一次 handler_init 覆盖
train/valid/test 三段 min start ~ max end；模型与 processors 同 M3-A
（含 ``DropLimitUpLearn`` 的 ``module_path`` 接线）。

产物（CWD）：
  - ``预测结果_ext.csv``（datetime,instrument,score）
  - train run-manifest（``config.segments`` 必含三段窗口）

宿主一次约 25 分钟（8 个月 handler）；VM 单测注入 ``predict_fn``，
不触碰真实 qlib 数据。

用法::

    python my_scripts/predict_extended.py
    python my_scripts/predict_extended.py \\
        --train 2026-01-01:2026-01-31 \\
        --valid 2026-02-01:2026-02-28 \\
        --test 2026-03-01:2026-09-08

导出 Qlib 臂（任务 2，as-of / topk 锁死，见 docs/m5r2-export-qlib-arm.md）::

    python my_scripts/export_daily_pool.py --pred my_scripts/预测结果_ext.csv \\
        --out-dir exports/m5r2_pred_topn10_20260302_20260908
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from timeit import default_timer as timer
from typing import Any, Callable, Mapping, Optional, Sequence

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# 共享 mlflow 逃生口 / 静音（须在任何 qlib import 之前）
import host_env  # noqa: E402,F401

from run_manifest import capture_git_provenance, write_train_manifest  # noqa: E402
from sweep_ranking import parse_date_range  # noqa: E402
from handler_frame_cache import resolve_qlib_kernels  # noqa: E402

REPO_ROOT = _SCRIPT_DIR.parent

DEFAULT_SEGMENTS: dict[str, tuple[str, str]] = {
    "train": ("2026-01-01", "2026-01-31"),
    "valid": ("2026-02-01", "2026-02-28"),
    "test": ("2026-03-01", "2026-09-08"),
}

PRED_CSV_NAME = "预测结果_ext.csv"

# 与 sweep_live_adapter / 宿主 Windows 路径对齐；可用 --provider-uri 覆盖
DEFAULT_PROVIDER_URI = "C:/Users/Thinkpad/.qlib/qlib_data/my_data"

# 任务 2：导出命令约定（as-of 默认 pred_minus_one，topk 默认 10）
M5R2_EXPORT_OUT_DIR = "exports/m5r2_pred_topn10_20260302_20260908"
M5R2_EXPORT_TOPK = 10
M5R2_EXPORT_ASOF = "pred_minus_one"

PredictFn = Callable[..., Mapping[str, Any]]


def handler_span(segments: Mapping[str, tuple[str, str]]) -> tuple[str, str]:
    """handler start/end = 三段最小 start / 最大 end。"""
    start_time = min(segments[k][0] for k in ("train", "valid", "test"))
    end_time = max(segments[k][1] for k in ("train", "valid", "test"))
    return start_time, end_time


def validate_segments(segments: Mapping[str, Any]) -> dict[str, tuple[str, str]]:
    """校验三段齐全、起止合法、train.start <= valid.start <= test.start。"""
    if not isinstance(segments, Mapping):
        raise ValueError("segments must be a mapping with train/valid/test")
    missing = [k for k in ("train", "valid", "test") if k not in segments]
    if missing:
        raise ValueError(f"segments missing {missing}")
    parsed: dict[str, tuple[str, str]] = {}
    for key in ("train", "valid", "test"):
        val = segments[key]
        if isinstance(val, str):
            parsed[key] = parse_date_range(val)
        elif isinstance(val, (list, tuple)) and len(val) == 2:
            start, end = str(val[0]).strip(), str(val[1]).strip()
            try:
                d0 = date.fromisoformat(start)
                d1 = date.fromisoformat(end)
            except ValueError as exc:
                raise ValueError(f"illegal {key} dates: {start!r} {end!r}") from exc
            if d0 > d1:
                raise ValueError(f"{key} start > end: {start} > {end}")
            parsed[key] = (start, end)
        else:
            raise ValueError(f"segment {key} must be START:END or (start, end)")
    if not (parsed["train"][0] <= parsed["valid"][0] <= parsed["test"][0]):
        raise ValueError("require train.start <= valid.start <= test.start")
    return parsed


def segments_for_manifest(segments: Mapping[str, tuple[str, str]]) -> dict[str, list[str]]:
    """manifest config 里 segments 用 list，便于 JSON。"""
    return {k: [segments[k][0], segments[k][1]] for k in ("train", "valid", "test")}


def pred_series_to_frame(pred: Any):
    """Normalize model.predict output to DataFrame(datetime, instrument, score)."""
    import pandas as pd

    if isinstance(pred, pd.DataFrame):
        frame = pred.copy()
        if isinstance(frame.index, pd.MultiIndex):
            if "score" not in frame.columns:
                frame = frame.iloc[:, :1].copy()
                frame.columns = ["score"]
            elif list(frame.columns) != ["score"]:
                frame = frame[["score"]]
            frame = frame.reset_index()
        elif "score" not in frame.columns:
            raise ValueError("pred DataFrame needs a score column or MultiIndex")
    elif isinstance(pred, pd.Series):
        series = pred.rename("score") if pred.name != "score" else pred
        frame = series.to_frame().reset_index()
    else:
        raise TypeError(f"unsupported pred type: {type(pred)!r}")

    cols = list(frame.columns)
    # Map first two non-score columns → datetime, instrument when needed
    if "datetime" not in frame.columns or "instrument" not in frame.columns:
        others = [c for c in cols if c != "score"]
        rename: dict[Any, str] = {}
        if "datetime" not in frame.columns and others:
            rename[others[0]] = "datetime"
            others = others[1:]
        if "instrument" not in frame.columns and others:
            rename[others[0]] = "instrument"
        if rename:
            frame = frame.rename(columns=rename)
    if "score" not in frame.columns:
        raise ValueError(f"pred frame missing score; columns={list(frame.columns)}")

    out = frame.loc[:, ["datetime", "instrument", "score"]].copy()
    out["datetime"] = pd.to_datetime(out["datetime"], errors="raise")
    out["instrument"] = out["instrument"].astype(str)
    out["score"] = pd.to_numeric(out["score"], errors="raise")
    return out.dropna(subset=["score"])


def write_pred_csv(pred_frame, path: Path | str) -> Path:
    """Write datetime,instrument,score CSV (UTF-8, no index)."""
    dest = Path(path)
    pred_frame.to_csv(dest, index=False, encoding="utf-8", lineterminator="\n")
    return dest


def live_predict(
    segments: Mapping[str, tuple[str, str]],
    *,
    provider_uri: str = DEFAULT_PROVIDER_URI,
) -> Mapping[str, Any]:
    """一次 handler_init + fit + predict(test)。不跑 PortAna / 不对齐自检。"""
    import pandas as pd
    import qlib
    from qlib.contrib.model import LGBModel
    from qlib.data.dataset import DatasetH

    from custom_handler import Alpha158CostKDJ
    from train_wiring import build_filtered_instruments

    segs = validate_segments(segments)
    # handler 覆盖三段 min start / max end。label 用 Ref($close,-2)，
    # 末尾 1-2 天 label 为 NaN 会被 dropna——与三月窗 / sweep_live_adapter 现行为一致。
    start_time, end_time = handler_span(segs)
    fit_start, fit_end = segs["train"]

    _kernels = resolve_qlib_kernels()
    print(f"[qlib] kernels={_kernels} (QLIB_KERNELS, default 1)", flush=True)
    qlib.init(provider_uri=provider_uri, region="cn", kernels=_kernels)

    instruments = build_filtered_instruments(
        start_time=start_time, end_time=end_time, exclude_stocks=["SZ000004", "SH600107"]
    )
    handler = Alpha158CostKDJ(
        instruments=instruments,
        start_time=start_time,
        end_time=end_time,
        fit_start_time=fit_start,
        fit_end_time=fit_end,
        infer_processors=[
            {"class": "ProcessInf"},
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature"}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        learn_processors=[
            {
                "class": "DropLimitUpLearn",
                "module_path": "custom_handler",
                "kwargs": {"col": "LIMIT_STATUS", "value": 1},
            },
            {"class": "DropnaLabel"},
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "label"}},
        ],
        include_alpha158=True,
        include_cost_kdj=True,
        include_lz=True,
    )
    dataset = DatasetH(handler=handler, segments=dict(segs))
    model = LGBModel(loss="mse", num_boost_round=200, learning_rate=0.05, max_depth=6)
    model.fit(dataset)

    pred = model.predict(dataset, "test")
    if isinstance(pred, pd.DataFrame):
        pred = pred.iloc[:, 0]
    pred = pred.dropna()
    frame = pred_series_to_frame(pred)
    return {
        "pred_frame": frame,
        "pred_rows": int(len(frame)),
        "handler_start": start_time,
        "handler_end": end_time,
        "notes": "predict_extended: pred only (no PortAna / no alignment)",
    }


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "M5r2 extended-window predict (pred CSV + train manifest; no PortAna)"
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--train",
        default=f"{DEFAULT_SEGMENTS['train'][0]}:{DEFAULT_SEGMENTS['train'][1]}",
        type=parse_date_range,
        metavar="START:END",
        help="Train window YYYY-MM-DD:YYYY-MM-DD",
    )
    p.add_argument(
        "--valid",
        default=f"{DEFAULT_SEGMENTS['valid'][0]}:{DEFAULT_SEGMENTS['valid'][1]}",
        type=parse_date_range,
        metavar="START:END",
        help="Valid window YYYY-MM-DD:YYYY-MM-DD",
    )
    p.add_argument(
        "--test",
        default=f"{DEFAULT_SEGMENTS['test'][0]}:{DEFAULT_SEGMENTS['test'][1]}",
        type=parse_date_range,
        metavar="START:END",
        help="Test window YYYY-MM-DD:YYYY-MM-DD",
    )
    p.add_argument(
        "--out-csv",
        default=PRED_CSV_NAME,
        help="Prediction CSV filename/path (default: CWD 预测结果_ext.csv)",
    )
    p.add_argument(
        "--manifests-dir",
        default=None,
        help="Train manifests directory (default: <repo>/manifests)",
    )
    p.add_argument(
        "--provider-uri",
        default=DEFAULT_PROVIDER_URI,
        help="qlib provider_uri (host Windows path by default)",
    )
    p.add_argument(
        "--no-manifest",
        action="store_true",
        help="Skip writing train run-manifest",
    )
    return p


def run_predict_extended(
    segments: Mapping[str, Any],
    *,
    out_csv: Path | str = PRED_CSV_NAME,
    manifests_dir: Path | str | None = None,
    repo_root: Path | str | None = None,
    provider_uri: str = DEFAULT_PROVIDER_URI,
    predict_fn: Optional[PredictFn] = None,
    git_prov: Optional[Mapping[str, Any]] = None,
    write_manifest: bool = True,
    cwd: Path | str | None = None,
) -> dict[str, Any]:
    """Core entry: validate → predict → write CSV (+ optional train manifest).

    ``predict_fn`` injection avoids real qlib/handler_init on VM tests.
    Injected callable receives validated segments and may accept
    ``provider_uri=`` kwarg; return mapping with ``pred_frame`` (DataFrame)
    or a Series/DataFrame under ``pred``.
    """
    import pandas as pd

    segs = validate_segments(segments)
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    work = Path(cwd) if cwd is not None else Path.cwd()
    out_path = Path(out_csv)
    if not out_path.is_absolute():
        out_path = work / out_path

    if git_prov is None:
        git_prov = capture_git_provenance(root)

    t0 = timer()
    fn = predict_fn or live_predict
    try:
        payload = dict(fn(segs, provider_uri=provider_uri))
    except TypeError:
        # allow simple mocks that only take segments
        payload = dict(fn(segs))

    if "pred_frame" in payload:
        frame = payload["pred_frame"]
    elif "pred" in payload:
        frame = pred_series_to_frame(payload["pred"])
    else:
        raise ValueError("predict_fn must return 'pred_frame' or 'pred'")

    if not isinstance(frame, pd.DataFrame):
        frame = pred_series_to_frame(frame)
    else:
        need = {"datetime", "instrument", "score"}
        if not need.issubset(set(frame.columns)):
            frame = pred_series_to_frame(frame)

    write_pred_csv(frame, out_path)
    elapsed = float(timer() - t0)
    pred_rows = int(payload.get("pred_rows") or len(frame))
    start_time, end_time = handler_span(segs)

    manifest_paths: list[Path] = []
    if write_manifest:
        man_dir = (
            Path(manifests_dir)
            if manifests_dir is not None
            else root / "manifests"
        )
        man_cfg = {
            "stage_kind": "predict_extended",
            "exp_name": "predict_extended",
            "segments": segments_for_manifest(segs),
            "handler_start": start_time,
            "handler_end": end_time,
            "include_lz": True,
            "drop_limit_up_learn": True,
            "portana": False,
            "alignment_check": False,
            "pred_csv": out_path.name,
        }
        extra_cfg = payload.get("config")
        if isinstance(extra_cfg, Mapping):
            man_cfg.update(dict(extra_cfg))
            man_cfg["segments"] = segments_for_manifest(segs)
        data = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
        timings = (
            payload.get("timings")
            if isinstance(payload.get("timings"), Mapping)
            else {
                "total_seconds": elapsed,
                "nodes": [{"name": "predict_extended", "seconds": elapsed}],
            }
        )
        written = write_train_manifest(
            manifests_dir=man_dir,
            config=man_cfg,
            pred_path=out_path if out_path.is_file() else None,
            timings=timings,
            data=data or {},
            repo_root=root,
            git_commit_sha=git_prov.get("git_commit") if git_prov else None,
            git_branch=git_prov.get("git_branch") if git_prov else None,
            git_dirty=git_prov.get("git_dirty") if git_prov else None,
            pred_rows=pred_rows,
            artifact_dirs=[out_path.parent],
        )
        manifest_paths = list(written)

    return {
        "pred_path": str(out_path),
        "pred_rows": pred_rows,
        "segments": segs,
        "handler_span": (start_time, end_time),
        "manifest_paths": [str(p) for p in manifest_paths],
        "elapsed_seconds": elapsed,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    # 启动时一次性取 git 溯源（收尾写 manifest 不再读 HEAD）
    git_prov = capture_git_provenance(REPO_ROOT)
    args = build_arg_parser().parse_args(argv)
    segments = {
        "train": args.train,
        "valid": args.valid,
        "test": args.test,
    }
    try:
        validate_segments(segments)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    result = run_predict_extended(
        segments,
        out_csv=args.out_csv,
        manifests_dir=args.manifests_dir,
        repo_root=REPO_ROOT,
        provider_uri=args.provider_uri,
        git_prov=git_prov,
        write_manifest=not args.no_manifest,
    )
    print(
        f"[predict_extended] pred={result['pred_path']} rows={result['pred_rows']} "
        f"handler={result['handler_span'][0]}..{result['handler_span'][1]} "
        f"secs={result['elapsed_seconds']:.1f}",
        flush=True,
    )
    if result["manifest_paths"]:
        print(f"[predict_extended] manifest={result['manifest_paths'][0]}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
