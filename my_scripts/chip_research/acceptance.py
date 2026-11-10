"""Bounded native chip -> LightGBM -> Qlib PortAna -> signal export acceptance.

Explicit existing provider only; input_kind labels synthetic and market runs separately.
This checks executable wiring, not profitability or point-in-time market-data quality.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from myquant_infra.artifacts.provenance import capture_git_provenance, md5_file, sha256_file
from myquant_infra.contracts.signal_bundle import (
    build_signal_bundle, canonical_json_bytes, validate_signal_bundle,
)

ROOT = Path(__file__).resolve().parents[2]
FIELDS = ("open", "close", "high", "low", "vol", "volume", "turnover_rate", "factor")


def provider_inventory(provider):
    return {p.relative_to(provider).as_posix(): [p.stat().st_size, p.stat().st_mtime_ns]
            for p in sorted(provider.rglob("*")) if p.is_file()}


def prepare(args):
    provider, output = Path(args.provider).expanduser(), Path(args.output).expanduser()
    if not provider.is_absolute() or not output.is_absolute():
        raise ValueError("provider and output must be absolute")
    provider, output = provider.resolve(), output.resolve()
    for protected in (provider, ROOT):
        if output.is_relative_to(protected) or protected.is_relative_to(output):
            raise ValueError("output must not overlap the provider or source checkout")
    if output.exists():
        raise FileExistsError("output must be a fresh directory")
    symbols = args.instruments.split(",")
    if not 3 <= len(symbols) <= 12 or len(set(symbols)) != len(symbols):
        raise ValueError("select 3..12 distinct instruments")
    import re
    if any(re.fullmatch(r"(?:SH|SZ|BJ)[0-9]{6}", s) is None for s in [*symbols, args.benchmark]):
        raise ValueError("use explicit Qlib instrument codes, e.g. SH600000")
    calendar_file = provider / "calendars/day.txt"
    calendar = pd.DatetimeIndex(pd.to_datetime(calendar_file.read_text().splitlines()))
    if not calendar.is_unique or not calendar.is_monotonic_increasing:
        raise ValueError("provider calendar must be unique and ordered")
    nominal = {name: tuple(pd.Timestamp(v) for v in getattr(args, name))
               for name in ("train", "valid", "test")}
    if not (nominal["train"][0] <= nominal["train"][1] < nominal["valid"][0]
            <= nominal["valid"][1] < nominal["test"][0] <= nominal["test"][1]):
        raise ValueError("train/valid/test must be ordered and disjoint")
    segments = {}
    for name, (start, end) in nominal.items():
        days = calendar[(calendar >= start) & (calendar <= end)]
        if start not in calendar or end not in calendar or len(days) < 4:
            raise ValueError(f"{name} needs provider session bounds and at least four sessions")
        if name == "test" and len(days) > 30:
            raise ValueError("test is limited to 30 sessions")
        segments[name] = (start, days[-3] if name != "test" else end)
    if calendar.get_loc(nominal["test"][1]) + 2 >= len(calendar):
        raise ValueError("test labels need two following provider sessions")
    files = [calendar_file, *sorted((provider / "instruments").glob("*.txt"))]
    for symbol in sorted(set(symbols + [args.benchmark])):
        fields = FIELDS if symbol in symbols else ("close",)
        for field in fields:
            path = provider / "features" / symbol.lower() / f"{field}.day.bin"
            if not path.is_file():
                raise FileNotFoundError(f"missing input field: {path}")
            files.append(path)
    return provider, output, symbols, calendar, nominal, segments, files


def run(args):
    provider, output, symbols, calendar, nominal, segments, files = prepare(args)
    before = {str(p.relative_to(provider)): sha256_file(p) for p in files}
    inventory = provider_inventory(provider)
    output.mkdir(parents=True)
    (output / "provider-inventory.json").write_bytes(canonical_json_bytes(inventory))
    receipt = {"schema": "myquant.chip-pipeline-acceptance/1", "status": "FAIL",
               "input_kind": args.input_kind, "provider": str(provider),
               "requested_handler": args.handler,
               "label": "Ref($open, -2)/Ref($open, -1) - 1",
               "source": capture_git_provenance(ROOT),
               "nominal_segments": {k: [str(v.date()) for v in val] for k, val in nominal.items()},
               "fit_segments": {k: [str(v.date()) for v in val] for k, val in segments.items()},
               "input_sha256": before,
               "limitations": ["Pipeline acceptance only; no profitability claim or production admission.",
                               "Market input availability and PIT quality are not proven by this runner."]}
    try:
        from my_scripts import host_env  # noqa: F401
        import qlib
        from qlib.data.dataset import DatasetH
        from qlib.data.dataset.handler import DataHandlerLP
        from myquant_factors import cyq_ops, turnover_coefficient_ops
        from my_scripts.chip_research.factor_expr import Chips, TurnCoeffChips
        from my_scripts.chip_research.qlib_workflow import run_model
        from my_scripts.export_daily_pool import export_daily_pool, load_predictions

        names = Chips.__new__(Chips).get_feature_config()[1]
        ops = [getattr(cyq_ops, n) for n in names]
        ops += [getattr(turnover_coefficient_ops, n) for n in ("ARC", "VRC", "SRC", "KRC")]
        qlib.init(provider_uri=str(provider), region="cn", kernels=1,
                  expression_cache=None, dataset_cache=None, custom_ops=ops,
                  exp_manager={"class": "MLflowExpManager", "module_path": "qlib.workflow.expm",
                               "kwargs": {"uri": (output / "mlruns").as_uri(),
                                          "default_exp_name": "chip_acceptance"}})
        handler_cls = {"Chips": Chips, "TurnCoeffChips": TurnCoeffChips}[args.handler]
        handler = handler_cls(instruments=symbols, start_time=nominal["train"][0],
                              end_time=nominal["test"][1], fit_start_time=nominal["train"][0],
                              fit_end_time=segments["train"][1])
        dataset = DatasetH(handler=handler, segments=segments)
        rows = {}
        for name in segments:
            frame = dataset.prepare(name, col_set=["feature", "label"], data_key=DataHandlerLP.DK_L)
            features = frame["feature"].to_numpy()
            if frame.empty or not np.isfinite(features).all() or not np.any(np.ptp(features, axis=0) > 0):
                raise ValueError(f"{name}: empty, non-finite or constant features")
            dates = frame.index.get_level_values("datetime")
            if name != "test":
                last_label_pos = calendar.get_indexer(dates).max() + 2
                if calendar[last_label_pos] > nominal[name][1]:
                    raise ValueError(f"{name}: prepared labels cross the nominal boundary")
            frame.to_parquet(output / f"{name}-prepared.parquet")
            rows[name] = len(frame)
        port_config = {
            "strategy": {"class": "TopkDropoutStrategy", "module_path": "qlib.contrib.strategy",
                         "kwargs": {"signal": "<PRED>", "topk": 2, "n_drop": 1,
                                    "only_tradable": True, "risk_degree": 0.8}},
            "backtest": {"start_time": args.test[0], "end_time": args.test[1], "account": 1000000,
                         "benchmark": args.benchmark,
                         "exchange_kwargs": {"freq": "day", "deal_price": "open",
                                             "limit_threshold": 0.095, "open_cost": 0.0005,
                                             "close_cost": 0.0015, "min_cost": 5, "trade_unit": 100}},
        }
        result = run_model(dataset, "gbdt", *args.test, experiment_name="chip_acceptance",
                           model_kw={"num_threads": 2, "num_boost_round": 20,
                                     "early_stopping_rounds": 5, "num_leaves": 7, "max_depth": 3,
                                     "lambda_l1": 0, "lambda_l2": 0},
                           port_analysis_config=port_config)
        recorder = result["recorder"]
        predictions = recorder.load_object("pred.pkl")
        if predictions.empty or not np.isfinite(predictions.to_numpy()).all():
            raise ValueError("predictions must be nonempty and finite")
        predictions.to_pickle(output / "pred.pkl")
        report = recorder.load_object("portfolio_analysis/report_normal_1day.pkl")
        if not np.isfinite(report[["return", "cost", "bench"]].to_numpy()).all() or report["cost"].sum() <= 0:
            raise ValueError("backtest must have finite results and actual charged trades")
        report.to_parquet(output / "backtest.parquet")
        sessions = []
        pools, scores, illegal = export_daily_pool(load_predictions(output / "pred.pkl"),
                                                   output / "signals", topk=2, bundle_sessions=sessions)
        if illegal or not pools or len(pools) != len(scores):
            raise ValueError("signal export missing or invalid")
        bundle = build_signal_bundle([
            {"signal_asof": asof, "target_session": target, "pool_file": path.name,
             "pool_md5": md5_file(path), "pool_sha256": sha256_file(path)}
            for asof, target, path in sessions
        ], price_domain=args.price_domain)
        validate_signal_bundle(bundle, files_root=output / "signals")
        (output / "signals/signal-bundle.json").write_bytes(canonical_json_bytes(bundle))
        receipt.update(status="PASS", handler=args.handler, instruments=symbols, rows=rows,
                       predictions=len(predictions), pool_files=len(pools), recorder_id=recorder.id,
                       model_parameters=recorder.load_object("trained_model.pkl").params,
                       port_analysis_config=port_config,
                       source_files={str(p.relative_to(ROOT)): sha256_file(p) for p in [
                           Path(__file__), Path(__file__).with_name("qlib_workflow.py"),
                           Path(__file__).with_name("factor_expr.py"),
                           ROOT / "myquant_factors/cyq_ops.py",
                           ROOT / "myquant_factors/turnover_coefficient_ops.py"]})
    except Exception as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        receipt["provider_unchanged"] = (provider_inventory(provider) == inventory and all(
            p.exists() and sha256_file(p) == before[str(p.relative_to(provider))] for p in files))
        if not receipt["provider_unchanged"]:
            receipt["status"] = "FAIL"
        receipt["artifact_sha256"] = {str(p.relative_to(output)): sha256_file(p)
                                      for p in sorted(output.rglob("*")) if p.is_file()}
        (output / "acceptance.json").write_bytes(canonical_json_bytes(receipt))
    if receipt["status"] != "PASS":
        raise RuntimeError("acceptance failed; see acceptance.json")
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--input-kind", choices=["synthetic", "market"], required=True)
    parser.add_argument("--instruments", required=True, help="3..12 comma-separated Qlib codes")
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--handler", choices=["Chips", "TurnCoeffChips"], default="Chips")
    parser.add_argument("--price-domain", choices=["none", "front", "back", "unspecified"], default="unspecified")
    for name in ("train", "valid", "test"):
        parser.add_argument(f"--{name}", nargs=2, required=True, metavar=("START", "END"))
    run(parser.parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
