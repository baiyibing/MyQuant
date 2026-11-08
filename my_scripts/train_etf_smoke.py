# -*- coding: utf-8 -*-
"""ETF 日线 Alpha158 + 小 LightGBM 冒烟。只初始化 my_data_etf。

验收 IC 排除跨段标签和未定义标签。日志里出现「IC」两个字不算通过。
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from myquant_infra.artifacts.provenance import sha256_file as file_sha256

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "my_scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "my_scripts"))

from myquant_infra.adapters.qlib_data.build_etf_qlib import (  # noqa: E402
    SURVIVORSHIP_NOTE,
    BuildEtfError,
    WINDOW_END,
    WINDOW_START,
    assert_target_allowed,
    realpath,
    summarize_ratios,
)

TRAIN_START = "2020-01-02"
TRAIN_END = "2024-12-31"
VALID_START = "2025-01-02"
VALID_END = "2025-12-31"
TEST_START = "2026-01-05"
TEST_END = WINDOW_END
SEGMENTS = {
    "train": (TRAIN_START, TRAIN_END),
    "valid": (VALID_START, VALID_END),
    "test": (TEST_START, TEST_END),
}
LABEL_EXPR = "Ref($close, -2)/Ref($close, -1) - 1"
LABEL_RULE = (
    "标签 "
    + LABEL_EXPR
    + " 在日期 T 使用之后第 1、第 2 个交易日的收盘。"
    "这两个交易日必须都落在本段内，否则视为跨界或未定义，不进入验收 IC。"
    "训练和验证的 DatasetH 分段末日也按相同规则收窄，跨界标签不进入拟合或 early stopping。"
)
DEFAULT_QLIB = Path.home() / ".qlib" / "qlib_data" / "my_data_etf"
DEFAULT_OUT = ROOT / "exports" / "etf_smoke"


def default_protected() -> tuple[Path, ...]:
    base = Path.home() / ".qlib" / "qlib_data"
    return (base / "my_data", base / "my_data_1min")


def assert_etf_provider(path: Path, protected: tuple[Path, ...] | None = None) -> Path:
    resolved = Path(path).expanduser()
    if resolved.name.lower() != "my_data_etf":
        raise BuildEtfError(f"provider 必须是 my_data_etf，收到 {resolved}")
    assert_target_allowed(resolved, protected or default_protected())
    return realpath(resolved)


def _normalized_calendar(calendar) -> pd.DatetimeIndex:
    return cast(Any, pd.DatetimeIndex(pd.to_datetime(list(calendar)))).normalize()


def in_segment_label_mask(dates, calendar, seg_start: str, seg_end: str, horizons: tuple[int, ...] = (1, 2)):
    cal = _normalized_calendar(calendar).unique().sort_values()
    pos = {ts: i for i, ts in enumerate(cal)}
    start = pd.Timestamp(seg_start)
    end = pd.Timestamp(seg_end)
    mask = []
    for raw in dates:
        ts = cast(pd.Timestamp, pd.Timestamp(raw)).normalize()
        index = pos.get(ts)
        if index is None or not (start <= ts <= end):
            mask.append(False)
            continue
        ok = True
        for horizon in horizons:
            future = index + horizon
            if future >= len(cal) or not (start <= cal[future] <= end):
                ok = False
                break
        mask.append(ok)
    return np.asarray(mask, dtype=bool)


def finite_corr(pred, label) -> tuple[float | None, int]:
    left = np.asarray(pred, dtype="float64")
    right = np.asarray(label, dtype="float64")
    mask = np.isfinite(left) & np.isfinite(right)
    count = int(mask.sum())
    if count < 2:
        return None, count
    value = float(np.corrcoef(left[mask], right[mask])[0, 1])
    if not np.isfinite(value):
        return None, count
    return value, count


def finite_rank_ic(pred, label) -> tuple[float | None, int]:
    left = np.asarray(pred, dtype="float64")
    right = np.asarray(label, dtype="float64")
    mask = np.isfinite(left) & np.isfinite(right)
    count = int(mask.sum())
    if count < 2:
        return None, count
    value = float(pd.Series(left[mask]).rank().corr(pd.Series(right[mask]).rank()))
    if not np.isfinite(value):
        return None, count
    return value, count


def acceptance_ic(pred, label, dates, calendar, seg_start: str, seg_end: str, horizons: tuple[int, ...] = (1, 2)) -> dict:
    keep = in_segment_label_mask(dates, calendar, seg_start, seg_end, horizons=horizons)
    pred_a = np.asarray(pred, dtype="float64")
    label_a = np.asarray(label, dtype="float64")
    ic, n_finite = finite_corr(pred_a[keep], label_a[keep])
    rank_ic, _n_rank = finite_rank_ic(pred_a[keep], label_a[keep])
    return {
        "ic": ic,
        "rank_ic": rank_ic,
        "n": n_finite,
        "rows": int(len(keep)),
        "kept": int(keep.sum()),
        "cross_or_undefined": int((~keep).sum()),
    }


def effective_fit_segments(calendar, segments=None) -> dict:
    """Purge forward labels from fitting while retaining nominal test dates."""
    nominal = SEGMENTS if segments is None else segments
    cal = _normalized_calendar(calendar)
    if cal.empty or not cal.is_unique or not cal.is_monotonic_increasing:
        raise BuildEtfError("fit calendar must be nonempty, unique and increasing")
    effective = dict(nominal)
    for name in ("train", "valid"):
        start, end = nominal[name]
        eligible = cal[in_segment_label_mask(cal, cal, start, end)]
        if eligible.empty:
            raise BuildEtfError(f"no in-segment fit labels: {name}")
        effective[name] = (start, str(cast(pd.Timestamp, eligible[-1]).date()))
    return effective


def fit_sample_summary(dataset, calendar, effective, data_key) -> dict:
    """Check the actual prepared learn rows, not only the configured cutoffs."""
    result = {}
    for name in ("train", "valid"):
        labels = dataset.prepare(name, col_set="label", data_key=data_key)
        dates = _dates_of(labels.index)
        if len(dates) == 0:
            raise BuildEtfError(f"empty prepared fit segment: {name}")
        start, end = SEGMENTS[name]
        allowed = in_segment_label_mask(dates, calendar, start, end)
        first, last = cast(pd.Timestamp, dates.min()), cast(pd.Timestamp, dates.max())
        if not allowed.all() or last > cast(pd.Timestamp, pd.Timestamp(effective[name][1])):
            raise BuildEtfError(f"cross-boundary prepared fit labels: {name}")
        result[name] = {"rows": len(dates), "first": str(first.date()),
                        "last": str(last.date()), "all_label_dates_in_nominal_segment": True}
    return result


def prepare_artifact_output(out: Path, provider: Path) -> None:
    assert_target_allowed(out, (*default_protected(), provider))
    if out.exists():
        raise BuildEtfError("acceptance output must be a fresh directory")
    out.mkdir(parents=True, exist_ok=False)


def persist_segment(out: Path, model_name: str, segment: str, joined: pd.DataFrame, calendar, report: dict) -> dict:
    if not joined.index.is_unique:
        raise BuildEtfError("duplicate prediction/label index")
    frame = joined.copy()
    frame["in_segment"] = in_segment_label_mask(_dates_of(frame.index), calendar, *SEGMENTS[segment])
    frame["finite_pair"] = np.isfinite(frame["pred"].to_numpy(dtype=float)) & np.isfinite(frame["label"].to_numpy(dtype=float))
    frame["accepted"] = frame["in_segment"] & frame["finite_pair"]
    if int(frame["accepted"].sum()) != report["n"]:
        raise BuildEtfError("persisted acceptance count mismatch")
    path = out / model_name / f"{segment}_pred_label.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".parquet.tmp")
    frame.to_parquet(temporary, index=True)
    temporary.replace(path)
    return {"path": path.relative_to(out).as_posix(), "sha256": file_sha256(path),
            "bytes": path.stat().st_size, "rows": len(frame), "report": report}


def package_versions() -> dict:
    result = {}
    for name in ("pyqlib", "lightgbm", "pandas", "numpy", "pyarrow"):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


DEFAULT_MODELS = ("lgb", "xgb", "cat", "double", "ols", "ridge", "lasso", "histgb")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ETF daily Alpha158 multi-model smoke on my_data_etf")
    parser.add_argument("--qlib-dir", type=Path, default=DEFAULT_QLIB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--num-boost-round", type=int, default=200)
    parser.add_argument("--exp-name", default="etf_daily_models")
    parser.add_argument("--write-acceptance-artifacts", action="store_true",
                        help="Write auditable prediction/label Parquet and JSON into a fresh --out-dir.")
    parser.add_argument(
        "--models",
        default=",".join(DEFAULT_MODELS),
        help="comma list: lgb,xgb,cat,double,ols,ridge,lasso,histgb",
    )
    return parser


def build_named_model(name: str, threads: int, num_boost_round: int):
    """同一套 DatasetH 上的对照模型。线性模型不吃 boost 轮数。"""
    if name == "lgb":
        from qlib.contrib.model import LGBModel

        return LGBModel(
            loss="mse",
            learning_rate=0.05,
            max_depth=6,
            num_leaves=31,
            num_threads=threads,
            num_boost_round=num_boost_round,
            early_stopping_rounds=30,
            verbosity=-1,
        )
    if name == "xgb":
        from qlib.contrib.model.xgboost import XGBModel

        return XGBModel(
            objective="reg:squarederror",
            eta=0.05,
            max_depth=6,
            nthread=threads,
            verbosity=0,
        )
    if name == "cat":
        from qlib.contrib.model.catboost_model import CatBoostModel

        return CatBoostModel(
            loss="RMSE",
            learning_rate=0.05,
            depth=6,
            thread_count=threads,
            allow_writing_files=False,
        )
    if name == "double":
        from qlib.contrib.model.double_ensemble import DEnsembleModel

        return DEnsembleModel(
            base_model="gbm",
            loss="mse",
            num_models=3,
            epochs=min(80, int(num_boost_round)),
            early_stopping_rounds=20,
            num_threads=threads,
            learning_rate=0.05,
            max_depth=6,
            num_leaves=31,
            verbosity=-1,
        )
    if name in {"ols", "ridge", "lasso"}:
        from qlib.contrib.model.linear import LinearModel

        alpha = {"ols": 0.0, "ridge": 1.0, "lasso": 0.001}[name]
        return LinearModel(estimator=name, alpha=alpha, fit_intercept=True, include_valid=False)
    if name == "histgb":
        from sklearn.ensemble import HistGradientBoostingRegressor

        return _SklearnRegressor(
            HistGradientBoostingRegressor(
                loss="squared_error",
                learning_rate=0.05,
                max_depth=6,
                max_iter=int(num_boost_round),
                early_stopping=True,
                n_iter_no_change=30,
                random_state=0,
            )
        )
    raise BuildEtfError(f"未知模型 {name}")


class _SklearnRegressor:
    """把 sklearn 回归器接到 DatasetH.fit / predict。"""

    def __init__(self, estimator):
        self.estimator = estimator

    def fit(self, dataset, **_kwargs):
        from qlib.data.dataset.handler import DataHandlerLP

        frame = dataset.prepare("train", col_set=["feature", "label"], data_key=DataHandlerLP.DK_L)
        frame = frame.dropna()
        self.estimator.fit(frame["feature"].to_numpy(), np.squeeze(frame["label"].to_numpy()))

    def predict(self, dataset, segment="test"):
        from qlib.data.dataset.handler import DataHandlerLP

        feature = dataset.prepare(segment, col_set="feature", data_key=DataHandlerLP.DK_I)
        values = self.estimator.predict(feature.to_numpy())
        return pd.Series(values, index=feature.index, name="score")


def fit_named(name: str, model, dataset, num_boost_round: int) -> None:
    if name in {"xgb", "cat"}:
        model.fit(dataset, num_boost_round=int(num_boost_round), early_stopping_rounds=30, verbose_eval=20)
        return
    model.fit(dataset)


def _dates_of(index: pd.Index) -> pd.DatetimeIndex:
    if isinstance(index, pd.MultiIndex):
        if "datetime" in index.names:
            return pd.DatetimeIndex(index.get_level_values("datetime"))
        return pd.DatetimeIndex(index.get_level_values(0))
    return pd.DatetimeIndex(index)


def _column(frame_or_series):
    if isinstance(frame_or_series, pd.DataFrame):
        return frame_or_series.iloc[:, 0]
    return frame_or_series


def main(argv=None) -> int:
    import host_env  # noqa: F401
    import qlib
    from qlib.constant import REG_CN
    from qlib.data import D
    from qlib.data.dataset import DatasetH
    from qlib.data.dataset.handler import DataHandlerLP
    from qlib.utils import init_instance_by_config
    from qlib.workflow import R

    args = build_parser().parse_args(argv)
    names = [item.strip() for item in str(args.models).split(",") if item.strip()]
    if not names:
        raise BuildEtfError("at least one model is required")
    unknown = [item for item in names if item not in DEFAULT_MODELS]
    if unknown:
        raise BuildEtfError(f"未知模型 {unknown}")
    if args.write_acceptance_artifacts and len(set(names)) != len(names):
        raise BuildEtfError("duplicate model names cannot share acceptance artifacts")
    qlib_dir = assert_etf_provider(args.qlib_dir)
    if not (qlib_dir / "calendars" / "day.txt").is_file():
        raise BuildEtfError(f"缺少日历 {qlib_dir / 'calendars' / 'day.txt'}")
    out = Path(args.out_dir)
    if args.write_acceptance_artifacts:
        prepare_artifact_output(out, qlib_dir)
    print(LABEL_RULE, flush=True)
    print(SURVIVORSHIP_NOTE, flush=True)
    print(
        f"fit_start_time={TRAIN_START} fit_end_time={TRAIN_END} "
        "learn/infer processors 只在这段上拟合；验证段和测试段不参与拟合",
        flush=True,
    )
    qlib.init(provider_uri=str(qlib_dir), region=REG_CN, kernels=1, expression_cache=None, dataset_cache=None)
    calendar = pd.DatetimeIndex(D.calendar(start_time=WINDOW_START, end_time=TEST_END))
    fit_segments = effective_fit_segments(calendar)
    print("effective_fit_segments", fit_segments, flush=True)
    threads = 8
    raw_threads = str(__import__("os").environ.get("LGB_NUM_THREADS", "") or "").strip()
    if raw_threads.isdigit() and int(raw_threads) >= 1:
        threads = int(raw_threads)
    handler_conf = {
        "class": "Alpha158",
        "module_path": "qlib.contrib.data.handler",
        "kwargs": {
            "instruments": "etf_full",
            "start_time": WINDOW_START,
            "end_time": TEST_END,
            "fit_start_time": TRAIN_START,
            "fit_end_time": TRAIN_END,
            "infer_processors": [
                {"class": "ProcessInf", "kwargs": {}},
                {"class": "ZScoreNorm", "kwargs": {"fields_group": "feature"}},
                {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
            ],
        },
    }
    from joblib import parallel_backend

    with parallel_backend("threading"):
        dataset = DatasetH(handler=init_instance_by_config(handler_conf), segments=fit_segments)
    handler = dataset.handler
    fit_samples = fit_sample_summary(dataset, calendar, fit_segments, DataHandlerLP.DK_L)
    print("handler", type(handler).__name__, "label", handler.get_label_config(), flush=True)
    for kind, procs in (("infer", handler.infer_processors), ("learn", handler.learn_processors)):
        for proc in procs:
            print(
                f"processor {kind} {type(proc).__name__} "
                f"fit_start_time={getattr(proc, 'fit_start_time', None)} "
                f"fit_end_time={getattr(proc, 'fit_end_time', None)}",
                flush=True,
            )
    out.mkdir(parents=True, exist_ok=True)
    lines = [LABEL_RULE, SURVIVORSHIP_NOTE, f"fit {TRAIN_START} {TRAIN_END}", f"models {','.join(names)}"]
    summaries = []
    component_receipts: dict[str, dict[str, Any]] = {}
    for model_name in names:
        print(f"MODEL {model_name}", flush=True)
        component: dict[str, Any] = {"status": "FAIL", "segments": {}}
        component_receipts[model_name] = component
        try:
            model = build_named_model(model_name, threads, int(args.num_boost_round))
            with R.start(experiment_name=f"{args.exp_name}_{model_name}"):
                fit_named(model_name, model, dataset, int(args.num_boost_round))
                recorder = R.get_recorder()
                print("recorder", model_name, recorder.id, flush=True)
            test_report = None
            for seg_name, (seg_start, seg_end) in SEGMENTS.items():
                pred = _column(model.predict(dataset, segment=seg_name))
                label = _column(dataset.prepare(seg_name, col_set="label", data_key=DataHandlerLP.DK_I))
                joined = pd.concat([pred.rename("pred"), label.rename("label")], axis=1, join="inner")
                report = acceptance_ic(
                    joined["pred"].to_numpy(),
                    joined["label"].to_numpy(),
                    _dates_of(joined.index),
                    calendar,
                    seg_start,
                    seg_end,
                )
                line = (
                    f"model {model_name} segment {seg_name} n={report['n']} "
                    f"ic={report['ic']} rank_ic={report['rank_ic']}"
                )
                print(line, flush=True)
                lines.append(line)
                if args.write_acceptance_artifacts:
                    component["segments"][seg_name] = persist_segment(out, model_name, seg_name, joined, calendar, report)
                    component["segments"][seg_name]["alignment"] = {"prediction_rows": len(pred), "label_rows": len(label), "inner_join_rows": len(joined)}
                if seg_name == "test":
                    test_report = report
            if test_report is None or test_report["n"] < 2 or test_report["ic"] is None:
                summaries.append((model_name, None, None, test_report["n"] if test_report else 0))
                print(f"ACCEPT_IC {model_name} failed", flush=True)
            else:
                component["status"] = "PASS"
                summaries.append((model_name, test_report["ic"], test_report["rank_ic"], test_report["n"]))
                print(
                    f"ACCEPT_IC {model_name} test={test_report['ic']} "
                    f"n={test_report['n']} rank_ic={test_report['rank_ic']}",
                    flush=True,
                )
        except Exception as exc:
            component["error_type"] = type(exc).__name__
            print(f"MODEL {model_name} failed: {type(exc).__name__}: {exc}", flush=True)
            lines.append(f"model {model_name} failed {type(exc).__name__}: {exc}")
            summaries.append((model_name, None, None, 0))
    close = D.features(D.instruments(market="etf_full"), ["$close"], start_time=WINDOW_START, end_time=TEST_END)
    if isinstance(close.index, pd.MultiIndex) and "instrument" in close.index.names:
        counts = close.iloc[:, 0].groupby(level="instrument").apply(lambda s: int(s.notna().sum()))
    else:
        counts = close.iloc[:, 0].groupby(level=1).apply(lambda s: int(s.notna().sum()))
    gap = summarize_ratios([1.0 - count / len(calendar) for count in counts.tolist()])
    gap_line = f"etf_full_gaps n={gap['n']} mean={gap['mean']} median={gap['median']} max={gap['max']}"
    print(gap_line, flush=True)
    lines.append(gap_line)
    lines.append("test_compare")
    print("test_compare", flush=True)
    for model_name, ic, rank_ic, count in summaries:
        row = f"compare {model_name} ic={ic} rank_ic={rank_ic} n={count}"
        print(row, flush=True)
        lines.append(row)
    report_path = out / "ic_report.txt"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("report", report_path, flush=True)
    if args.write_acceptance_artifacts:
        anchors = {rel: file_sha256(qlib_dir / rel) for rel in
                   ("calendars/day.txt", "instruments/all.txt", "instruments/etf_full.txt")}
        passed = sum(item["status"] == "PASS" for item in component_receipts.values())
        receipt = {
            "schema_version": "etf-smoke-acceptance.v1", "policy": "purged-fit-h1-h2.v1",
            "status": "PASS" if passed == len(names) else "PARTIAL" if passed else "FAIL",
            "nominal_segments": SEGMENTS, "effective_segments": fit_segments, "fit_samples": fit_samples,
            "label": LABEL_EXPR, "horizons": [1, 2], "mask_bounds": "nominal segments",
            "ic_method": "pooled Pearson; RankIC is pooled Spearman over accepted finite rows",
            "processor_fit": [{"group": kind, "class": type(proc).__name__,
                "fit_start_time": str(getattr(proc, "fit_start_time", None)),
                "fit_end_time": str(getattr(proc, "fit_end_time", None))}
                for kind, procs in (("infer", handler.infer_processors), ("learn", handler.learn_processors)) for proc in procs],
            "provider_anchors_sha256": anchors, "script_sha256": file_sha256(Path(__file__)),
            "versions": package_versions(), "threads": threads,
            "seed_policy": "unchanged library/model defaults; no cross-version bitwise retraining guarantee",
            "models": component_receipts, "survivorship_note": SURVIVORSHIP_NOTE,
        }
        receipt_path = out / "acceptance.json"
        temporary = receipt_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        temporary.replace(receipt_path)
    if not any(ic is not None for _name, ic, _rank, _count in summaries):
        return 2
    return 0


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    raise SystemExit(main())
