# -*- coding: utf-8 -*-
"""ETF 日线 Alpha158 + 小 LightGBM 冒烟。只初始化 my_data_etf。

验收 IC 排除跨段标签和未定义标签。日志里出现「IC」两个字不算通过。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "my_scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "my_scripts"))

from qlib_scripts.build_etf_qlib import (  # noqa: E402
    SURVIVORSHIP_NOTE,
    BuildEtfError,
    WINDOW_END,
    WINDOW_START,
    assert_target_allowed,
    default_protected,
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
    "DatasetH 的 learn 仍使用训练段时间切片，段末跨界行若标签有数值会进入拟合；验收不计这些行。"
)
DEFAULT_QLIB = Path.home() / ".qlib" / "qlib_data" / "my_data_etf"
DEFAULT_OUT = ROOT / "exports" / "etf_smoke"


def assert_etf_provider(path: Path, protected: tuple[Path, ...] | None = None) -> Path:
    resolved = Path(path).expanduser()
    if resolved.name.lower() != "my_data_etf":
        raise BuildEtfError(f"provider 必须是 my_data_etf，收到 {resolved}")
    assert_target_allowed(resolved, protected or default_protected())
    return realpath(resolved)


def in_segment_label_mask(dates, calendar, seg_start: str, seg_end: str, horizons: tuple[int, ...] = (1, 2)):
    cal = pd.DatetimeIndex(pd.to_datetime(list(calendar))).normalize().unique().sort_values()
    pos = {ts: i for i, ts in enumerate(cal)}
    start = pd.Timestamp(seg_start)
    end = pd.Timestamp(seg_end)
    mask = []
    for raw in dates:
        ts = pd.Timestamp(raw).normalize()
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


DEFAULT_MODELS = ("lgb", "xgb", "cat", "double", "ols", "ridge", "lasso", "histgb")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ETF daily Alpha158 multi-model smoke on my_data_etf")
    parser.add_argument("--qlib-dir", type=Path, default=DEFAULT_QLIB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--num-boost-round", type=int, default=200)
    parser.add_argument("--exp-name", default="etf_daily_models")
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
            return pd.to_datetime(index.get_level_values("datetime"))
        return pd.to_datetime(index.get_level_values(0))
    return pd.to_datetime(index)


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
    qlib_dir = assert_etf_provider(args.qlib_dir)
    if not (qlib_dir / "calendars" / "day.txt").is_file():
        raise BuildEtfError(f"缺少日历 {qlib_dir / 'calendars' / 'day.txt'}")
    print(LABEL_RULE, flush=True)
    print(SURVIVORSHIP_NOTE, flush=True)
    print(
        f"fit_start_time={TRAIN_START} fit_end_time={TRAIN_END} "
        "learn/infer processors 只在这段上拟合；验证段和测试段不参与拟合",
        flush=True,
    )
    qlib.init(provider_uri=str(qlib_dir), region=REG_CN, kernels=1)
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
        dataset = DatasetH(handler=init_instance_by_config(handler_conf), segments=SEGMENTS)
    handler = dataset.handler
    print("handler", type(handler).__name__, "label", handler.get_label_config(), flush=True)
    for kind, procs in (("infer", handler.infer_processors), ("learn", handler.learn_processors)):
        for proc in procs:
            print(
                f"processor {kind} {type(proc).__name__} "
                f"fit_start_time={getattr(proc, 'fit_start_time', None)} "
                f"fit_end_time={getattr(proc, 'fit_end_time', None)}",
                flush=True,
            )
    names = [item.strip() for item in str(args.models).split(",") if item.strip()]
    unknown = [item for item in names if item not in DEFAULT_MODELS]
    if unknown:
        raise BuildEtfError(f"未知模型 {unknown}")
    calendar = pd.DatetimeIndex(D.calendar(start_time=WINDOW_START, end_time=TEST_END))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    lines = [LABEL_RULE, SURVIVORSHIP_NOTE, f"fit {TRAIN_START} {TRAIN_END}", f"models {','.join(names)}"]
    summaries = []
    for model_name in names:
        print(f"MODEL {model_name}", flush=True)
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
                if seg_name == "test":
                    test_report = report
            if test_report is None or test_report["n"] < 2 or test_report["ic"] is None:
                summaries.append((model_name, None, None, test_report["n"] if test_report else 0))
                print(f"ACCEPT_IC {model_name} failed", flush=True)
            else:
                summaries.append((model_name, test_report["ic"], test_report["rank_ic"], test_report["n"]))
                print(
                    f"ACCEPT_IC {model_name} test={test_report['ic']} "
                    f"n={test_report['n']} rank_ic={test_report['rank_ic']}",
                    flush=True,
                )
        except Exception as exc:
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
    if not any(ic is not None for _name, ic, _rank, _count in summaries):
        return 2
    return 0


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    raise SystemExit(main())
