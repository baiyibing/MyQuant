# -*- coding: utf-8 -*-
"""T5-DSTR1 B-gate: RankIC + Top10Spread pair diagnostics vs control 8a061ea4."""
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

LABEL = "Ref($close,-2)/Ref($close,-1)-1"
SEED = 20260918
BLOCK = 5
BOOT = 10000
CONTROL_RECORDER = "8a061ea428e04bb3a199a485ade49d0e"
EXPERIMENT = "alpha158_cost_kdj_lgb"


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
    p.add_argument("--label", default=LABEL)
    p.add_argument("--topk", type=int, default=10)
    p.add_argument("--top10-spread-vs", default="common-universe-equal-weight")
    p.add_argument("--window", action="append", required=True)
    p.add_argument("--block-days", type=int, default=BLOCK)
    p.add_argument("--bootstrap-reps", type=int, default=BOOT)
    p.add_argument("--seed", type=int, default=SEED)
    p.add_argument("--provider-uri", default=r"C:/Users/wangc/.qlib/qlib_data/my_data")
    p.add_argument("--mlruns-dir", type=Path, default=SCRIPT_DIR / "mlruns")
    p.add_argument("--control-experiment", default=EXPERIMENT)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--fail-if-out-exists", action="store_true")
    return p


def load_pred(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    dt = cols.get("datetime") or cols.get("date")
    inst = cols.get("instrument") or cols.get("asset") or cols.get("symbol")
    score = cols.get("score") or cols.get("pred") or cols.get("prediction")
    if not (dt and inst and score):
        raise ValueError(f"pred columns missing in {path}: {df.columns.tolist()}")
    out = df[[dt, inst, score]].copy()
    out.columns = ["datetime", "instrument", "score"]
    out["datetime"] = pd.to_datetime(out["datetime"]).dt.normalize()
    out["instrument"] = out["instrument"].astype(str)
    out["score"] = pd.to_numeric(out["score"], errors="coerce")
    return out.dropna(subset=["score"])


def load_pred_from_recorder(provider_uri, mlruns_dir, recorder_id, experiment) -> pd.DataFrame:
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
        frame = obj.rename("score").reset_index()
    else:
        frame = obj.reset_index() if isinstance(obj.index, pd.MultiIndex) else obj.copy()
    if "score" not in frame.columns:
        cands = [c for c in frame.columns if c not in {"datetime", "instrument"}]
        frame = frame.rename(columns={cands[0]: "score"})
    out = frame[["datetime", "instrument", "score"]].copy()
    out["datetime"] = pd.to_datetime(out["datetime"]).dt.normalize()
    out["instrument"] = out["instrument"].astype(str)
    out["score"] = pd.to_numeric(out["score"], errors="coerce")
    return out.dropna(subset=["score"])


def load_labels(instruments: list[str], start: str, end: str, label: str) -> pd.DataFrame:
    from qlib.data import D

    raw = D.features(list(instruments), [label], start_time=start, end_time=end)
    if raw is None or raw.empty:
        raise RuntimeError(f"D.features empty for {start}:{end}")
    frame = raw.reset_index() if isinstance(raw.index, pd.MultiIndex) else raw.copy()
    if label not in frame.columns:
        values = [c for c in frame.columns if c not in {"datetime", "instrument"}]
        if len(values) != 1:
            raise ValueError(f"unexpected label columns: {list(frame.columns)}")
        frame = frame.rename(columns={values[0]: label})
    out = frame.loc[:, ["datetime", "instrument", label]].copy()
    out = out.rename(columns={label: "label"})
    out["datetime"] = pd.to_datetime(out["datetime"]).dt.normalize()
    out["instrument"] = out["instrument"].astype(str)
    out["label"] = pd.to_numeric(out["label"], errors="coerce")
    return out


def daily_rankic(df: pd.DataFrame) -> pd.Series:
    def _one(g: pd.DataFrame) -> float:
        if len(g) < 4:
            return np.nan
        return float(g["score"].corr(g["label"], method="spearman"))

    return df.groupby("datetime", sort=True).apply(_one, include_groups=False)


def daily_top10_spread(df: pd.DataFrame, topk: int = 10) -> pd.Series:
    """Equal-weight TopK minus equal-weight of the common universe. Not Top-Bottom."""

    def _one(g: pd.DataFrame) -> float:
        if len(g) < topk:
            return np.nan
        g = g.sort_values("score", ascending=False)
        top = g.head(topk)["label"].mean()
        univ = g["label"].mean()
        return float(top - univ)

    return df.groupby("datetime", sort=True).apply(_one, include_groups=False)


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


def quarter_flags(daily: pd.Series) -> dict:
    s = daily.dropna()
    if s.empty:
        return {"majority_negative": True, "single_quarter_driven": True, "quarters": {}}
    q = s.groupby(s.index.to_period("Q")).mean()
    qmap = {str(k): float(v) for k, v in q.items()}
    neg = sum(1 for v in qmap.values() if v < 0)
    majority_negative = (neg / max(len(qmap), 1)) > 0.5
    total = float(s.mean())
    pos_q = sum(1 for v in qmap.values() if v > 0)
    single = bool(total > 0 and pos_q <= 1)
    return {
        "majority_negative": majority_negative,
        "single_quarter_driven": single,
        "quarters": qmap,
        "mean": total,
    }


def evaluate_window(name, start, end, ctrl, cand, labels, topk, block, reps, seed):
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    lab = labels[(labels["datetime"] >= s) & (labels["datetime"] <= e)]
    c0 = ctrl[(ctrl["datetime"] >= s) & (ctrl["datetime"] <= e)]
    c1 = cand[(cand["datetime"] >= s) & (cand["datetime"] <= e)]
    m0 = c0.merge(lab, on=["datetime", "instrument"], how="inner")
    m1 = c1.merge(lab, on=["datetime", "instrument"], how="inner")
    keys = set(zip(m0["datetime"], m0["instrument"])) & set(zip(m1["datetime"], m1["instrument"]))
    if not keys:
        raise RuntimeError(f"{name}: empty common sample")
    key_df = pd.DataFrame(list(keys), columns=["datetime", "instrument"])
    m0 = m0.merge(key_df, on=["datetime", "instrument"])
    m1 = m1.merge(key_df, on=["datetime", "instrument"])

    ric0 = daily_rankic(m0)
    ric1 = daily_rankic(m1)
    sp0 = daily_top10_spread(m0, topk=topk)
    sp1 = daily_top10_spread(m1, topk=topk)
    d_ric = (ric1 - ric0).dropna()
    mean0, mean1 = float(ric0.mean()), float(ric1.mean())
    spm0, spm1 = float(sp0.mean()), float(sp1.mean())
    pe, lo, hi = moving_block_bootstrap_ci(d_ric.to_numpy(), block_days=block, reps=reps, seed=seed)
    qflags = quarter_flags(d_ric)
    is26 = name.startswith("2026")
    return {
        "window": name,
        "start": start,
        "end": end,
        "n_common_rows": int(len(m0)),
        "n_common_days_ric": int(d_ric.shape[0]),
        "rankic_control": mean0,
        "rankic_candidate": mean1,
        "rankic_delta": float(mean1 - mean0),
        "top10_control": spm0,
        "top10_candidate": spm1,
        "top10_delta": float(spm1 - spm0),
        "top10_spread_vs": "common-universe-equal-weight",
        "delta_rankic_ci": {"point": pe, "lo": lo, "hi": hi},
        "quarters": qflags,
        "pass_rankic": bool(mean1 > mean0),
        "pass_top10": bool(spm1 > spm0),
        "pass_ci": bool(lo > 0) if is26 else True,
        "pass_quarters": ((not qflags["majority_negative"]) and (not qflags["single_quarter_driven"]))
        if is26
        else True,
    }


def main(argv=None) -> int:
    import qlib
    from qlib.constant import REG_CN

    args = build_parser().parse_args(argv)
    if args.label != LABEL:
        return fail(f"label must stay frozen: {LABEL}")
    if int(args.topk) != 10:
        return fail("topk must stay 10")
    if args.top10_spread_vs != "common-universe-equal-weight":
        return fail("top10-spread-vs must be common-universe-equal-weight")
    if args.control_recorder != CONTROL_RECORDER:
        return fail(f"control-recorder must stay {CONTROL_RECORDER}")
    if int(args.block_days) != BLOCK or int(args.bootstrap_reps) != BOOT or int(args.seed) != SEED:
        return fail("bootstrap is frozen at 5 / 10000 / 20260918")

    out: Path = args.out_dir.expanduser().resolve()
    if args.fail_if_out_exists and out.exists():
        return fail(f"out-dir exists: {out}")
    out.mkdir(parents=True, exist_ok=False)

    windows = []
    for i, w in enumerate(args.window):
        a, b = w.split(":", 1)
        name = "2025_valid" if i == 0 else ("2026_oos" if i == 1 else f"w{i}")
        windows.append((name, a.strip(), b.strip()))

    ctrl25 = load_pred(args.control_pred_2025)
    cand25 = load_pred(args.candidate_pred_2025)
    cand26_path = args.candidate_pred_2026
    if cand26_path is None:
        cand26_path = args.candidate_pred_2025.expanduser().resolve().parent / "pred_2026.csv"
    cand26 = load_pred(cand26_path)

    print("[init] qlib", flush=True)
    qlib.init(provider_uri=str(args.provider_uri), region=REG_CN, kernels=1)
    if args.control_pred_2026 is not None and args.control_pred_2026.expanduser().is_file():
        ctrl26 = load_pred(args.control_pred_2026)
    else:
        print("[load] control 2026 from recorder pred.pkl (read-only)", flush=True)
        ctrl26 = load_pred_from_recorder(
            args.provider_uri, args.mlruns_dir, args.control_recorder, args.control_experiment
        )

    start_all = min(w[1] for w in windows)
    end_all = max(w[2] for w in windows)
    print(f"[labels] {start_all}..{end_all}", flush=True)
    instruments = sorted(
        set(ctrl25["instrument"]) | set(cand25["instrument"]) | set(ctrl26["instrument"]) | set(cand26["instrument"])
    )
    labels = load_labels(instruments, start_all, end_all, args.label)

    results = []
    for name, start, end in windows:
        ctrl = ctrl25 if name.startswith("2025") else ctrl26
        cand = cand25 if name.startswith("2025") else cand26
        print(f"[eval] {name}", flush=True)
        results.append(
            evaluate_window(
                name, start, end, ctrl, cand, labels, args.topk, args.block_days, args.bootstrap_reps, args.seed
            )
        )

    by = {r["window"]: r for r in results}
    r25, r26 = by["2025_valid"], by["2026_oos"]
    b_pass = (
        r25["pass_rankic"]
        and r25["pass_top10"]
        and r26["pass_rankic"]
        and r26["pass_top10"]
        and r26["pass_ci"]
        and r26["pass_quarters"]
    )
    verdict = {
        "verdict": "B_GATE_PASS" if b_pass else "DSTR_MODEL_NO_TRANSFER",
        "b_pass": b_pass,
        "control_recorder": args.control_recorder,
        "candidate_recorder": args.candidate_recorder,
        "windows": results,
        "online_untouched": True,
    }
    (out / "verdict.json").write_text(json.dumps(verdict, indent=2, default=str), encoding="utf-8")
    pd.DataFrame(
        [
            {
                "window": r["window"],
                "rankic_control": r["rankic_control"],
                "rankic_candidate": r["rankic_candidate"],
                "rankic_delta": r["rankic_delta"],
                "top10_control": r["top10_control"],
                "top10_candidate": r["top10_candidate"],
                "ci_lo": r["delta_rankic_ci"]["lo"],
                "ci_hi": r["delta_rankic_ci"]["hi"],
            }
            for r in results
        ]
    ).to_csv(out / "window_summary.csv", index=False, encoding="utf-8")
    print(json.dumps({"verdict": verdict["verdict"], "b_pass": b_pass}, ensure_ascii=False), flush=True)
    return 0 if b_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
