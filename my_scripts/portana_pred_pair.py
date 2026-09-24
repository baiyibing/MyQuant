# -*- coding: utf-8 -*-
"""T5-DSTR1 C-gate: paired 10/3 PortAna for control vs candidate preds."""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import host_env  # noqa: F401
import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

SEED = 20260918
CONTROL_RECORDER = "8a061ea428e04bb3a199a485ade49d0e"
EXPERIMENT = "alpha158_cost_kdj_lgb"
FEATURE = "DOWNSTREAK5_RANK"
LABEL_NOTE = "full-universe pred; not A/B common-sample"


def fail(msg: str, code: int = 2) -> int:
    print(f"[FAIL] {msg}", flush=True)
    return code


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--control-recorder", required=True)
    p.add_argument("--candidate-recorder", required=True)
    p.add_argument("--control-pred-2025", type=Path, required=True)
    p.add_argument("--candidate-pred-2025", type=Path, required=True)
    p.add_argument("--control-pred-2026", type=Path, default=None)
    p.add_argument("--candidate-pred-2026", type=Path, default=None)
    p.add_argument("--window", action="append", required=True)
    p.add_argument("--topk", type=int, default=10)
    p.add_argument("--n-drop", type=int, default=3)
    p.add_argument("--hold-thresh", type=int, default=1)
    p.add_argument("--open-cost", type=float, default=0.0005)
    p.add_argument("--close-cost", type=float, default=0.0015)
    p.add_argument("--min-cost", type=float, default=5)
    p.add_argument("--account", type=float, default=1e8)
    p.add_argument("--risk-degree", type=float, default=0.95)
    p.add_argument("--benchmark", default="SH000300")
    p.add_argument("--all-buy-gates-off", action="store_true")
    p.add_argument("--all-price-exits-off", action="store_true")
    p.add_argument("--block-days", type=int, default=5)
    p.add_argument("--bootstrap-reps", type=int, default=10000)
    p.add_argument("--seed", type=int, default=SEED)
    p.add_argument("--provider-uri", default=r"C:/Users/wangc/.qlib/qlib_data/my_data")
    p.add_argument("--mlruns-dir", type=Path, default=SCRIPT_DIR / "mlruns")
    p.add_argument("--control-experiment", default=EXPERIMENT)
    p.add_argument("--lineage", type=Path, default=None)
    p.add_argument("--sidecar-sha256", default=None)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--fail-if-out-exists", action="store_true")
    return p


def load_pred(path: Path) -> pd.Series:
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    dt = cols.get("datetime") or cols.get("date")
    inst = cols.get("instrument") or cols.get("asset")
    score = cols.get("score") or cols.get("pred")
    out = df[[dt, inst, score]].copy()
    out.columns = ["datetime", "instrument", "score"]
    out["datetime"] = pd.to_datetime(out["datetime"])
    out["instrument"] = out["instrument"].astype(str)
    ser = out.set_index(["datetime", "instrument"])["score"].sort_index()
    ser = ser[~ser.index.duplicated(keep="last")]
    return ser


def load_pred_from_recorder(provider_uri, mlruns_dir, recorder_id, experiment) -> pd.Series:
    import qlib
    from qlib.config import REG_CN
    from qlib.workflow import R

    qlib.init(
        provider_uri=str(Path(os.path.expanduser(provider_uri)).resolve()),
        region=REG_CN,
        kernels=1,
        exp_manager={
            "class": "MLflowExpManager",
            "module_path": "qlib.workflow.expm",
            "kwargs": {"uri": str(Path(mlruns_dir).expanduser().resolve()), "default_exp_name": "MyExperiment"},
        },
    )
    rec = R.get_recorder(recorder_id=recorder_id, experiment_name=experiment)
    obj = rec.load_object("pred.pkl")
    if isinstance(obj, pd.Series):
        ser = obj.copy()
        ser.name = "score"
    else:
        frame = obj.reset_index() if isinstance(obj.index, pd.MultiIndex) else obj.copy()
        if "score" not in frame.columns:
            cands = [c for c in frame.columns if c not in {"datetime", "instrument"}]
            frame = frame.rename(columns={cands[0]: "score"})
        ser = frame.set_index(["datetime", "instrument"])["score"]
    ser.index = ser.index.set_names(["datetime", "instrument"])
    ser = ser.sort_index()
    ser = ser[~ser.index.duplicated(keep="last")]
    return ser


def run_portana(pred: pd.Series, start: str, end: str, args) -> dict:
    from qlib.contrib.evaluate import backtest_daily, risk_analysis
    from qlib.contrib.strategy import TopkDropoutStrategy

    kw = dict(
        signal=pred,
        topk=int(args.topk),
        n_drop=int(args.n_drop),
        hold_thresh=int(args.hold_thresh),
    )
    try:
        strategy = TopkDropoutStrategy(**kw, risk_degree=float(args.risk_degree))
    except TypeError:
        strategy = TopkDropoutStrategy(**kw)
        if hasattr(strategy, "risk_degree"):
            strategy.risk_degree = float(args.risk_degree)
    report_normal, _positions = backtest_daily(
        start_time=start,
        end_time=end,
        strategy=strategy,
        account=float(args.account),
        benchmark=args.benchmark,
        exchange_kwargs={
            "freq": "day",
            "limit_threshold": 0.095,
            "deal_price": "close",
            "open_cost": float(args.open_cost),
            "close_cost": float(args.close_cost),
            "min_cost": float(args.min_cost),
        },
    )
    analysis = risk_analysis(report_normal["return"] - report_normal["bench"])
    analysis_with = risk_analysis(report_normal["return"] - report_normal["bench"] - report_normal["cost"])
    net = (report_normal["return"] - report_normal["cost"]).fillna(0.0)
    nav = (1.0 + net).cumprod()
    end_nav = float(nav.iloc[-1]) if len(nav) else float("nan")
    period_ret = float(nav.iloc[-1] - 1.0) if len(nav) else float("nan")
    turnover = float(report_normal["turnover"].sum()) if "turnover" in report_normal.columns else float("nan")
    cost_sum = float(report_normal["cost"].sum()) if "cost" in report_normal.columns else float("nan")
    mdd = float("nan")
    if "max_drawdown" in analysis_with.index:
        mdd = float(analysis_with.loc["max_drawdown", "risk"])
    excess_ann = float("nan")
    if "annualized_return" in analysis_with.index:
        excess_ann = float(analysis_with.loc["annualized_return", "risk"])
    excess_ann_raw = float("nan")
    if "annualized_return" in analysis.index:
        excess_ann_raw = float(analysis.loc["annualized_return", "risk"])
    return {
        "end_nav": end_nav,
        "period_return": period_ret,
        "excess_ann_with_cost": excess_ann,
        "excess_ann_without_cost": excess_ann_raw,
        "max_drawdown_with_cost": mdd,
        "turnover_sum": turnover,
        "cost_sum": cost_sum,
        "daily_net": net,
        "report": report_normal,
    }


def moving_block_bootstrap_ci(values, *, block_days, reps, seed):
    sample = np.asarray(list(values), dtype=float)
    sample = sample[np.isfinite(sample)]
    if len(sample) < block_days:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    block_count = math.ceil(len(sample) / block_days)
    last_start = len(sample) - block_days
    estimates = np.empty(reps)
    offsets = np.arange(block_days)
    for i in range(reps):
        starts = rng.integers(0, last_start + 1, size=block_count)
        idx = (starts[:, None] + offsets[None, :]).ravel()[: len(sample)]
        estimates[i] = float(sample[idx].mean())
    lo, hi = np.quantile(estimates, [0.025, 0.975])
    return float(sample.mean()), float(lo), float(hi)


def quarter_delta_flags(daily_ctrl: pd.Series, daily_cand: pd.Series) -> dict:
    idx = daily_ctrl.index.union(daily_cand.index)
    r0 = daily_ctrl.reindex(idx).fillna(0.0)
    r1 = daily_cand.reindex(idx).fillna(0.0)
    work = pd.DataFrame({"ctrl": r0, "cand": r1})
    work["quarter"] = work.index.to_period("Q")
    qmap = {}
    for q, g in work.groupby("quarter", sort=True):
        c0 = float((1.0 + g["ctrl"]).prod() - 1.0)
        c1 = float((1.0 + g["cand"]).prod() - 1.0)
        qmap[str(q)] = float(c1 - c0)
    if not qmap:
        return {"majority_negative": True, "single_quarter_driven": True, "quarters": {}}
    neg = sum(1 for v in qmap.values() if v < 0)
    majority_negative = (neg / max(len(qmap), 1)) > 0.5
    total = float(sum(qmap.values()))
    pos_q = sum(1 for v in qmap.values() if v > 0)
    single = bool(total > 0 and pos_q <= 1)
    return {
        "majority_negative": majority_negative,
        "single_quarter_driven": single,
        "quarters": qmap,
        "sum": total,
    }


def main(argv=None) -> int:
    import qlib
    from qlib.constant import REG_CN

    args = build_parser().parse_args(argv)
    if int(args.topk) != 10 or int(args.n_drop) != 3 or int(args.hold_thresh) != 1:
        return fail("C is frozen at 10/3 hold_thresh=1")
    if not args.all_buy_gates_off or not args.all_price_exits_off:
        return fail("C requires --all-buy-gates-off --all-price-exits-off")
    if args.control_recorder != CONTROL_RECORDER:
        return fail(f"control-recorder must stay {CONTROL_RECORDER}")
    if args.benchmark != "SH000300":
        return fail("C benchmark must stay SH000300")
    if int(args.block_days) != 5 or int(args.bootstrap_reps) != 10000 or int(args.seed) != SEED:
        return fail("bootstrap is frozen at 5 / 10000 / 20260918")

    lineage_path = args.lineage
    if lineage_path is None:
        auto = args.candidate_pred_2025.expanduser().resolve().parent / "lineage.json"
        if auto.is_file():
            lineage_path = auto
    lineage = None
    if lineage_path is not None:
        lineage = json.loads(Path(lineage_path).expanduser().resolve().read_text(encoding="utf-8"))
        if str(lineage.get("candidate_recorder")) != str(args.candidate_recorder):
            return fail("lineage candidate_recorder mismatch")
        if args.sidecar_sha256 and str(lineage.get("sidecar_sha256", "")).lower() != args.sidecar_sha256.lower():
            return fail("C lineage sidecar SHA mismatch vs B recorder bloodline")
        if lineage.get("only_extra_feature") != FEATURE:
            return fail("C lineage is not DOWNSTREAK5_RANK-only")
    elif args.sidecar_sha256:
        return fail("C requires B lineage.json to verify sidecar SHA bloodline")

    out: Path = args.out_dir.expanduser().resolve()
    if args.fail_if_out_exists and out.exists():
        return fail(f"out-dir exists: {out}")
    out.mkdir(parents=True, exist_ok=False)

    windows = []
    for i, w in enumerate(args.window):
        a, b = w.split(":", 1)
        name = "2025_valid" if i == 0 else ("2026_oos" if i == 1 else f"w{i}")
        windows.append((name, a.strip(), b.strip()))

    print("[init] qlib", flush=True)
    qlib.init(provider_uri=str(args.provider_uri), region=REG_CN, kernels=1)

    ctrl25 = load_pred(args.control_pred_2025)
    cand25 = load_pred(args.candidate_pred_2025)
    cand26_path = args.candidate_pred_2026
    if cand26_path is None:
        cand26_path = args.candidate_pred_2025.expanduser().resolve().parent / "pred_2026.csv"
    cand26 = load_pred(cand26_path)
    if args.control_pred_2026 is not None and args.control_pred_2026.expanduser().is_file():
        ctrl26 = load_pred(args.control_pred_2026)
    else:
        print("[load] control 2026 from recorder pred.pkl (read-only)", flush=True)
        ctrl26 = load_pred_from_recorder(
            args.provider_uri, args.mlruns_dir, args.control_recorder, args.control_experiment
        )

    results = []
    for name, start, end in windows:
        ctrl = ctrl25 if name.startswith("2025") else ctrl26
        cand = cand25 if name.startswith("2025") else cand26
        print(f"[portana] {name} control", flush=True)
        r0 = run_portana(ctrl, start, end, args)
        print(f"[portana] {name} candidate", flush=True)
        r1 = run_portana(cand, start, end, args)
        d_net = (r1["daily_net"] - r0["daily_net"]).dropna()
        d_period = float(r1["period_return"] - r0["period_return"])
        pe, lo, hi = moving_block_bootstrap_ci(
            d_net.to_numpy(), block_days=args.block_days, reps=args.bootstrap_reps, seed=args.seed
        )
        qflags = quarter_delta_flags(r0["daily_net"], r1["daily_net"])
        is26 = name.startswith("2026")
        row = {
            "window": name,
            "start": start,
            "end": end,
            "control_end_nav": r0["end_nav"],
            "candidate_end_nav": r1["end_nav"],
            "control_period_return": r0["period_return"],
            "candidate_period_return": r1["period_return"],
            "delta_net_return": d_period,
            "control_excess_ann_with_cost": r0["excess_ann_with_cost"],
            "candidate_excess_ann_with_cost": r1["excess_ann_with_cost"],
            "control_max_drawdown_with_cost": r0["max_drawdown_with_cost"],
            "candidate_max_drawdown_with_cost": r1["max_drawdown_with_cost"],
            "control_turnover_sum": r0["turnover_sum"],
            "candidate_turnover_sum": r1["turnover_sum"],
            "control_cost_sum": r0["cost_sum"],
            "candidate_cost_sum": r1["cost_sum"],
            "delta_daily_mean": pe,
            "delta_daily_ci_lo": lo,
            "delta_daily_ci_hi": hi,
            "quarters": qflags,
            "pass_delta_gt0": bool(d_period > 0),
            "pass_excess_rank": bool(r1["excess_ann_with_cost"] > r0["excess_ann_with_cost"]),
            "pass_ci": bool(lo > 0) if is26 else True,
            "pass_quarters": ((not qflags["majority_negative"]) and (not qflags["single_quarter_driven"]))
            if is26
            else True,
        }
        results.append(row)
        d_net.to_csv(out / f"daily_delta_net_{name}.csv", header=["delta_net"], encoding="utf-8")

    by = {r["window"]: r for r in results}
    r25, r26 = by["2025_valid"], by["2026_oos"]
    c_pass = (
        r25["pass_delta_gt0"]
        and r25["pass_excess_rank"]
        and r26["pass_delta_gt0"]
        and r26["pass_excess_rank"]
        and r26["pass_ci"]
        and r26["pass_quarters"]
    )
    flip = (r25["delta_net_return"] > 0) != (r26["delta_net_return"] > 0) or r26["quarters"]["majority_negative"]
    if c_pass:
        label = "DSTR_FEATURE_CANDIDATE"
    elif flip:
        label = "DSTR_PORTANA_FLIP"
    else:
        label = "DSTR_PORTANA_NO_EDGE"

    verdict = {
        "verdict": label,
        "c_pass": c_pass,
        "control_recorder": args.control_recorder,
        "candidate_recorder": args.candidate_recorder,
        "note": LABEL_NOTE,
        "lineage": lineage,
        "windows": results,
        "online_untouched": True,
    }
    (out / "verdict.json").write_text(json.dumps(verdict, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"verdict": label, "c_pass": c_pass}, ensure_ascii=False), flush=True)
    return 0 if c_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
