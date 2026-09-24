# -*- coding: utf-8 -*-
"""T5-WRD1: one-shot BROKER_WR_GAP sidecar on frozen handler index."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import host_env  # noqa: F401

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
RECORDER_ID = "8a061ea428e04bb3a199a485ade49d0e"
EXPERIMENT = "alpha158_cost_kdj_lgb"
DEFAULT_HANDLER_PKL = Path.home() / ".cache/qlib_handler_cache/handler_86d82e09280b20b8.pkl"
EXPECTED_CYQ_SHA = "d167d27916920ea7c49a3f0cb2202de2bb64b7a4425a7852de64f0b278c88a34"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _key_digest(df) -> str:
    # stable row-key digest: instrument|YYYY-MM-DD sorted
    keys = (
        df["instrument"].astype(str)
        + "|"
        + df["datetime"].dt.strftime("%Y-%m-%d")
    ).sort_values(kind="mergesort")
    h = hashlib.sha256()
    for k in keys:
        h.update(k.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Export BROKER_WR_GAP sidecar once")
    p.add_argument("--experiment", default=EXPERIMENT)
    p.add_argument("--recorder-id", default=RECORDER_ID)
    p.add_argument("--handler-index-source", default="recorder-handler")
    p.add_argument("--handler-pkl", type=Path, default=DEFAULT_HANDLER_PKL)
    p.add_argument("--provider-uri", default="~/.qlib/qlib_data/my_data")
    p.add_argument("--freeze-provider-snapshot", action="store_true")
    p.add_argument("--read-broker-field-once", action="store_true")
    p.add_argument("--broker-field", default="$winratio")
    p.add_argument("--cyq-file", type=Path, required=True)
    p.add_argument("--cyq-column", default="winner_ratio")
    p.add_argument("--cyq-sha256", default=EXPECTED_CYQ_SHA)
    p.add_argument("--start", default="2020-01-02")
    p.add_argument("--end", default="2026-09-14")
    p.add_argument("--rank-method", default="average")
    p.add_argument("--rank-pct", default="pandas-pct-true")
    p.add_argument("--direction", choices=("lower",), default="lower")
    p.add_argument("--min-ols-n", type=int, default=3)
    p.add_argument("--fit-universe", default="handler-daily-valid-intersection")
    p.add_argument("--fit-once", action="store_true")
    p.add_argument("--feature-name", default="BROKER_WR_GAP")
    p.add_argument("--emit-source-columns", action="store_true")
    p.add_argument("--emit-q-v", action="store_true")
    p.add_argument("--emit-ols-qc", action="store_true")
    p.add_argument("--emit-hash-and-key-digest", action="store_true")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--fail-if-out-exists", action="store_true")
    p.add_argument("--mlruns-dir", type=Path, default=SCRIPT_DIR / "mlruns")
    return p


def main(argv: list[str] | None = None) -> int:
    import numpy as np
    import pandas as pd
    import qlib
    from qlib.config import REG_CN
    from qlib.data import D

    args = build_parser().parse_args(argv)
    out_dir = args.out_dir.expanduser().resolve()
    if args.fail_if_out_exists and out_dir.exists() and any(out_dir.iterdir()):
        # allow empty dir; refuse if parquet/manifest present
        for name in ("BROKER_WR_GAP.parquet", "manifest.json"):
            if (out_dir / name).exists():
                raise FileExistsError(f"refuse to overwrite {out_dir / name}")
    out_dir.mkdir(parents=True, exist_ok=True)

    cyq_path = args.cyq_file.expanduser().resolve()
    if not cyq_path.is_file():
        raise FileNotFoundError(cyq_path)
    cyq_sha = _sha256(cyq_path)
    if cyq_sha.lower() != args.cyq_sha256.lower():
        raise RuntimeError(f"CYQ SHA mismatch: {cyq_sha} != {args.cyq_sha256}")
    print(f"[cyq] sha ok {cyq_sha}", flush=True)

    handler_pkl = args.handler_pkl.expanduser().resolve()
    if not handler_pkl.is_file():
        raise FileNotFoundError(handler_pkl)

    provider = Path(os.path.expanduser(args.provider_uri)).resolve()
    qlib.init(provider_uri=str(provider), region=REG_CN, kernels=1)

    from custom_handler import Alpha158CostKDJ

    print(f"[handler] load {handler_pkl}", flush=True)
    handler = Alpha158CostKDJ.load(str(handler_pkl))
    infer = handler._infer
    idx = infer.index
    # normalize to columns
    if list(idx.names) == ["datetime", "instrument"]:
        base = pd.DataFrame(
            {
                "datetime": pd.to_datetime(idx.get_level_values("datetime")).normalize(),
                "instrument": idx.get_level_values("instrument").astype(str),
            }
        )
    elif list(idx.names) == ["instrument", "datetime"]:
        base = pd.DataFrame(
            {
                "datetime": pd.to_datetime(idx.get_level_values("datetime")).normalize(),
                "instrument": idx.get_level_values("instrument").astype(str),
            }
        )
    else:
        raise ValueError(f"unexpected index names {idx.names}")

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)
    base = base.loc[(base["datetime"] >= start) & (base["datetime"] <= end)].copy()
    print(f"[handler] rows in window={len(base)} instruments={base['instrument'].nunique()}", flush=True)

    # CYQ
    cyq = pd.read_parquet(cyq_path)
    code_col = "stock_code" if "stock_code" in cyq.columns else "instrument"
    date_col = "date" if "date" in cyq.columns else "datetime"
    cyq = pd.DataFrame(
        {
            "datetime": pd.to_datetime(cyq[date_col]).dt.normalize(),
            "instrument": cyq[code_col].astype(str),
            "exact_winner_ratio": pd.to_numeric(cyq[args.cyq_column], errors="coerce"),
        }
    )

    # broker field once
    instruments = sorted(base["instrument"].unique().tolist())
    print(f"[broker] D.features n={len(instruments)} field={args.broker_field}", flush=True)
    raw = D.features(instruments, [args.broker_field], start_time=args.start, end_time=args.end)
    if raw is None or raw.empty:
        raise RuntimeError("broker field empty")
    br = raw.reset_index() if isinstance(raw.index, pd.MultiIndex) else raw.copy()
    if args.broker_field not in br.columns:
        vals = [c for c in br.columns if c not in {"datetime", "instrument"}]
        if len(vals) != 1:
            raise ValueError(br.columns)
        br = br.rename(columns={vals[0]: args.broker_field})
    br = br.rename(columns={args.broker_field: "broker_winratio"})
    br["datetime"] = pd.to_datetime(br["datetime"]).dt.normalize()
    br["instrument"] = br["instrument"].astype(str)
    br["broker_winratio"] = pd.to_numeric(br["broker_winratio"], errors="coerce")

    merged = base.merge(cyq, on=["datetime", "instrument"], how="left")
    merged = merged.merge(br, on=["datetime", "instrument"], how="left")
    print(f"[join] rows={len(merged)}", flush=True)

    # daily OLS once
    rows = []
    deg_counts: dict[str, int] = {}
    for day, g in merged.groupby("datetime", sort=True):
        m = g.copy()
        ok = (
            m["exact_winner_ratio"].notna()
            & m["broker_winratio"].notna()
            & (m["exact_winner_ratio"] >= 0)
            & (m["exact_winner_ratio"] <= 1)
            & (m["broker_winratio"] >= 0)
            & (m["broker_winratio"] <= 1)
        )
        sample = m.loc[ok]
        n = int(len(sample))
        reason = ""
        q = v = resid = None
        if n < args.min_ols_n:
            reason = "n_lt_min"
        else:
            q = (-sample["exact_winner_ratio"]).rank(method="average", pct=True)
            v = (-sample["broker_winratio"]).rank(method="average", pct=True)
            if q.nunique() < 2 or v.nunique() < 2:
                reason = "zero_variance_rank"
            else:
                X = np.column_stack([np.ones(n), q.to_numpy(dtype=float)])
                y = v.to_numpy(dtype=float)
                try:
                    beta, _, rank, _ = np.linalg.lstsq(X, y, rcond=None)
                    if rank < 2:
                        reason = "rank_deficient"
                    else:
                        resid = y - X @ beta
                        if not np.isfinite(resid).all():
                            reason = "resid_nonfinite"
                except Exception:
                    reason = "ols_fail"
        if reason:
            deg_counts[reason] = deg_counts.get(reason, 0) + 1
            for i, r in m.iterrows():
                rows.append(
                    {
                        "datetime": day,
                        "instrument": r["instrument"],
                        "broker_winratio": r["broker_winratio"],
                        "exact_winner_ratio": r["exact_winner_ratio"],
                        "q": np.nan,
                        "v": np.nan,
                        args.feature_name: np.nan,
                        "ols_n": n,
                        "degenerate_reason": reason,
                    }
                )
            continue
        # map residuals back
        sample = sample.copy()
        sample["q"] = q.to_numpy()
        sample["v"] = v.to_numpy()
        sample[args.feature_name] = resid
        sample["ols_n"] = n
        sample["degenerate_reason"] = ""
        # non-sample handler rows that day → missing feature
        out_day = m[["datetime", "instrument", "broker_winratio", "exact_winner_ratio"]].merge(
            sample[["instrument", "q", "v", args.feature_name, "ols_n", "degenerate_reason"]],
            on="instrument",
            how="left",
        )
        out_day["ols_n"] = out_day["ols_n"].fillna(n)
        out_day["degenerate_reason"] = out_day["degenerate_reason"].fillna("not_in_ols_sample")
        rows.extend(out_day.to_dict("records"))

    out = pd.DataFrame(rows)
    out["datetime"] = pd.to_datetime(out["datetime"]).dt.normalize()
    out["instrument"] = out["instrument"].astype(str)
    out = out.sort_values(["datetime", "instrument"], kind="mergesort").reset_index(drop=True)

    parquet_path = out_dir / f"{args.feature_name}.parquet"
    out.to_parquet(parquet_path, index=False)
    sidecar_sha = _sha256(parquet_path)
    key_digest = _key_digest(out)

    # orth check on finite g,q: corr should be ~0
    finite = out.dropna(subset=[args.feature_name, "q"])
    orth = float(np.corrcoef(finite[args.feature_name], finite["q"])[0, 1]) if len(finite) > 10 else None

    manifest = {
        "generated_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "experiment": args.experiment,
        "recorder_id": args.recorder_id,
        "handler_pkl": str(handler_pkl),
        "handler_infer_rows": int(len(infer)),
        "window": {"start": args.start, "end": args.end},
        "cyq_file": str(cyq_path),
        "cyq_sha256": cyq_sha,
        "broker_field": args.broker_field,
        "provider_uri": str(provider),
        "feature_name": args.feature_name,
        "sidecar_path": str(parquet_path),
        "sidecar_sha256": sidecar_sha,
        "key_digest": key_digest,
        "n_rows": int(len(out)),
        "n_instruments": int(out["instrument"].nunique()),
        "n_days": int(out["datetime"].nunique()),
        "degenerate_day_counts": deg_counts,
        "corr_g_q_finite": orth,
        "min_ols_n": args.min_ols_n,
        "fit_once": True,
        "rank": "pandas.Series.rank(method=average, pct=True) on -levels",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"sidecar_sha256": sidecar_sha, "key_digest": key_digest, "rows": len(out), "orth_g_q": orth}, ensure_ascii=False), flush=True)
    print(f"[out] {parquet_path}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        raise
