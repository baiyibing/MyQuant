# -*- coding: utf-8 -*-
"""T5-AMI1 A-gate: AMIHUD partial RankIC controlling frozen 8a061ea4 score."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import host_env  # noqa: F401

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
REPO_ROOT = SCRIPT_DIR.parent
RECORDER_ID = "8a061ea428e04bb3a199a485ade49d0e"
EXPERIMENT = "alpha158_cost_kdj_lgb"
LABEL = "Ref($close,-2)/Ref($close,-1)-1"
DEFAULT_WINDOWS = (("2025-01-03", "2025-12-31"), ("2026-01-01", "2026-09-14"))
WINDOW_NAMES = ("2025_valid", "2026_oos")
BLOCK_DAYS = 5
BOOTSTRAP_REPS = 10_000
SEED = 20_260_918
MIN_COVERAGE = 0.98
FEATURE = "AMIHUD20_RANK"


def _load_runtime():
    global np, pd
    import numpy as np_module
    import pandas as pd_module

    np = np_module
    pd = pd_module


def parse_window(value: str):
    a, b = value.split(":", 1)
    return a.strip(), b.strip()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_identity(path: Path) -> dict[str, Any]:
    st = path.stat()
    return {
        "path": str(path.resolve()),
        "size_bytes": int(st.st_size),
        "mtime_utc": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        "sha256": _sha256(path),
    }


def _date_string(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return pd.Timestamp(value).date().isoformat()


def _key_digest(df) -> str:
    keys = (df["instrument"].astype(str) + "|" + df["datetime"].dt.strftime("%Y-%m-%d")).sort_values(
        kind="mergesort"
    )
    h = hashlib.sha256()
    for k in keys:
        h.update(k.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def build_parser():
    p = argparse.ArgumentParser()
    p.add_argument("--experiment", default=EXPERIMENT)
    p.add_argument("--recorder-id", default=RECORDER_ID)
    p.add_argument("--pred-2025", type=Path, default=SCRIPT_DIR / "预测结果_8a061ea4_2025valid.csv")
    p.add_argument("--sidecar", type=Path, required=True)
    p.add_argument("--sidecar-manifest", type=Path, required=True)
    p.add_argument("--sidecar-sha256", required=True)
    p.add_argument("--verify-key-digest", action="store_true")
    p.add_argument("--feature", default=FEATURE)
    p.add_argument("--control-score", action="store_true")
    p.add_argument("--label", default=LABEL)
    p.add_argument("--window", action="append", type=parse_window)
    p.add_argument("--min-coverage", type=float, default=MIN_COVERAGE)
    p.add_argument("--min-partial-n", type=int, default=4)
    p.add_argument("--block-days", type=int, default=BLOCK_DAYS)
    p.add_argument("--bootstrap-reps", type=int, default=BOOTSTRAP_REPS)
    p.add_argument("--seed", type=int, default=SEED)
    p.add_argument("--provider-uri", default=r"C:/Users/wangc/.qlib/qlib_data/my_data")
    p.add_argument("--mlruns-dir", type=Path, default=SCRIPT_DIR / "mlruns")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--fail-if-out-exists", action="store_true")
    p.add_argument(
        "--export-control-pred-2026",
        type=Path,
        default=None,
        help="Write a read-only copy of recorder pred.pkl (2026) for later B/C; never writes back to recorder.",
    )
    return p


def _normalize_scores(obj, source):
    if isinstance(obj, pd.Series):
        frame = obj.rename("score").reset_index()
    else:
        frame = obj.reset_index() if isinstance(obj.index, pd.MultiIndex) else obj.copy()
    if "score" not in frame.columns:
        cands = [c for c in frame.columns if c not in {"datetime", "instrument"}]
        frame = frame.rename(columns={cands[0]: "score"})
    if "datetime" not in frame.columns or "instrument" not in frame.columns:
        others = [c for c in frame.columns if c != "score"]
        rename = {}
        if "datetime" not in frame.columns:
            rename[others[0]] = "datetime"
        rem = [c for c in others if c not in rename]
        if "instrument" not in frame.columns:
            rename[rem[0]] = "instrument"
        frame = frame.rename(columns=rename)
    out = frame[["datetime", "instrument", "score"]].copy()
    out["datetime"] = pd.to_datetime(out["datetime"]).dt.normalize()
    out["instrument"] = out["instrument"].astype(str)
    out["score"] = pd.to_numeric(out["score"], errors="coerce")
    out = out.dropna(subset=["score"]).drop_duplicates(["datetime", "instrument"])
    return out.sort_values(["datetime", "instrument"], kind="mergesort").reset_index(drop=True)


def _load_2025(path: Path):
    return _normalize_scores(pd.read_csv(path), str(path)), _file_identity(path)


def _load_2026(provider_uri, mlruns_dir, recorder_id, experiment):
    import qlib
    from qlib.config import REG_CN
    from qlib.workflow import R

    provider = Path(os.path.expanduser(provider_uri)).resolve()
    store = mlruns_dir.expanduser().resolve()
    qlib.init(
        provider_uri=str(provider),
        region=REG_CN,
        kernels=1,
        exp_manager={
            "class": "MLflowExpManager",
            "module_path": "qlib.workflow.expm",
            "kwargs": {"uri": str(store), "default_exp_name": "MyExperiment"},
        },
    )
    rec = R.get_recorder(recorder_id=recorder_id, experiment_name=experiment)
    scores = _normalize_scores(rec.load_object("pred.pkl"), f"recorder:{recorder_id}")
    return scores, {"recorder_id": recorder_id, "mlruns_dir": str(store)}


def _ensure_qlib(provider_uri, mlruns_dir):
    import qlib
    from qlib.config import REG_CN

    qlib.init(
        provider_uri=str(Path(os.path.expanduser(provider_uri)).resolve()),
        region=REG_CN,
        kernels=1,
        exp_manager={
            "class": "MLflowExpManager",
            "module_path": "qlib.workflow.expm",
            "kwargs": {"uri": str(mlruns_dir.expanduser().resolve()), "default_exp_name": "MyExperiment"},
        },
    )


def _load_labels(instruments, start, end, label):
    from qlib.data import D

    raw = D.features(list(instruments), [label], start_time=start, end_time=end)
    frame = raw.reset_index() if isinstance(raw.index, pd.MultiIndex) else raw.copy()
    if label not in frame.columns:
        vals = [c for c in frame.columns if c not in {"datetime", "instrument"}]
        frame = frame.rename(columns={vals[0]: label})
    out = frame[["datetime", "instrument", label]].rename(columns={label: "label"})
    out["datetime"] = pd.to_datetime(out["datetime"]).dt.normalize()
    out["instrument"] = out["instrument"].astype(str)
    out["label"] = pd.to_numeric(out["label"], errors="coerce")
    return out


def _pct_rank(s):
    return s.rank(method="average", pct=True)


def _ols_resid(y, *cols):
    yv = np.asarray(y, dtype=float)
    X = np.column_stack([np.ones(len(yv))] + [np.asarray(c, dtype=float) for c in cols])
    beta, _, rank, _ = np.linalg.lstsq(X, yv, rcond=None)
    if rank < X.shape[1]:
        raise RuntimeError("rank_deficient")
    return yv - X @ beta


def _partial_day(day, feature, min_n):
    if len(day) < min_n:
        return float("nan"), "n_lt_min"
    s = _pct_rank(day["score"])
    y = _pct_rank(day["label"])
    a = day[feature]
    if s.nunique() < 2 or y.nunique() < 2 or a.nunique() < 2:
        return float("nan"), "zero_variance"
    try:
        ra = _ols_resid(a.to_numpy(), s.to_numpy())
        ry = _ols_resid(y.to_numpy(), s.to_numpy())
    except Exception:
        return float("nan"), "ols_fail"
    if not (np.isfinite(ra).all() and np.isfinite(ry).all()):
        return float("nan"), "resid_nonfinite"
    if np.nanstd(ra) <= 0 or np.nanstd(ry) <= 0:
        return float("nan"), "resid_zero_var"
    corr = float(np.corrcoef(ra, ry)[0, 1])
    if not np.isfinite(corr):
        return float("nan"), "corr_nonfinite"
    return corr, None


def moving_block_bootstrap_ci(values, *, block_days, reps, seed):
    sample = np.asarray(list(values), dtype=float)
    sample = sample[np.isfinite(sample)]
    if len(sample) < block_days:
        raise ValueError("too few days")
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
    return {
        "n_days": int(len(sample)),
        "block_days": block_days,
        "reps": reps,
        "seed": seed,
        "point_estimate": float(sample.mean()),
        "ci_lower": float(lo),
        "ci_upper": float(hi),
    }


def _series_stats(series):
    v = pd.to_numeric(series, errors="coerce").dropna()
    std = float(v.std(ddof=1)) if len(v) > 1 else float("nan")
    mean = float(v.mean()) if len(v) else float("nan")
    return {
        "n_days": int(len(v)),
        "mean": mean,
        "median": float(v.median()) if len(v) else float("nan"),
        "std": std,
        "icir": mean / std if np.isfinite(std) and std > 0 else float("nan"),
    }


def _quarter_stability(daily, col="partial_rankic"):
    work = daily.copy()
    work["quarter"] = pd.to_datetime(work["datetime"]).dt.to_period("Q").astype(str)
    rows = []
    for q, g in work.groupby("quarter", sort=True):
        rows.append({"quarter": q, **_series_stats(g[col])})
    means = [r["mean"] for r in rows if np.isfinite(r["mean"])]
    n_q = len(means)
    n_neg = sum(1 for m in means if m < 0)
    n_pos = sum(1 for m in means if m > 0)
    full = float(np.nanmean(means)) if means else float("nan")
    majority_negative = (n_neg / n_q > 0.5) if n_q else True
    single = bool(np.isfinite(full) and full > 0 and n_pos <= 1)
    return {
        "quarters": rows,
        "majority_negative": majority_negative,
        "single_quarter_driven": single,
        "passes": (not majority_negative) and (not single),
    }


def decide_verdict(windows, data_ok: bool):
    s0 = bool(data_ok) and all(w["coverage_pass"] for w in windows.values())
    m25 = windows["2025_valid"]["partial_rankic"]["mean"]
    m26 = windows["2026_oos"]["partial_rankic"]["mean"]
    ci_lo = windows["2026_oos"]["bootstrap"]["ci_lower"]
    q = windows["2026_oos"]["quarter_stability"]
    same_pos = bool(m25 > 0 and m26 > 0)
    flip = bool((m25 > 0) != (m26 > 0)) or bool(q.get("majority_negative"))
    s1 = bool(same_pos and ci_lo > 0 and q.get("passes"))
    if not s0:
        verdict = "AMIHUD_DATA_INVALID"
    elif flip:
        verdict = "AMIHUD_CONDITIONAL_FLIP"
    elif not s1:
        verdict = "AMIHUD_CONDITIONAL_NO_EDGE"
    else:
        verdict = "A_GATE_PASS"
    return {
        "verdict": verdict,
        "gates": {
            "S0": s0,
            "S1_means_gt0": same_pos,
            "S1_ci": bool(ci_lo > 0),
            "S1_quarters": bool(q.get("passes")),
            "S1_pass": bool(s0 and s1),
        },
        "means": {"2025_valid": m25, "2026_oos": m26},
        "ci_2026": windows["2026_oos"]["bootstrap"],
    }


def _json_safe(v):
    if isinstance(v, dict):
        return {str(k): _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return float(v) if np.isfinite(v) else None
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (pd.Timestamp, datetime, date)):
        return str(v)
    return v


def main(argv=None):
    args = build_parser().parse_args(argv)
    _load_runtime()
    if args.feature != FEATURE:
        raise ValueError(f"feature must be {FEATURE}")
    if not args.control_score:
        raise ValueError("--control-score is mandatory")
    if args.label != LABEL:
        raise ValueError(f"label must stay frozen: {LABEL}")

    out_dir = args.out_dir.expanduser().resolve()
    if args.fail_if_out_exists and out_dir.exists():
        raise FileExistsError(f"refuse to reuse existing out-dir {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=False)

    side = args.sidecar.expanduser().resolve()
    side_sha = _sha256(side)
    if side_sha.lower() != args.sidecar_sha256.lower():
        raise RuntimeError(f"sidecar SHA mismatch {side_sha} != {args.sidecar_sha256}")
    manifest = json.loads(args.sidecar_manifest.expanduser().resolve().read_text(encoding="utf-8"))
    if str(manifest.get("sidecar_sha256", "")).lower() != side_sha.lower():
        raise RuntimeError("manifest sidecar sha mismatch")

    sc = pd.read_parquet(side)
    required = {"instrument", "datetime", args.feature, "impact20", "close", "amount", "missing_reason"}
    missing = sorted(required - set(sc.columns))
    if missing:
        raise RuntimeError(f"sidecar missing columns {missing}")
    sc["datetime"] = pd.to_datetime(sc["datetime"]).dt.normalize()
    sc["instrument"] = sc["instrument"].astype(str)
    if int(sc.duplicated(["datetime", "instrument"]).sum()):
        raise RuntimeError("sidecar keys not unique")
    if args.verify_key_digest:
        got = _key_digest(sc)
        expected = manifest.get("key_digest")
        if not expected or got.lower() != str(expected).lower():
            raise RuntimeError(f"key digest mismatch {got} != {expected}")

    windows_cfg = list(DEFAULT_WINDOWS if args.window is None else args.window)
    windows = dict(zip(WINDOW_NAMES, windows_cfg))

    scores_2025, meta25 = _load_2025(args.pred_2025)
    scores_2026, meta26 = _load_2026(args.provider_uri, args.mlruns_dir, args.recorder_id, args.experiment)
    if args.export_control_pred_2026 is not None:
        exp_path = args.export_control_pred_2026.expanduser().resolve()
        if exp_path.exists():
            raise FileExistsError(f"refuse to overwrite {exp_path}")
        exp_path.parent.mkdir(parents=True, exist_ok=True)
        scores_2026.to_csv(exp_path, index=False, encoding="utf-8", lineterminator="\n")
        print(f"[export] control 2026 pred -> {exp_path} n={len(scores_2026)}", flush=True)

    daily_parts = []
    summaries = {}
    data_ok = True
    data_errors = []
    for name, (start, end) in windows.items():
        base = scores_2025 if name == "2025_valid" else scores_2026
        lo, hi = pd.Timestamp(start), pd.Timestamp(end)
        scores = base.loc[(base["datetime"] >= lo) & (base["datetime"] <= hi)].copy()
        _ensure_qlib(args.provider_uri, args.mlruns_dir)
        labels = _load_labels(sorted(scores["instrument"].unique()), start, end, args.label)
        merged = scores.merge(labels, on=["datetime", "instrument"], how="left")
        side_cols = [
            "datetime",
            "instrument",
            args.feature,
            "impact20",
            "close",
            "amount",
            "close_ok",
            "amount_ok",
            "window_complete",
            "missing_reason",
        ]
        side_cols = [c for c in side_cols if c in sc.columns]
        merged = merged.merge(sc[side_cols], on=["datetime", "instrument"], how="left")
        n_score = int(merged["score"].notna().sum())
        complete = merged.dropna(subset=["score", "label", args.feature])
        complete = complete.loc[np.isfinite(complete[args.feature])]
        coverage = len(complete) / n_score if n_score else 0.0
        close_miss = int((~merged.get("close_ok", True)).sum()) if "close_ok" in merged.columns else None
        amount_miss = int((~merged.get("amount_ok", True)).sum()) if "amount_ok" in merged.columns else None
        window_miss = (
            int((~merged.get("window_complete", True)).sum()) if "window_complete" in merged.columns else None
        )
        if coverage < args.min_coverage:
            data_ok = False
            data_errors.append(f"{name} coverage {coverage:.6f} < {args.min_coverage}")
        rows = []
        deg = {}
        ns = []
        for day, g in complete.groupby("datetime", sort=True):
            pic, reason = _partial_day(g, args.feature, args.min_partial_n)
            if reason:
                deg[reason] = deg.get(reason, 0) + 1
                continue
            ns.append(int(len(g)))
            rows.append(
                {
                    "window": name,
                    "datetime": _date_string(day),
                    "n_complete": int(len(g)),
                    "partial_rankic": pic,
                }
            )
        daily = pd.DataFrame(rows)
        if daily.empty:
            data_ok = False
            data_errors.append(f"{name}: no effective days")
            stats = {"n_days": 0, "mean": float("nan"), "median": float("nan"), "std": float("nan"), "icir": float("nan")}
            boot = {"ci_lower": float("nan"), "ci_upper": float("nan"), "point_estimate": float("nan")}
            qstab = {"majority_negative": True, "single_quarter_driven": True, "passes": False, "quarters": []}
        else:
            stats = _series_stats(daily["partial_rankic"])
            boot = moving_block_bootstrap_ci(
                daily["partial_rankic"], block_days=args.block_days, reps=args.bootstrap_reps, seed=args.seed
            )
            qstab = _quarter_stability(daily) if name == "2026_oos" else None
        summaries[name] = {
            "partial_rankic": stats,
            "bootstrap": boot,
            "quarter_stability": qstab,
            "row_coverage": float(coverage),
            "coverage_pass": bool(coverage >= args.min_coverage),
            "effective_days": int(len(daily)),
            "degraded_days": deg,
            "median_common_names": float(np.median(ns)) if ns else float("nan"),
            "n_score_finite": n_score,
            "n_complete": int(len(complete)),
            "missing_close_rows": close_miss,
            "missing_amount_rows": amount_miss,
            "missing_window_rows": window_miss,
        }
        if len(daily):
            daily_parts.append(daily)
        print(
            f"[{name}] mean={stats['mean']} ci=[{boot.get('ci_lower')},{boot.get('ci_upper')}] "
            f"cov={coverage:.4f}",
            flush=True,
        )

    decision = decide_verdict(summaries, data_ok)
    if data_errors:
        decision["data_errors"] = data_errors
    if decision["gates"]["S1_pass"]:
        decision["action"] = "A passed; may proceed to B"
    else:
        decision["action"] = "Stop per §4; do not enter B/C"

    if daily_parts:
        pd.concat(daily_parts, ignore_index=True).to_csv(out_dir / "daily_partial_rankic.csv", index=False)
    payload = {
        "sidecar_sha256": side_sha,
        "manifest": manifest,
        "pred_2025": meta25,
        "pred_2026": meta26,
        "windows": summaries,
        "decision": decision,
        "label": args.label,
        "online_untouched": True,
    }
    (out_dir / "window_summary.json").write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "verdict.json").write_text(
        json.dumps(_json_safe(decision), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[verdict] {decision['verdict']}", flush=True)
    return 0 if decision["gates"]["S1_pass"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        raise
