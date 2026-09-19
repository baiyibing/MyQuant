# -*- coding: utf-8 -*-
"""T5-CYQ1 stage A: conditional RankIC of CYQ given frozen 8a061ea4 score.

Read-only diagnostic. Never trains, never overwrites pred, never runs PortAna/BT.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import host_env  # noqa: F401

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

RECORDER_ID = "8a061ea428e04bb3a199a485ade49d0e"
EXPERIMENT = "alpha158_cost_kdj_lgb"
LABEL = "Ref($close,-2)/Ref($close,-1)-1"
DEFAULT_WINDOWS = (("2025-01-03", "2025-12-31"), ("2026-01-01", "2026-09-14"))
WINDOW_NAMES = ("2025_valid", "2026_oos")
BLOCK_DAYS = 5
BOOTSTRAP_REPS = 10_000
SEED = 20_260_917
MIN_COVERAGE = 0.98
FEATURE_NAME_SIGNAL = "cyq_signal"  # -winner_ratio


def _load_runtime() -> None:
    global np, pd
    import numpy as np_module
    import pandas as pd_module

    np = np_module
    pd = pd_module


def parse_window(value: str) -> tuple[str, str]:
    parts = value.split(":", maxsplit=1)
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("window must be START:END")
    start, end = (p.strip() for p in parts)
    try:
        if date.fromisoformat(start) > date.fromisoformat(end):
            raise argparse.ArgumentTypeError(f"window start after end: {value!r}")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO window: {value!r}") from exc
    return start, end


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="T5-CYQ1 A: CYQ partial RankIC gates")
    p.add_argument("--experiment", default=EXPERIMENT)
    p.add_argument("--recorder-id", default=RECORDER_ID)
    p.add_argument("--pred-2025", type=Path, default=SCRIPT_DIR / "预测结果_8a061ea4_2025valid.csv")
    p.add_argument("--cyq-file", type=Path, required=True)
    p.add_argument("--cyq-column", default="winner_ratio")
    p.add_argument("--direction", choices=("lower", "higher"), default="lower")
    p.add_argument("--label", default=LABEL)
    p.add_argument("--window", action="append", type=parse_window)
    p.add_argument("--min-coverage", type=float, default=MIN_COVERAGE)
    p.add_argument("--block-days", type=int, default=BLOCK_DAYS)
    p.add_argument("--bootstrap-reps", type=int, default=BOOTSTRAP_REPS)
    p.add_argument("--seed", type=int, default=SEED)
    p.add_argument("--provider-uri", default="~/.qlib/qlib_data/my_data")
    p.add_argument("--mlruns-dir", type=Path, default=SCRIPT_DIR / "mlruns")
    p.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "exports/analysis/t5_cyq1_information_20260917",
    )
    return p


def _file_identity(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "size_bytes": int(stat.st_size),
        "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "sha256": digest.hexdigest(),
    }


def _date_string(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return pd.Timestamp(value).date().isoformat()


def _normalize_scores(obj: Any, source: str) -> tuple[Any, dict[str, Any]]:
    if isinstance(obj, pd.Series):
        frame = obj.rename("score").reset_index()
    elif isinstance(obj, pd.DataFrame):
        frame = obj.reset_index() if isinstance(obj.index, pd.MultiIndex) else obj.copy()
    else:
        raise TypeError(f"unsupported prediction from {source}: {type(obj)!r}")
    if "score" not in frame.columns:
        candidates = [c for c in frame.columns if c not in {"datetime", "instrument"}]
        if len(candidates) != 1:
            raise ValueError(f"{source}: missing score; columns={list(frame.columns)}")
        frame = frame.rename(columns={candidates[0]: "score"})
    if "datetime" not in frame.columns or "instrument" not in frame.columns:
        others = [c for c in frame.columns if c != "score"]
        rename: dict[Any, str] = {}
        if "datetime" not in frame.columns:
            rename[others[0]] = "datetime"
        remaining = [c for c in others if c not in rename]
        if "instrument" not in frame.columns:
            rename[remaining[0]] = "instrument"
        frame = frame.rename(columns=rename)
    out = frame.loc[:, ["datetime", "instrument", "score"]].copy()
    out["datetime"] = pd.to_datetime(out["datetime"], errors="raise").dt.normalize()
    out["instrument"] = out["instrument"].astype(str)
    out["score"] = pd.to_numeric(out["score"], errors="coerce")
    missing = int(out["score"].isna().sum())
    out = out.dropna(subset=["score"])
    dup = int(out.duplicated(["datetime", "instrument"], keep=False).sum())
    if dup:
        raise ValueError(f"{source}: {dup} duplicate datetime/instrument rows")
    out = out.sort_values(["datetime", "instrument"], kind="mergesort").reset_index(drop=True)
    meta = {
        "source": source,
        "usable_score_rows": int(len(out)),
        "missing_score_rows": missing,
        "date_min": _date_string(out["datetime"].min()) if len(out) else None,
        "date_max": _date_string(out["datetime"].max()) if len(out) else None,
    }
    return out, meta


def _load_2025(path: Path):
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    frame, meta = _normalize_scores(pd.read_csv(resolved), str(resolved))
    meta.update(_file_identity(resolved))
    return frame, meta


def _load_2026(provider_uri: str, mlruns_dir: Path, recorder_id: str, experiment: str):
    import qlib
    from qlib.config import REG_CN
    from qlib.workflow import R

    provider = Path(os.path.expanduser(provider_uri)).resolve()
    store = mlruns_dir.expanduser().resolve()
    if not provider.exists():
        raise FileNotFoundError(provider)
    if not store.is_dir():
        raise FileNotFoundError(store)
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
    print(f"[input] load read-only recorder={recorder_id} pred.pkl", flush=True)
    scores, meta = _normalize_scores(rec.load_object("pred.pkl"), f"recorder:{recorder_id}/pred.pkl")
    meta.update({"experiment": experiment, "recorder_id": recorder_id, "mlruns_dir": str(store)})
    return scores, meta


def _ensure_qlib(provider_uri: str, mlruns_dir: Path) -> None:
    import qlib
    from qlib.config import REG_CN

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


def _load_labels(instruments: list[str], start: str, end: str, label: str):
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


def _load_cyq(path: Path, column: str) -> tuple[Any, dict[str, Any]]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    df = pd.read_parquet(resolved)
    if column not in df.columns:
        raise ValueError(f"CYQ missing column {column}; have {list(df.columns)}")
    code_col = "stock_code" if "stock_code" in df.columns else "instrument"
    date_col = "date" if "date" in df.columns else "datetime"
    out = pd.DataFrame(
        {
            "datetime": pd.to_datetime(df[date_col]).dt.normalize(),
            "instrument": df[code_col].astype(str),
            "winner_ratio": pd.to_numeric(df[column], errors="coerce"),
        }
    )
    out = out.dropna(subset=["winner_ratio"])
    # value domain check later on join
    meta = _file_identity(resolved)
    meta.update(
        {
            "rows": int(len(out)),
            "instruments": int(out["instrument"].nunique()),
            "date_min": _date_string(out["datetime"].min()),
            "date_max": _date_string(out["datetime"].max()),
            "column": column,
        }
    )
    return out, meta


def _pct_rank(series: Any) -> Any:
    return series.rank(method="average", pct=True)


def _ols_resid(y: Any, x: Any) -> Any:
    """Residuals of y ~ 1 + x (no intercept-only fallback)."""
    yv = np.asarray(y, dtype=float)
    xv = np.asarray(x, dtype=float)
    n = len(yv)
    X = np.column_stack([np.ones(n), xv])
    beta, _, _, _ = np.linalg.lstsq(X, yv, rcond=None)
    return yv - X @ beta


def _partial_rankic_day(day: Any) -> tuple[float, str | None]:
    """Return (partial_rankic, degrade_reason). degrade_reason set => skip day."""
    if len(day) < 5:
        return float("nan"), "n_lt_5"
    s = _pct_rank(day["score"])
    c = _pct_rank(day["cyq_signal"])
    y = _pct_rank(day["label"])
    if s.nunique(dropna=False) < 2 or c.nunique(dropna=False) < 2 or y.nunique(dropna=False) < 2:
        return float("nan"), "zero_variance_rank"
    try:
        rc = _ols_resid(c.to_numpy(), s.to_numpy())
        ry = _ols_resid(y.to_numpy(), s.to_numpy())
    except Exception:
        return float("nan"), "ols_fail"
    if not (np.isfinite(rc).all() and np.isfinite(ry).all()):
        return float("nan"), "resid_nonfinite"
    if np.nanstd(rc) <= 0 or np.nanstd(ry) <= 0:
        return float("nan"), "resid_zero_var"
    corr = float(np.corrcoef(rc, ry)[0, 1])
    if not np.isfinite(corr):
        return float("nan"), "corr_nonfinite"
    return corr, None


def moving_block_bootstrap_ci(values: Iterable[float], *, block_days: int, reps: int, seed: int) -> dict[str, Any]:
    sample = np.asarray(list(values), dtype=float)
    sample = sample[np.isfinite(sample)]
    if len(sample) < block_days:
        raise ValueError(f"need >= {block_days} finite days; got {len(sample)}")
    rng = np.random.default_rng(seed)
    block_count = math.ceil(len(sample) / block_days)
    last_start = len(sample) - block_days
    estimates = np.empty(reps, dtype=float)
    offsets = np.arange(block_days)
    for rep in range(reps):
        starts = rng.integers(0, last_start + 1, size=block_count)
        indices = (starts[:, None] + offsets[None, :]).ravel()[: len(sample)]
        estimates[rep] = float(sample[indices].mean())
    lower, upper = np.quantile(estimates, [0.025, 0.975])
    return {
        "method": "moving_block_bootstrap",
        "statistic": "mean_daily_cyq_partial_rankic",
        "n_days": int(len(sample)),
        "block_days": block_days,
        "reps": reps,
        "seed": seed,
        "point_estimate": float(sample.mean()),
        "ci_level": 0.95,
        "ci_lower": float(lower),
        "ci_upper": float(upper),
    }


def _series_stats(series: Any) -> dict[str, Any]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    std = float(values.std(ddof=1)) if len(values) > 1 else float("nan")
    mean = float(values.mean()) if len(values) else float("nan")
    return {
        "n_days": int(len(values)),
        "mean": mean,
        "median": float(values.median()) if len(values) else float("nan"),
        "std": std,
        "icir": mean / std if np.isfinite(std) and std > 0 else float("nan"),
    }


def _quarter_stability(daily: Any, col: str = "partial_rankic") -> dict[str, Any]:
    work = daily.copy()
    work["quarter"] = pd.to_datetime(work["datetime"]).dt.to_period("Q").astype(str)
    rows = []
    for q, g in work.groupby("quarter", sort=True):
        st = _series_stats(g[col])
        rows.append({"quarter": q, **st})
    means = [r["mean"] for r in rows if np.isfinite(r["mean"])]
    n_q = len(means)
    n_neg = sum(1 for m in means if m < 0)
    n_pos = sum(1 for m in means if m > 0)
    full_mean = float(np.nanmean(means)) if means else float("nan")
    majority_negative = (n_neg / n_q > 0.5) if n_q else True
    single_quarter_driven = bool(np.isfinite(full_mean) and full_mean > 0 and n_pos <= 1)
    return {
        "quarters": rows,
        "majority_negative": bool(majority_negative),
        "single_quarter_driven": bool(single_quarter_driven),
        "passes": bool((not majority_negative) and (not single_quarter_driven)),
    }


def _window_slice(scores: Any, start: str, end: str) -> Any:
    lo = pd.Timestamp(start)
    hi = pd.Timestamp(end)
    return scores.loc[(scores["datetime"] >= lo) & (scores["datetime"] <= hi)].copy()


def analyze_window(
    name: str,
    scores: Any,
    cyq: Any,
    *,
    label: str,
    direction: str,
    min_coverage: float,
    provider_uri: str,
    mlruns_dir: Path,
) -> tuple[Any, dict[str, Any]]:
    start = _date_string(scores["datetime"].min())
    end = _date_string(scores["datetime"].max())
    assert start and end
    _ensure_qlib(provider_uri, mlruns_dir)
    instruments = sorted(scores["instrument"].unique().tolist())
    labels = _load_labels(instruments, start, end, label)
    merged = scores.merge(labels, on=["datetime", "instrument"], how="left", validate="one_to_one")
    merged = merged.merge(cyq, on=["datetime", "instrument"], how="left", validate="one_to_one")
    n_pred = int(len(merged))
    # domain
    wr = merged["winner_ratio"]
    if wr.notna().any() and ((wr.dropna() < 0).any() or (wr.dropna() > 1).any()):
        raise RuntimeError(f"{name}: winner_ratio outside [0,1]")
    if direction == "lower":
        merged["cyq_signal"] = -merged["winner_ratio"]
    else:
        merged["cyq_signal"] = merged["winner_ratio"]
    complete = merged.dropna(subset=["score", "label", "winner_ratio"]).copy()
    coverage = len(complete) / n_pred if n_pred else 0.0
    # daily
    rows = []
    degrade_counts: dict[str, int] = {}
    for day_value, day in complete.groupby("datetime", sort=True):
        pic, reason = _partial_rankic_day(day)
        if reason:
            degrade_counts[reason] = degrade_counts.get(reason, 0) + 1
            continue
        rows.append(
            {
                "window": name,
                "datetime": _date_string(day_value),
                "n_complete": int(len(day)),
                "partial_rankic": pic,
            }
        )
    daily = pd.DataFrame(rows)
    if daily.empty:
        raise RuntimeError(f"{name}: no effective partial RankIC days")
    stats = _series_stats(daily["partial_rankic"])
    bootstrap = moving_block_bootstrap_ci(
        daily["partial_rankic"].tolist(),
        block_days=BLOCK_DAYS,
        reps=BOOTSTRAP_REPS,
        seed=SEED,
    )
    qstab = _quarter_stability(daily) if name == "2026_oos" else None
    # coverage by day median stocks
    day_cov = []
    for day_value, day_all in merged.groupby("datetime", sort=True):
        n_all = len(day_all)
        n_ok = int(day_all[["score", "label", "winner_ratio"]].notna().all(axis=1).sum())
        day_cov.append(n_ok / n_all if n_all else 0.0)
    summary = {
        "window": name,
        "start": start,
        "end": end,
        "n_pred_rows": n_pred,
        "n_complete_rows": int(len(complete)),
        "row_coverage": float(coverage),
        "day_coverage_mean": float(np.mean(day_cov)) if day_cov else float("nan"),
        "day_coverage_min": float(np.min(day_cov)) if day_cov else float("nan"),
        "coverage_pass": bool(coverage >= min_coverage),
        "partial_rankic": stats,
        "degraded_days": degrade_counts,
        "effective_days": int(len(daily)),
        "stocks_per_day_median": float(daily["n_complete"].median()),
        "bootstrap": bootstrap,
        "quarter_stability": qstab,
        "cyq_missing_rate": float(1.0 - coverage),
    }
    return daily, summary


def decide_verdict(windows: dict[str, dict[str, Any]], *, min_coverage: float) -> dict[str, Any]:
    # S0 data
    s0 = all(w["coverage_pass"] for w in windows.values())
    w25 = windows["2025_valid"]
    w26 = windows["2026_oos"]
    m25 = w25["partial_rankic"]["mean"]
    m26 = w26["partial_rankic"]["mean"]
    ci_lo = w26["bootstrap"]["ci_lower"]
    q = w26["quarter_stability"] or {}
    same_sign_pos = bool(m25 > 0 and m26 > 0)
    flip = bool((m25 > 0) != (m26 > 0)) or bool(q.get("majority_negative"))
    no_edge = bool(same_sign_pos and (ci_lo <= 0 or q.get("single_quarter_driven")))
    s1 = bool(same_sign_pos and ci_lo > 0 and q.get("passes"))
    if not s0:
        verdict = "CYQ_DATA_INVALID"
        action = "Stop; fix data availability only; do not change CYQ口径."
    elif flip and not same_sign_pos:
        verdict = "CYQ_CONDITIONAL_FLIP"
        action = "Stop CYQ single-feature route; do not flip direction or cut quarters."
    elif (not s1) and (same_sign_pos or m26 <= 0 or ci_lo <= 0 or q.get("single_quarter_driven") or q.get("majority_negative")):
        # majority_negative already in flip path if m signs differ; here catch no-edge
        if (m25 > 0) != (m26 > 0) or q.get("majority_negative"):
            verdict = "CYQ_CONDITIONAL_FLIP"
            action = "Stop CYQ single-feature route."
        else:
            verdict = "CYQ_CONDITIONAL_NO_EDGE"
            action = "Insufficient OOS evidence; stop; do not revive with PortAna."
    elif s1:
        verdict = "CYQ_INFORMATION_PASS"
        action = "A gate passed; may proceed to B (one-column retrain) only."
    else:
        verdict = "CYQ_CONDITIONAL_NO_EDGE"
        action = "Stop."
    return {
        "verdict": verdict,
        "gates": {
            "S0_coverage": bool(s0),
            "S1_both_mean_gt0": bool(same_sign_pos),
            "S1_2026_ci_lower_gt0": bool(ci_lo > 0),
            "S1_quarter_stability": bool(q.get("passes")),
            "S1_pass": bool(s1 and s0),
            "cross_window_flip": bool(flip),
        },
        "means": {"2025_valid": m25, "2026_oos": m26},
        "ci_2026": w26["bootstrap"],
        "action": action,
        "min_coverage": min_coverage,
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return str(value)
    return value


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    _load_runtime()
    out_dir = args.out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("daily_partial_rankic.csv", "window_summary.json", "verdict.json", "input_summary.json"):
        existing = out_dir / name
        if existing.exists():
            raise FileExistsError(f"refuse to overwrite existing {existing}")

    windows_cfg = list(DEFAULT_WINDOWS if args.window is None else args.window)
    if len(windows_cfg) != 2:
        raise ValueError("--window must be omitted or supplied exactly twice")
    windows = dict(zip(WINDOW_NAMES, windows_cfg))

    cyq, cyq_meta = _load_cyq(args.cyq_file, args.cyq_column)
    print(f"[cyq] {cyq_meta['path']} sha256={cyq_meta['sha256']} rows={cyq_meta['rows']}", flush=True)

    scores_2025, meta_2025 = _load_2025(args.pred_2025)
    scores_2026, meta_2026 = _load_2026(
        args.provider_uri, args.mlruns_dir, args.recorder_id, args.experiment
    )

    daily_parts = []
    summaries: dict[str, Any] = {}
    for name, (start, end) in windows.items():
        base = scores_2025 if name == "2025_valid" else scores_2026
        sliced = _window_slice(base, start, end)
        if sliced.empty:
            raise RuntimeError(f"{name}: empty score slice {start}:{end}")
        daily, summary = analyze_window(
            name,
            sliced,
            cyq,
            label=args.label,
            direction=args.direction,
            min_coverage=args.min_coverage,
            provider_uri=args.provider_uri,
            mlruns_dir=args.mlruns_dir,
        )
        daily_parts.append(daily)
        summaries[name] = summary
        print(
            f"[{name}] mean_partial={summary['partial_rankic']['mean']:.6f} "
            f"ci=[{summary['bootstrap']['ci_lower']:.6f},{summary['bootstrap']['ci_upper']:.6f}] "
            f"cov={summary['row_coverage']:.4f} eff_days={summary['effective_days']}",
            flush=True,
        )

    daily_all = pd.concat(daily_parts, ignore_index=True)
    daily_all.to_csv(out_dir / "daily_partial_rankic.csv", index=False)
    decision = decide_verdict(summaries, min_coverage=args.min_coverage)
    payload = {
        "generated_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "cyq": cyq_meta,
        "pred_2025": meta_2025,
        "pred_2026": meta_2026,
        "label": args.label,
        "direction": args.direction,
        "windows": summaries,
        "decision": decision,
    }
    (out_dir / "window_summary.json").write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "verdict.json").write_text(
        json.dumps(_json_safe(decision), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "input_summary.json").write_text(
        json.dumps(
            _json_safe({"cyq": cyq_meta, "pred_2025": meta_2025, "pred_2026": meta_2026}),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    md = [
        f"# T5-CYQ1 A verdict: `{decision['verdict']}`",
        "",
        f"- action: {decision['action']}",
        f"- 2025 mean partial RankIC: {decision['means']['2025_valid']}",
        f"- 2026 mean partial RankIC: {decision['means']['2026_oos']}",
        f"- 2026 CI: [{decision['ci_2026']['ci_lower']}, {decision['ci_2026']['ci_upper']}]",
        f"- CYQ sha256: `{cyq_meta['sha256']}`",
        f"- CYQ path: `{cyq_meta['path']}`",
        "",
    ]
    (out_dir / "verdict.md").write_text("\n".join(md), encoding="utf-8")
    print(f"[verdict] {decision['verdict']}", flush=True)
    print(f"[out] {out_dir}", flush=True)
    return 0 if decision["verdict"] == "CYQ_INFORMATION_PASS" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FileExistsError as exc:
        print(f"FATAL fail-closed: {exc}", file=sys.stderr)
        raise SystemExit(3)
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        raise
