# -*- coding: utf-8 -*-
"""T5-LH3 label-horizon precheck on one frozen recorder prediction.

This is a read-only signal diagnostic.  It loads the 2026 ``pred.pkl`` from
recorder 8a061ea4 and the already-exported 2025 valid scores, evaluates two
fixed labels, and writes metrics to a new output directory.  It never trains,
saves recorder objects, runs PortAna/backtests, or changes online settings.
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
from typing import Any, Iterable, Sequence

import host_env  # noqa: F401  # must precede any qlib import

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

RECORDER_ID = "8a061ea428e04bb3a199a485ade49d0e"
EXPERIMENT = "alpha158_cost_kdj_lgb"
CONTROL_LABEL = "Ref($close,-2)/Ref($close,-1)-1"
CANDIDATE_LABEL = "Ref($close,-4)/Ref($close,-1)-1"
DEFAULT_WINDOWS = (("2025-01-03", "2025-12-31"), ("2026-01-01", "2026-09-14"))
WINDOW_NAMES = ("2025_valid", "2026_oos")
TOPK = 10
CONTROL_HOLDING_DAYS = 1
CANDIDATE_HOLDING_DAYS = 3
BLOCK_DAYS = 5
BOOTSTRAP_REPS = 10_000
SEED = 20_260_917
OUTPUT_FILES = (
    "daily_metrics.csv",
    "window_summary.json",
    "window_summary.md",
    "input_summary.json",
)


def _load_runtime_dependencies() -> None:
    """Import heavy runtime dependencies only after argparse handles ``--help``."""
    global np, pd
    try:
        import numpy as np_module
        import pandas as pd_module
    except ImportError as exc:
        raise RuntimeError("runtime requires numpy and pandas in the selected Python environment") from exc
    np = np_module
    pd = pd_module


def parse_window(value: str) -> tuple[str, str]:
    """Parse an inclusive START:END ISO date range."""
    parts = value.split(":", maxsplit=1)
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("window must be START:END")
    start, end = (part.strip() for part in parts)
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO window: {value!r}") from exc
    if start_date > end_date:
        raise argparse.ArgumentTypeError(f"window start is after end: {value!r}")
    return start, end


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only T5-LH3 precheck: fixed 8a061ea4 scores, h=1 vs h=3 labels; "
            "no training, PortAna, backtest, gate sweep, or online change"
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--experiment", choices=(EXPERIMENT,), default=EXPERIMENT)
    parser.add_argument("--recorder-id", choices=(RECORDER_ID,), default=RECORDER_ID)
    parser.add_argument(
        "--pred-2025",
        type=Path,
        default=SCRIPT_DIR / "预测结果_8a061ea4_2025valid.csv",
        help="Existing 2025 valid score CSV (read only)",
    )
    parser.add_argument(
        "--provider-uri",
        default="~/.qlib/qlib_data/my_data",
        help="Qlib provider containing close data",
    )
    parser.add_argument(
        "--mlruns-dir",
        type=Path,
        default=SCRIPT_DIR / "mlruns",
        help="MLflow file store containing the fixed recorder",
    )
    parser.add_argument(
        "--window",
        action="append",
        type=parse_window,
        metavar="START:END",
        help="Exactly twice when overriding: first 2025 valid, then 2026 OOS",
    )
    parser.add_argument("--control-label", choices=(CONTROL_LABEL,), default=CONTROL_LABEL)
    parser.add_argument("--candidate-label", choices=(CANDIDATE_LABEL,), default=CANDIDATE_LABEL)
    parser.add_argument("--topk", type=int, choices=(TOPK,), default=TOPK)
    parser.add_argument("--block-days", type=int, choices=(BLOCK_DAYS,), default=BLOCK_DAYS)
    parser.add_argument(
        "--bootstrap-reps", type=int, choices=(BOOTSTRAP_REPS,), default=BOOTSTRAP_REPS
    )
    parser.add_argument("--seed", type=int, choices=(SEED,), default=SEED)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "exports/analysis/annual_lift_label_h3_20260917",
        help="Fresh output directory; existing result files are never overwritten",
    )
    return parser


def _windows_from_args(values: list[tuple[str, str]] | None) -> dict[str, tuple[str, str]]:
    windows = list(DEFAULT_WINDOWS if values is None else values)
    if len(windows) != 2:
        raise ValueError("--window must be omitted or supplied exactly twice (2025 valid, 2026 OOS)")
    return dict(zip(WINDOW_NAMES, windows))


def _normalize_scores(obj: Any, source: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    if isinstance(obj, pd.Series):
        frame = obj.rename("score").reset_index()
    elif isinstance(obj, pd.DataFrame):
        frame = obj.reset_index() if isinstance(obj.index, pd.MultiIndex) else obj.copy()
    else:
        raise TypeError(f"unsupported prediction object from {source}: {type(obj)!r}")

    if "score" not in frame.columns:
        candidates = [c for c in frame.columns if c not in {"datetime", "instrument"}]
        if len(candidates) == 1:
            frame = frame.rename(columns={candidates[0]: "score"})
        else:
            raise ValueError(f"{source}: missing unambiguous score column; columns={list(frame.columns)}")
    if "datetime" not in frame.columns or "instrument" not in frame.columns:
        others = [c for c in frame.columns if c != "score"]
        if len(others) < 2:
            raise ValueError(f"{source}: need datetime, instrument, score")
        rename: dict[Any, str] = {}
        if "datetime" not in frame.columns:
            rename[others[0]] = "datetime"
        remaining = [c for c in others if c not in rename]
        if "instrument" not in frame.columns:
            rename[remaining[0]] = "instrument"
        frame = frame.rename(columns=rename)

    out = frame.loc[:, ["datetime", "instrument", "score"]].copy()
    raw_rows = len(out)
    out["datetime"] = pd.to_datetime(out["datetime"], errors="raise").dt.normalize()
    out["instrument"] = out["instrument"].astype(str)
    out["score"] = pd.to_numeric(out["score"], errors="coerce")
    missing_scores = int(out["score"].isna().sum())
    out = out.dropna(subset=["score"])
    duplicate_rows = int(out.duplicated(["datetime", "instrument"], keep=False).sum())
    if duplicate_rows:
        raise ValueError(f"{source}: {duplicate_rows} duplicate datetime/instrument rows")
    out = out.sort_values(["datetime", "instrument"], kind="mergesort").reset_index(drop=True)
    meta = {
        "source": source,
        "raw_rows": int(raw_rows),
        "usable_score_rows": int(len(out)),
        "missing_score_rows": missing_scores,
        "duplicate_key_rows": duplicate_rows,
        "date_min": _date_string(out["datetime"].min()) if len(out) else None,
        "date_max": _date_string(out["datetime"].max()) if len(out) else None,
        "dates": int(out["datetime"].nunique()),
        "instruments": int(out["instrument"].nunique()),
    }
    return out, meta


def _load_2025_scores(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"2025 valid score CSV not found: {resolved}")
    frame, meta = _normalize_scores(pd.read_csv(resolved), str(resolved))
    meta.update(_file_identity(resolved))
    return frame, meta


def _init_qlib_and_load_2026(
    *, provider_uri: str, mlruns_dir: Path
) -> tuple[pd.DataFrame, dict[str, Any]]:
    # Lazy imports keep ``--help`` runnable even on a host without qlib.
    import qlib
    from qlib.config import REG_CN
    from qlib.workflow import R

    provider = Path(os.path.expanduser(provider_uri)).resolve()
    store = mlruns_dir.expanduser().resolve()
    if not provider.exists():
        raise FileNotFoundError(f"qlib provider not found: {provider}")
    if not store.is_dir():
        raise FileNotFoundError(f"MLflow store not found: {store}")
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
    recorder = R.get_recorder(recorder_id=RECORDER_ID, experiment_name=EXPERIMENT)
    print(f"[input] load read-only recorder={RECORDER_ID} object=pred.pkl", flush=True)
    scores, meta = _normalize_scores(recorder.load_object("pred.pkl"), f"recorder:{RECORDER_ID}/pred.pkl")
    matches = sorted(store.glob(f"*/{RECORDER_ID}/artifacts/pred.pkl"))
    meta.update(
        {
            "experiment": EXPERIMENT,
            "recorder_id": RECORDER_ID,
            "object": "pred.pkl",
            "mlruns_dir": str(store),
            "artifact_matches": [str(path.resolve()) for path in matches],
        }
    )
    if len(matches) == 1:
        meta.update(_file_identity(matches[0]))
    return scores, meta


def _load_labels(
    instruments: Sequence[str], start: str, end: str
) -> tuple[pd.DataFrame, dict[str, Any]]:
    from qlib.data import D

    print(
        f"[label] D.features instruments={len(instruments)} window={start}:{end} "
        f"expressions=2",
        flush=True,
    )
    raw = D.features(
        list(instruments),
        [CONTROL_LABEL, CANDIDATE_LABEL],
        start_time=start,
        end_time=end,
    )
    if raw is None or raw.empty:
        raise RuntimeError(f"D.features returned no label rows for {start}:{end}")
    frame = raw.reset_index() if isinstance(raw.index, pd.MultiIndex) else raw.copy()
    if "datetime" not in frame.columns or "instrument" not in frame.columns:
        raise ValueError(f"label frame missing index names; columns={list(frame.columns)}")
    if CONTROL_LABEL not in frame.columns or CANDIDATE_LABEL not in frame.columns:
        values = [c for c in frame.columns if c not in {"datetime", "instrument"}]
        if len(values) != 2:
            raise ValueError(f"label frame has unexpected columns: {list(frame.columns)}")
        frame = frame.rename(columns={values[0]: CONTROL_LABEL, values[1]: CANDIDATE_LABEL})
    out = frame.loc[:, ["datetime", "instrument", CONTROL_LABEL, CANDIDATE_LABEL]].copy()
    out = out.rename(columns={CONTROL_LABEL: "label_control", CANDIDATE_LABEL: "label_candidate"})
    out["datetime"] = pd.to_datetime(out["datetime"], errors="raise").dt.normalize()
    out["instrument"] = out["instrument"].astype(str)
    out["label_control"] = pd.to_numeric(out["label_control"], errors="coerce")
    out["label_candidate"] = pd.to_numeric(out["label_candidate"], errors="coerce")
    duplicate_rows = int(out.duplicated(["datetime", "instrument"], keep=False).sum())
    if duplicate_rows:
        raise ValueError(f"labels: {duplicate_rows} duplicate datetime/instrument rows")
    meta = {
        "raw_rows": int(len(out)),
        "rows_control_present": int(out["label_control"].notna().sum()),
        "rows_candidate_present": int(out["label_candidate"].notna().sum()),
        "rows_both_present": int(out[["label_control", "label_candidate"]].notna().all(axis=1).sum()),
        "duplicate_key_rows": duplicate_rows,
    }
    return out, meta


def _spearman(left: pd.Series, right: pd.Series) -> float:
    aligned = pd.concat([left, right], axis=1).dropna()
    if len(aligned) < 2 or aligned.iloc[:, 0].nunique() < 2 or aligned.iloc[:, 1].nunique() < 2:
        return float("nan")
    return float(
        aligned.iloc[:, 0].rank(method="average").corr(
            aligned.iloc[:, 1].rank(method="average"), method="pearson"
        )
    )


def _dailyize(values: pd.Series, holding_days: int) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce").astype(float)
    if (numeric.dropna() <= -1.0).any():
        raise ValueError("label return <= -100%; cannot geometrically dailyize")
    return (1.0 + numeric).pow(1.0 / holding_days) - 1.0


def _daily_metrics(
    window_name: str,
    scores: pd.DataFrame,
    labels: pd.DataFrame,
    *,
    topk: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    merged = scores.merge(labels, on=["datetime", "instrument"], how="left", validate="one_to_one")
    complete_mask = merged[["score", "label_control", "label_candidate"]].notna().all(axis=1)
    complete = merged.loc[complete_mask].copy()
    if complete.empty:
        raise RuntimeError(f"{window_name}: no common score/control/candidate rows")
    complete["control_daily"] = _dailyize(complete["label_control"], CONTROL_HOLDING_DAYS)
    complete["candidate_daily"] = _dailyize(complete["label_candidate"], CANDIDATE_HOLDING_DAYS)

    pred_counts = merged.groupby("datetime", sort=True).size().rename("n_pred")
    rows: list[dict[str, Any]] = []
    for day_value, day in complete.groupby("datetime", sort=True):
        ranked = day.sort_values(["score", "instrument"], ascending=[False, True], kind="mergesort")
        selected = ranked.head(topk)
        n_pred = int(pred_counts.loc[day_value])
        n_complete = int(len(ranked))
        control_universe = float(ranked["control_daily"].mean())
        candidate_universe = float(ranked["candidate_daily"].mean())
        control_top = float(selected["control_daily"].mean())
        candidate_top = float(selected["candidate_daily"].mean())
        rankic_control = _spearman(ranked["score"], ranked["label_control"])
        rankic_candidate = _spearman(ranked["score"], ranked["label_candidate"])
        rows.append(
            {
                "window": window_name,
                "datetime": _date_string(day_value),
                "n_pred": n_pred,
                "n_complete": n_complete,
                "missing_rate": (n_pred - n_complete) / n_pred if n_pred else float("nan"),
                "top10_n": int(len(selected)),
                "rankic_control": rankic_control,
                "rankic_candidate": rankic_candidate,
                "delta_rankic": rankic_candidate - rankic_control,
                "top10_control_daily": control_top,
                "universe_control_daily": control_universe,
                "top10_spread_control": control_top - control_universe,
                "top10_candidate_daily": candidate_top,
                "universe_candidate_daily": candidate_universe,
                "top10_spread_candidate": candidate_top - candidate_universe,
                "delta_top10_spread": (candidate_top - candidate_universe)
                - (control_top - control_universe),
            }
        )
    daily = pd.DataFrame(rows)
    missing_rows = int((~complete_mask).sum())
    input_meta = {
        "pred_rows_in_window": int(len(scores)),
        "label_rows_returned": int(len(labels)),
        "common_complete_rows": int(len(complete)),
        "missing_either_label_rows": missing_rows,
        "missing_rate": missing_rows / len(merged) if len(merged) else float("nan"),
        "effective_dates": int(daily["datetime"].nunique()),
        "date_min": str(daily["datetime"].min()),
        "date_max": str(daily["datetime"].max()),
        "instruments": int(complete["instrument"].nunique()),
        "stocks_per_day_median": float(daily["n_complete"].median()),
        "stocks_per_day_min": int(daily["n_complete"].min()),
    }
    return daily, complete, input_meta


def moving_block_bootstrap_ci(
    values: Iterable[float], *, block_days: int, reps: int, seed: int
) -> dict[str, Any]:
    sample = np.asarray(list(values), dtype=float)
    sample = sample[np.isfinite(sample)]
    if len(sample) < block_days:
        raise ValueError(
            f"need at least {block_days} finite daily delta RankIC values; got {len(sample)}"
        )
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
        "statistic": "mean_daily_delta_rankic",
        "n_days": int(len(sample)),
        "block_days": block_days,
        "reps": reps,
        "seed": seed,
        "point_estimate": float(sample.mean()),
        "ci_level": 0.95,
        "ci_lower": float(lower),
        "ci_upper": float(upper),
    }


def _series_stats(series: pd.Series) -> dict[str, Any]:
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


def _quarterly(daily: pd.DataFrame) -> list[dict[str, Any]]:
    work = daily.copy()
    work["quarter"] = pd.to_datetime(work["datetime"]).dt.to_period("Q").astype(str)
    columns = (
        "rankic_control",
        "rankic_candidate",
        "delta_rankic",
        "top10_spread_control",
        "top10_spread_candidate",
        "delta_top10_spread",
    )
    rows = []
    for quarter, block in work.groupby("quarter", sort=True):
        row: dict[str, Any] = {"quarter": quarter, "days": int(len(block))}
        row.update({column: float(block[column].mean()) for column in columns})
        rows.append(row)
    return rows


def _quarter_stability(
    quarters: list[dict[str, Any]], *, delta_rankic_mean: float, delta_top10_mean: float
) -> dict[str, Any]:
    n_quarters = len(quarters)
    negative_candidate_rankic = sum(row["rankic_candidate"] < 0 for row in quarters)
    negative_candidate_top10 = sum(row["top10_spread_candidate"] < 0 for row in quarters)
    positive_delta_rankic = sum(row["delta_rankic"] > 0 for row in quarters)
    positive_delta_top10 = sum(row["delta_top10_spread"] > 0 for row in quarters)
    majority_negative = n_quarters > 0 and (
        negative_candidate_rankic > n_quarters / 2
        or negative_candidate_top10 > n_quarters / 2
    )
    single_quarter_driven = n_quarters >= 2 and (
        (delta_rankic_mean > 0 and positive_delta_rankic <= 1)
        or (delta_top10_mean > 0 and positive_delta_top10 <= 1)
    )
    return {
        "quarters": n_quarters,
        "negative_candidate_rankic_quarters": int(negative_candidate_rankic),
        "negative_candidate_top10_quarters": int(negative_candidate_top10),
        "positive_delta_rankic_quarters": int(positive_delta_rankic),
        "positive_delta_top10_quarters": int(positive_delta_top10),
        "majority_negative": bool(majority_negative),
        "single_quarter_driven": bool(single_quarter_driven),
        "passes": bool(not majority_negative and not single_quarter_driven),
        "rule": (
            "fail if >50% quarters have negative candidate RankIC/Top10 spread, or if an "
            "overall positive RankIC/Top10 improvement is positive in <=1 quarter"
        ),
    }


def _summarize_window(
    daily: pd.DataFrame,
    input_meta: dict[str, Any],
    *,
    block_days: int,
    reps: int,
    seed: int,
) -> dict[str, Any]:
    rankic_control = _series_stats(daily["rankic_control"])
    rankic_candidate = _series_stats(daily["rankic_candidate"])
    delta_rankic = _series_stats(daily["delta_rankic"])
    top_control = _series_stats(daily["top10_spread_control"])
    top_candidate = _series_stats(daily["top10_spread_candidate"])
    delta_top = _series_stats(daily["delta_top10_spread"])
    bootstrap = moving_block_bootstrap_ci(
        daily["delta_rankic"], block_days=block_days, reps=reps, seed=seed
    )
    quarters = _quarterly(daily)
    stability = _quarter_stability(
        quarters,
        delta_rankic_mean=delta_rankic["mean"],
        delta_top10_mean=delta_top["mean"],
    )
    return {
        "input": input_meta,
        "rankic": {
            "control": rankic_control,
            "candidate": rankic_candidate,
            "delta_candidate_minus_control": delta_rankic,
        },
        "top10_daily_signal_spread": {
            "dailyization": "geometric: (1 + holding-period return) ** (1 / holding_days) - 1",
            "control_holding_days": CONTROL_HOLDING_DAYS,
            "candidate_holding_days": CANDIDATE_HOLDING_DAYS,
            "control": top_control,
            "candidate": top_candidate,
            "delta_candidate_minus_control": delta_top,
        },
        "delta_rankic_bootstrap": bootstrap,
        "quarters": quarters,
        "quarter_stability": stability,
    }


def _decide_verdict(windows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    per_window: dict[str, dict[str, bool]] = {}
    for name in WINDOW_NAMES:
        summary = windows[name]
        per_window[name] = {
            "candidate_rankic_positive": summary["rankic"]["candidate"]["mean"] > 0,
            "candidate_top10_spread_positive": summary["top10_daily_signal_spread"]["candidate"]["mean"] > 0,
            "candidate_rankic_better": summary["rankic"]["delta_candidate_minus_control"]["mean"] > 0,
            "candidate_top10_spread_better": summary["top10_daily_signal_spread"][
                "delta_candidate_minus_control"
            ]["mean"]
            > 0,
        }
    keys = tuple(per_window[WINDOW_NAMES[0]])
    cross_window_flip = any(
        per_window[WINDOW_NAMES[0]][key] != per_window[WINDOW_NAMES[1]][key] for key in keys
    )
    s1 = all(
        row["candidate_rankic_positive"] and row["candidate_top10_spread_positive"]
        for row in per_window.values()
    )
    s2 = all(
        row["candidate_rankic_better"] and row["candidate_top10_spread_better"]
        for row in per_window.values()
    )
    oos = windows["2026_oos"]
    s3_ci = oos["delta_rankic_bootstrap"]["ci_lower"] > 0
    s3_quarters = bool(oos["quarter_stability"]["passes"])
    s3 = bool(s3_ci and s3_quarters)
    if s1 and s2 and s3:
        verdict = "LABEL_HORIZON_CANDIDATE"
        action = "May request one separately approved paired retrain changing only the label."
    elif cross_window_flip:
        verdict = "LABEL_HORIZON_FLIP"
        action = "Stop the label-horizon route; do not scan other horizons or 2026 gates."
    else:
        verdict = "LABEL_HORIZON_NO_EDGE"
        action = "Evidence is insufficient; stop the label-horizon route and do not revive it with one-window NAV."
    return {
        "verdict": verdict,
        "per_window_checks": per_window,
        "gates": {
            "S1_same_sign": bool(s1),
            "S2_same_order": bool(s2),
            "S3_oos_ci_lower_gt_zero": bool(s3_ci),
            "S3_quarter_stability": bool(s3_quarters),
            "S3_oos_evidence": bool(s3),
            "cross_window_flip": bool(cross_window_flip),
        },
        "action": action,
        "always_forbidden": [
            "retrain in this run",
            "overwrite pred",
            "run PortAna or backtest",
            "scan other label horizons",
            "scan 2026 gates",
            "change online 10/3",
        ],
    }


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
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).date().isoformat()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return str(value)
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _fmt(value: Any, digits: int = 6) -> str:
    if value is None or not np.isfinite(float(value)):
        return "NA"
    return f"{float(value):.{digits}f}"


def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def _render_markdown(payload: dict[str, Any]) -> str:
    windows = payload["windows"]
    verdict = payload["decision"]
    overview_rows = []
    for name in WINDOW_NAMES:
        item = windows[name]
        overview_rows.append(
            (
                name,
                item["input"]["effective_dates"],
                _fmt(item["input"]["stocks_per_day_median"], 1),
                _fmt(item["input"]["missing_rate"], 4),
                _fmt(item["rankic"]["control"]["mean"]),
                _fmt(item["rankic"]["candidate"]["mean"]),
                _fmt(item["rankic"]["delta_candidate_minus_control"]["mean"]),
                _fmt(item["delta_rankic_bootstrap"]["ci_lower"]),
                _fmt(item["delta_rankic_bootstrap"]["ci_upper"]),
                _fmt(item["top10_daily_signal_spread"]["control"]["mean"]),
                _fmt(item["top10_daily_signal_spread"]["candidate"]["mean"]),
            )
        )
    lines = [
        "# T5-LH3 label-horizon precheck",
        "",
        f"- Generated UTC: `{payload['generated_at_utc']}`",
        f"- Recorder: `{RECORDER_ID}` (`pred.pkl`, read only)",
        f"- Control: `{CONTROL_LABEL}` (1 holding day)",
        f"- Candidate: `{CANDIDATE_LABEL}` (3 holding days)",
        "- Top10 returns use geometric per-trading-day conversion before subtracting the common-universe mean.",
        "- RankIC is daily cross-sectional Spearman; ICIR here is daily mean / daily sample standard deviation.",
        "",
        "## Window summary",
        "",
        _markdown_table(
            (
                "window",
                "days",
                "stocks/day p50",
                "missing",
                "RankIC ctl",
                "RankIC cand",
                "ΔRankIC",
                "CI low",
                "CI high",
                "Top10 ctl",
                "Top10 cand",
            ),
            overview_rows,
        ),
        "",
        "## RankIC distribution",
        "",
        _markdown_table(
            ("window", "arm", "days", "mean", "median", "ICIR (mean/std)"),
            tuple(
                (
                    name,
                    arm,
                    windows[name]["rankic"][arm]["n_days"],
                    _fmt(windows[name]["rankic"][arm]["mean"]),
                    _fmt(windows[name]["rankic"][arm]["median"]),
                    _fmt(windows[name]["rankic"][arm]["icir"]),
                )
                for name in WINDOW_NAMES
                for arm in ("control", "candidate")
            ),
        ),
        "",
        "## Quarterly stability",
        "",
    ]
    quarter_rows = []
    for name in WINDOW_NAMES:
        for row in windows[name]["quarters"]:
            quarter_rows.append(
                (
                    name,
                    row["quarter"],
                    row["days"],
                    _fmt(row["rankic_control"]),
                    _fmt(row["rankic_candidate"]),
                    _fmt(row["delta_rankic"]),
                    _fmt(row["top10_spread_control"]),
                    _fmt(row["top10_spread_candidate"]),
                    _fmt(row["delta_top10_spread"]),
                )
            )
    lines.extend(
        [
            _markdown_table(
                (
                    "window",
                    "quarter",
                    "days",
                    "RankIC ctl",
                    "RankIC cand",
                    "ΔRankIC",
                    "Top10 ctl",
                    "Top10 cand",
                    "ΔTop10",
                ),
                quarter_rows,
            ),
            "",
            "## Gates and stop rule",
            "",
            _markdown_table(
                ("gate", "pass"),
                tuple((key, value) for key, value in verdict["gates"].items()),
            ),
            "",
            f"Action: {verdict['action']}",
            "",
            "This precheck does not authorize retraining, PortAna/BT, another horizon/gate sweep, or an online change.",
            "",
            f"**verdict: {verdict['verdict']}**",
            "",
        ]
    )
    return "\n".join(lines)


def _prepare_output(out_dir: Path) -> Path:
    resolved = out_dir.expanduser().resolve()
    conflicts = [resolved / name for name in OUTPUT_FILES if (resolved / name).exists()]
    if conflicts:
        joined = ", ".join(str(path) for path in conflicts)
        raise FileExistsError(f"refuse to overwrite existing result files: {joined}")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def run(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    out_dir = _prepare_output(args.out_dir)
    _load_runtime_dependencies()
    windows = _windows_from_args(args.window)
    scores_2025, meta_2025 = _load_2025_scores(args.pred_2025)
    scores_2026, meta_2026 = _init_qlib_and_load_2026(
        provider_uri=args.provider_uri,
        mlruns_dir=args.mlruns_dir,
    )
    source_scores = {"2025_valid": scores_2025, "2026_oos": scores_2026}
    daily_parts = []
    window_summaries: dict[str, dict[str, Any]] = {}
    per_window_inputs: dict[str, Any] = {}

    for name in WINDOW_NAMES:
        start, end = windows[name]
        scores = source_scores[name]
        mask = scores["datetime"].between(pd.Timestamp(start), pd.Timestamp(end), inclusive="both")
        clipped = scores.loc[mask].copy()
        if clipped.empty:
            raise RuntimeError(f"{name}: no prediction rows in requested window {start}:{end}")
        instruments = sorted(clipped["instrument"].unique().tolist())
        labels, label_meta = _load_labels(instruments, start, end)
        daily, _complete, sample_meta = _daily_metrics(name, clipped, labels, topk=args.topk)
        sample_meta.update({"requested_start": start, "requested_end": end, "labels": label_meta})
        summary = _summarize_window(
            daily,
            sample_meta,
            block_days=args.block_days,
            reps=args.bootstrap_reps,
            seed=args.seed,
        )
        daily_parts.append(daily)
        window_summaries[name] = summary
        per_window_inputs[name] = sample_meta
        print(
            f"[summary] {name} days={sample_meta['effective_dates']} "
            f"delta_rankic={summary['rankic']['delta_candidate_minus_control']['mean']:.6f} "
            f"ci95=[{summary['delta_rankic_bootstrap']['ci_lower']:.6f},"
            f"{summary['delta_rankic_bootstrap']['ci_upper']:.6f}]",
            flush=True,
        )

    decision = _decide_verdict(window_summaries)
    generated_at = datetime.now(timezone.utc).isoformat()
    summary_payload = {
        "schema_version": 1,
        "generated_at_utc": generated_at,
        "fixed_inputs": {
            "experiment": EXPERIMENT,
            "recorder_id": RECORDER_ID,
            "control_label": CONTROL_LABEL,
            "candidate_label": CANDIDATE_LABEL,
            "topk": TOPK,
            "block_days": BLOCK_DAYS,
            "bootstrap_reps": BOOTSTRAP_REPS,
            "seed": SEED,
        },
        "windows": window_summaries,
        "decision": decision,
    }
    input_payload = {
        "schema_version": 1,
        "generated_at_utc": generated_at,
        "read_only": True,
        "pred_2025": meta_2025,
        "pred_2026": meta_2026,
        "provider_uri": str(Path(os.path.expanduser(args.provider_uri)).resolve()),
        "fixed_protocol": {
            "experiment": EXPERIMENT,
            "recorder_id": RECORDER_ID,
            "control_label": CONTROL_LABEL,
            "candidate_label": CANDIDATE_LABEL,
            "control_holding_days": CONTROL_HOLDING_DAYS,
            "candidate_holding_days": CANDIDATE_HOLDING_DAYS,
            "dailyization": "geometric",
            "topk": TOPK,
            "block_days": BLOCK_DAYS,
            "bootstrap_reps": BOOTSTRAP_REPS,
            "seed": SEED,
        },
        "windows": per_window_inputs,
        "constraints": {
            "training": False,
            "pred_writes": False,
            "portana_or_backtest": False,
            "gate_or_horizon_sweep": False,
            "online_change": False,
        },
    }

    daily_all = pd.concat(daily_parts, ignore_index=True)
    daily_all.to_csv(out_dir / "daily_metrics.csv", index=False, encoding="utf-8", lineterminator="\n")
    _write_json(out_dir / "window_summary.json", summary_payload)
    _write_json(out_dir / "input_summary.json", input_payload)
    (out_dir / "window_summary.md").write_text(
        _render_markdown(summary_payload), encoding="utf-8", newline="\n"
    )
    return out_dir, decision


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        out_dir, decision = run(args)
    except (FileNotFoundError, FileExistsError, RuntimeError, TypeError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(f"[output] {out_dir}", flush=True)
    print(f"verdict: {decision['verdict']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
