# -*- coding: utf-8 -*-
"""Smoke train/predict on my_data_1min. Does not touch daily my_data or keeper preds."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import host_env  # noqa: F401

import pandas as pd
import qlib
from catboost.utils import get_gpu_device_count
from qlib.constant import REG_CN
from qlib.contrib.model import LGBModel
from qlib.contrib.model.catboost_model import CatBoostModel
from qlib.data.dataset import DatasetH
from qlib.utils import init_instance_by_config
from qlib.workflow import R
from qlib.workflow.record_temp import SigAnaRecord, SignalRecord

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "my_scripts"))

from custom_handler_1min import Alpha1minSmall
from handler_frame_cache import resolve_lgb_num_threads

sys.path.insert(0, str(ROOT / "qlib_scripts"))
from build_mydata_1min import SMOKE_SYMBOLS

DEFAULT_QLIB_DIR = Path.home() / ".qlib" / "qlib_data" / "my_data_1min"
DEFAULT_OUT = ROOT / "exports" / "1min_smoke"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="1min LGB smoke; writes exports/1min_smoke/")
    parser.add_argument("--qlib-dir", type=Path, default=DEFAULT_QLIB_DIR)
    parser.add_argument("--start", default="2025-01-02 09:30:00")
    parser.add_argument("--train-end", default="2026-06-30 15:00:00")
    parser.add_argument("--valid-end", default="2026-07-31 15:00:00")
    parser.add_argument("--test-end", default="2026-09-09 15:00:00")
    parser.add_argument("--label-horizon", type=int, default=2, help="bars; 2=official highfreq, 30≈half hour")
    parser.add_argument("--instruments", nargs="*", default=list(SMOKE_SYMBOLS))
    parser.add_argument("--all-instruments", action="store_true", help="Use instruments/all (5570 names; heavy)")
    parser.add_argument("--model", choices=("lgb", "cat"), default="lgb")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--exp-name", default="")
    return parser


def _build_model(kind: str, threads: int):
    if kind == "cat":
        gpu_n = int(get_gpu_device_count())
        print("catboost gpu_count", gpu_n, "task_type", "GPU" if gpu_n > 0 else "CPU")
        return CatBoostModel(
            loss="RMSE",
            learning_rate=0.05,
            depth=6,
            l2_leaf_reg=3.0,
            thread_count=threads,
            devices="0",
            allow_writing_files=False,
        )
    return LGBModel(
        loss="mse",
        learning_rate=0.05,
        max_depth=6,
        num_leaves=31,
        num_threads=threads,
        verbosity=-1,
    )


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    qlib_dir = args.qlib_dir.expanduser().resolve()
    daily = (Path.home() / ".qlib/qlib_data/my_data").resolve()
    if qlib_dir == daily:
        raise SystemExit("refusing to init daily my_data")
    if not (qlib_dir / "calendars" / "1min.txt").is_file():
        raise SystemExit(f"missing 1min calendar: {qlib_dir / 'calendars' / '1min.txt'}")

    qlib.init(provider_uri=str(qlib_dir), region=REG_CN, kernels=1)
    universe = "all" if args.all_instruments else (args.instruments or list(SMOKE_SYMBOLS))
    threads = resolve_lgb_num_threads()
    print(
        "instruments",
        "all" if universe == "all" else f"{len(universe)} names",
        "model",
        args.model,
        "threads",
        threads,
    )
    handler_conf = {
        "class": "Alpha1minSmall",
        "module_path": "custom_handler_1min",
        "kwargs": {
            "instruments": universe,
            "start_time": args.start,
            "end_time": args.test_end,
            "fit_start_time": args.start,
            "fit_end_time": args.train_end,
            "freq": "1min",
            "label_horizon": int(args.label_horizon),
        },
    }
    dataset = DatasetH(
        handler=init_instance_by_config(handler_conf),
        segments={
            "train": (args.start, args.train_end),
            "valid": (args.train_end, args.valid_end),
            "test": (args.valid_end, args.test_end),
        },
    )
    model = _build_model(args.model, threads)
    exp = args.exp_name or ("1min_cat_all" if args.model == "cat" and universe == "all" else "1min_smoke")
    with R.start(experiment_name=exp):
        model.fit(dataset)
        pred = model.predict(dataset)
        SignalRecord(model, dataset, R.get_recorder()).generate()
        try:
            SigAnaRecord(R.get_recorder()).generate()
        except Exception as exc:
            print("SigAna skipped:", exc)
        recorder = R.get_recorder()
        print("recorder", recorder.id)

    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    frame = pred.reset_index()
    if list(frame.columns)[:2] != ["datetime", "instrument"]:
        frame.columns = ["datetime", "instrument", "score"] + list(frame.columns[3:])
    else:
        frame = frame.rename(columns={frame.columns[2]: "score"})
    dest = out / f"预测结果_1min_{args.model}_h{int(args.label_horizon)}.csv"
    frame.to_csv(dest, index=False)
    print("features", ["MA5", "MA10", "MA20", "MA60", "STD20", "V5V20", "RET1", "HL"])
    print("label", f"Ref($close,-{int(args.label_horizon)})/Ref($close,-1)-1")
    print("pred", dest, "rows", len(frame), "days", frame["datetime"].nunique())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
