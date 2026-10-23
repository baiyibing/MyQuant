# -*- coding: utf-8 -*-
"""Several models on three labels. One handler load.

h1: close[T+2] / close[T+1] - 1
h2: close[T+3] / close[T+1] - 1
x5: five-trading-day return minus the same window on SH510300
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "my_scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "my_scripts"))

from train_etf_smoke import (  # noqa: E402
    SEGMENTS,
    SURVIVORSHIP_NOTE,
    TEST_END,
    TRAIN_END,
    TRAIN_START,
    WINDOW_START,
    _column,
    _dates_of,
    acceptance_ic,
    assert_etf_provider,
    build_named_model,
    fit_named,
)

OUT = ROOT / "exports" / "etf_label_horizon_models"
MODELS = ("lgb", "xgb", "cat", "ols", "ridge", "lasso", "histgb")
LABELS = {
    "h1": ("Ref($close, -2)/Ref($close, -1) - 1", (1, 2)),
    "h2": ("Ref($close, -3)/Ref($close, -1) - 1", (1, 3)),
    "x5": (
        "Ref($close, -6)/Ref($close, -1) - ChangeInstrument('SH510300', Ref($close, -6)/Ref($close, -1))",
        (1, 6),
    ),
}


class _OneLabel:
    """Expose a single label column so qlib models that reject multi-label can fit."""

    def __init__(self, dataset, label_name: str):
        self.dataset = dataset
        self.label_name = label_name

    def __getattr__(self, name):
        return getattr(self.dataset, name)

    def prepare(self, segments, col_set=None, data_key=None, **kwargs):
        result = self.dataset.prepare(segments, col_set=col_set, data_key=data_key, **kwargs)
        if isinstance(result, (list, tuple)):
            return type(result)(self._narrow(item) for item in result)
        return self._narrow(result)

    def _narrow(self, frame):
        if not isinstance(frame, pd.DataFrame) or not isinstance(frame.columns, pd.MultiIndex):
            return frame
        if "label" not in frame.columns.get_level_values(0):
            return frame
        keep = [
            col
            for col in frame.columns
            if col[0] == "feature" or (col[0] == "label" and col[-1] == self.label_name)
        ]
        return frame.loc[:, keep]


def _selected_models(argv: list[str] | None) -> tuple[str, ...]:
    if argv and "--models" in argv:
        raw = argv[argv.index("--models") + 1]
        return tuple(item.strip() for item in raw.split(",") if item.strip())
    return MODELS


def main(argv: list[str] | None = None) -> int:
    import host_env  # noqa: F401
    import qlib
    from qlib.constant import REG_CN
    from qlib.data import D
    from qlib.data.dataset import DatasetH
    from qlib.data.dataset.handler import DataHandlerLP
    from qlib.utils import init_instance_by_config
    from qlib.workflow import R

    qlib_dir = assert_etf_provider(Path.home() / ".qlib" / "qlib_data" / "my_data_etf")
    fields = [expr for expr, _horizons in LABELS.values()]
    models = _selected_models(argv if argv is not None else sys.argv[1:])
    print("labels", list(LABELS), "models", list(models), flush=True)
    print(SURVIVORSHIP_NOTE, flush=True)
    qlib.init(provider_uri=str(qlib_dir), region=REG_CN, kernels=1)
    handler_conf = {
        "class": "Alpha158",
        "module_path": "qlib.contrib.data.handler",
        "kwargs": {
            "instruments": "etf_full",
            "start_time": WINDOW_START,
            "end_time": TEST_END,
            "fit_start_time": TRAIN_START,
            "fit_end_time": TRAIN_END,
            "label": (fields, list(LABELS)),
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
    calendar = pd.DatetimeIndex(D.calendar(start_time=WINDOW_START, end_time=TEST_END))
    lines = [
        "train 2020-01-02..2024-12-31  valid 2025  test 2026-01-05..2026-10-13",
        SURVIVORSHIP_NOTE,
        "models " + ",".join(models),
    ]
    for label_name, (expr, horizons) in LABELS.items():
        view = _OneLabel(dataset, label_name)
        print(f"LABEL {label_name} {expr}", flush=True)
        lines.append(f"label {label_name} {expr}")
        for model_name in models:
            print(f"MODEL {model_name} label {label_name}", flush=True)
            try:
                model = build_named_model(model_name, 8, 200)
                with R.start(experiment_name=f"etf_horizon_{label_name}_{model_name}"):
                    fit_named(model_name, model, view, 200)
                for seg_name, (seg_start, seg_end) in SEGMENTS.items():
                    pred = _column(model.predict(view, segment=seg_name))
                    raw = view.prepare(seg_name, col_set="label", data_key=DataHandlerLP.DK_I)
                    label = raw.iloc[:, 0] if isinstance(raw, pd.DataFrame) else raw
                    joined = pd.concat([pred.rename("pred"), label.rename("label")], axis=1, join="inner")
                    report = acceptance_ic(
                        joined["pred"].to_numpy(),
                        joined["label"].to_numpy(),
                        _dates_of(joined.index),
                        calendar,
                        seg_start,
                        seg_end,
                        horizons=horizons,
                    )
                    line = (
                        f"label {label_name} model {model_name} segment {seg_name} "
                        f"n={report['n']} ic={report['ic']} rank_ic={report['rank_ic']}"
                    )
                    print(line, flush=True)
                    lines.append(line)
            except Exception as exc:
                print(f"MODEL {model_name} label {label_name} failed: {type(exc).__name__}: {exc}", flush=True)
                lines.append(f"label {label_name} model {model_name} failed {type(exc).__name__}: {exc}")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "ic_report.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("report", path, flush=True)
    return 0


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    raise SystemExit(main(sys.argv[1:]))
