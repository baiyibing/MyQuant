# -*- coding: utf-8 -*-
"""T5-AMI1: one-shot AMIHUD20_RANK sidecar on frozen handler index."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import host_env  # noqa: F401

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
REPO_ROOT = SCRIPT_DIR.parent
RECORDER_ID = "8a061ea428e04bb3a199a485ade49d0e"
EXPERIMENT = "alpha158_cost_kdj_lgb"
DEFAULT_HANDLER_PKL = Path(r"D:\qlib_handler_cache\handler_86d82e09280b20b8.pkl")
DEFAULT_PROVIDER = r"C:/Users/wangc/.qlib/qlib_data/my_data"
FEATURE = "AMIHUD20_RANK"
LOOKBACK = 20
SAMPLE_RECOMPUTE = 16
SAMPLE_RANK_DAYS = 3


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _key_digest(df) -> str:
    keys = (df["instrument"].astype(str) + "|" + df["datetime"].dt.strftime("%Y-%m-%d")).sort_values(
        kind="mergesort"
    )
    h = hashlib.sha256()
    for k in keys:
        h.update(k.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _git_commit() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), text=True
        ).strip()
        return out
    except Exception as exc:
        return f"unavailable:{exc}"


def _calendar_fingerprint(provider: Path) -> dict[str, Any]:
    cal_path = provider / "calendars" / "day.txt"
    if not cal_path.is_file():
        raise FileNotFoundError(cal_path)
    inst_path = provider / "instruments" / "all.txt"
    fp: dict[str, Any] = {
        "provider_uri": str(provider),
        "calendar_path": str(cal_path),
        "calendar_sha256": _sha256(cal_path),
        "calendar_size_bytes": int(cal_path.stat().st_size),
    }
    if inst_path.is_file():
        fp["instruments_all_sha256"] = _sha256(inst_path)
        fp["instruments_all_path"] = str(inst_path)
    return fp


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Export AMIHUD20_RANK sidecar once")
    p.add_argument("--experiment", default=EXPERIMENT)
    p.add_argument("--recorder-id", default=RECORDER_ID)
    p.add_argument("--handler-index-source", default="recorder-handler")
    p.add_argument("--handler-pkl", type=Path, default=DEFAULT_HANDLER_PKL)
    p.add_argument("--provider-uri", default=DEFAULT_PROVIDER)
    p.add_argument("--freeze-provider-snapshot", action="store_true")
    p.add_argument("--close-field", default="$close")
    p.add_argument("--amount-field", default="$amount")
    p.add_argument("--lookback-market-days", type=int, default=LOOKBACK)
    p.add_argument("--require-complete-window", action="store_true")
    p.add_argument("--impact", default="abs-return-over-amount")
    p.add_argument("--rank-method", default="average")
    p.add_argument("--rank-pct", default="pandas-pct-true")
    p.add_argument("--feature-name", default=FEATURE)
    p.add_argument("--start", default="2020-01-02")
    p.add_argument("--end", default="2026-09-14")
    p.add_argument("--emit-source-qc", action="store_true")
    p.add_argument("--emit-hash-and-key-digest", action="store_true")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--fail-if-out-exists", action="store_true")
    p.add_argument("--mlruns-dir", type=Path, default=SCRIPT_DIR / "mlruns")
    p.add_argument("--sample-recompute", type=int, default=SAMPLE_RECOMPUTE)
    return p


def _require_frozen(args) -> None:
    if args.handler_index_source != "recorder-handler":
        raise ValueError(f"handler-index-source must be recorder-handler, got {args.handler_index_source}")
    if args.close_field != "$close":
        raise ValueError(f"close-field must be $close, got {args.close_field}")
    if args.amount_field != "$amount":
        raise ValueError(f"amount-field must be $amount, got {args.amount_field}")
    if int(args.lookback_market_days) != LOOKBACK:
        raise ValueError(f"lookback-market-days must be {LOOKBACK}")
    if args.impact != "abs-return-over-amount":
        raise ValueError(f"impact must be abs-return-over-amount, got {args.impact}")
    if args.rank_method != "average":
        raise ValueError(f"rank-method must be average, got {args.rank_method}")
    if args.rank_pct != "pandas-pct-true":
        raise ValueError(f"rank-pct must be pandas-pct-true, got {args.rank_pct}")
    if args.feature_name != FEATURE:
        raise ValueError(f"feature-name must be {FEATURE}, got {args.feature_name}")
    if not args.require_complete_window:
        raise ValueError("--require-complete-window is mandatory")
    if not args.freeze_provider_snapshot:
        raise ValueError("--freeze-provider-snapshot is mandatory")


def _handler_keys(handler, start, end, pd):
    infer = handler._infer
    idx = infer.index
    names = list(idx.names)
    if names == ["datetime", "instrument"]:
        base = pd.DataFrame(
            {
                "datetime": pd.to_datetime(idx.get_level_values("datetime")).normalize(),
                "instrument": idx.get_level_values("instrument").astype(str),
            }
        )
    elif names == ["instrument", "datetime"]:
        base = pd.DataFrame(
            {
                "datetime": pd.to_datetime(idx.get_level_values("datetime")).normalize(),
                "instrument": idx.get_level_values("instrument").astype(str),
            }
        )
    else:
        raise ValueError(f"unexpected index names {idx.names}")
    base = base.loc[(base["datetime"] >= start) & (base["datetime"] <= end)].copy()
    return infer, base


def _missing_reason(close_ok: bool, amount_ok: bool, window_complete: bool) -> str:
    if window_complete and close_ok and amount_ok:
        return ""
    parts = []
    if not close_ok:
        parts.append("close_invalid")
    if not amount_ok:
        parts.append("amount_invalid")
    if not window_complete:
        parts.append("incomplete_window")
    return "|".join(parts) if parts else "unknown"


def _recompute_one(instrument: str, t, calendar, close_field: str, amount_field: str, lookback: int, pd, np):
    from qlib.data import D

    pos = calendar.get_loc(t)
    if isinstance(pos, slice) or (hasattr(pos, "__len__") and not isinstance(pos, (int, np.integer))):
        raise KeyError(t)
    pos = int(pos)
    if pos < lookback:
        return None, "not_enough_history"
    days = calendar[pos - lookback : pos + 1]  # t-20 .. t  (21 closes)
    raw = D.features([instrument], [close_field, amount_field], start_time=days[0], end_time=days[-1])
    if raw is None or raw.empty:
        return None, "empty_features"
    frame = raw.reset_index() if isinstance(raw.index, pd.MultiIndex) else raw.copy()
    frame["datetime"] = pd.to_datetime(frame["datetime"]).dt.normalize()
    frame = frame.set_index("datetime").reindex(days)
    close = pd.to_numeric(frame[close_field], errors="coerce")
    amount = pd.to_numeric(frame[amount_field], errors="coerce")
    prev = close.shift(1)
    close_ok = close.notna() & np.isfinite(close) & (close > 0)
    prev_ok = prev.notna() & np.isfinite(prev) & (prev > 0)
    amount_ok = amount.notna() & np.isfinite(amount) & (amount > 0)
    daily_ok = close_ok & prev_ok & amount_ok
    window_days = days[1:]  # t-19 .. t
    if not bool(daily_ok.loc[window_days].all()):
        return None, "incomplete_window"
    ret = (close / prev - 1.0).abs()
    impact = (ret / amount).loc[window_days]
    if not np.isfinite(impact.to_numpy(dtype=float)).all():
        return None, "nonfinite_impact"
    return float(impact.mean()), ""


def main(argv: list[str] | None = None) -> int:
    import numpy as np
    import pandas as pd
    import qlib
    from qlib.config import REG_CN
    from qlib.data import D

    args = build_parser().parse_args(argv)
    _require_frozen(args)

    out_dir = args.out_dir.expanduser().resolve()
    if args.fail_if_out_exists and out_dir.exists():
        raise FileExistsError(f"refuse to reuse existing out-dir {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=False)

    handler_pkl = args.handler_pkl.expanduser().resolve()
    if not handler_pkl.is_file():
        raise FileNotFoundError(handler_pkl)

    provider = Path(os.path.expanduser(args.provider_uri)).resolve()
    snap = _calendar_fingerprint(provider)
    commit = _git_commit()
    print(f"[freeze] provider={provider}", flush=True)
    print(f"[freeze] calendar_sha256={snap['calendar_sha256']}", flush=True)
    print(f"[freeze] commit={commit}", flush=True)

    qlib.init(provider_uri=str(provider), region=REG_CN, kernels=1)

    from custom_handler import Alpha158CostKDJ

    print(f"[handler] load {handler_pkl}", flush=True)
    handler = Alpha158CostKDJ.load(str(handler_pkl))
    start = pd.Timestamp(args.start).normalize()
    end = pd.Timestamp(args.end).normalize()
    infer, base = _handler_keys(handler, start, end, pd)
    if base.empty:
        raise RuntimeError("handler index empty in sidecar window")
    if int(base.duplicated(["datetime", "instrument"]).sum()):
        raise RuntimeError("handler keys not unique")
    print(
        f"[handler] rows in window={len(base)} instruments={base['instrument'].nunique()} "
        f"days={base['datetime'].nunique()}",
        flush=True,
    )

    cal = pd.DatetimeIndex(pd.to_datetime(list(D.calendar()))).normalize().unique().sort_values()
    snap["calendar_first"] = str(cal[0].date())
    snap["calendar_last"] = str(cal[-1].date())
    snap["calendar_days"] = int(len(cal))
    if cal[-1] < end:
        raise RuntimeError(f"calendar last {cal[-1].date()} < sidecar end {end.date()}")
    start_pos = int(cal.searchsorted(start))
    # Frozen provider calendar starts 2020-01-02; do not invent earlier days.
    # Rows without 20 prior market days stay missing (incomplete_window).
    look_idx = max(0, start_pos - int(args.lookback_market_days))
    raw_start = cal[look_idx]
    print(
        f"[calendar] raw_start={raw_start.date()} start={start.date()} end={end.date()} "
        f"n={len(cal)} lookback_available={start_pos - look_idx}",
        flush=True,
    )

    instruments = sorted(base["instrument"].unique().tolist())
    print(
        f"[features] D.features n={len(instruments)} fields={args.close_field},{args.amount_field}",
        flush=True,
    )
    raw = D.features(
        instruments,
        [args.close_field, args.amount_field],
        start_time=raw_start,
        end_time=end,
    )
    if raw is None or raw.empty:
        raise RuntimeError("close/amount features empty")
    feat = raw.reset_index() if isinstance(raw.index, pd.MultiIndex) else raw.copy()
    if args.close_field not in feat.columns or args.amount_field not in feat.columns:
        raise ValueError(f"unexpected feature columns: {list(feat.columns)}")
    feat["datetime"] = pd.to_datetime(feat["datetime"]).dt.normalize()
    feat["instrument"] = feat["instrument"].astype(str)
    feat["close"] = pd.to_numeric(feat[args.close_field], errors="coerce")
    feat["amount"] = pd.to_numeric(feat[args.amount_field], errors="coerce")

    cal_window = cal[(cal >= raw_start) & (cal <= end)]
    close_w = feat.pivot_table(index="datetime", columns="instrument", values="close", aggfunc="last")
    amount_w = feat.pivot_table(index="datetime", columns="instrument", values="amount", aggfunc="last")
    close_w = close_w.reindex(cal_window)
    amount_w = amount_w.reindex(cal_window)
    # keep handler instruments only (never rank a broader market first)
    close_w = close_w.reindex(columns=instruments)
    amount_w = amount_w.reindex(columns=instruments)

    prev = close_w.shift(1)
    ret = (close_w / prev - 1.0).abs()
    close_ok = close_w.notna() & np.isfinite(close_w) & (close_w > 0)
    prev_ok = prev.notna() & np.isfinite(prev) & (prev > 0)
    amount_ok = amount_w.notna() & np.isfinite(amount_w) & (amount_w > 0)
    daily_ok = close_ok & prev_ok & amount_ok
    impact_d = (ret / amount_w).where(daily_ok)
    n_ok = daily_ok.astype("int16").rolling(args.lookback_market_days, min_periods=args.lookback_market_days).sum()
    impact20_w = impact_d.rolling(args.lookback_market_days, min_periods=args.lookback_market_days).mean()
    impact20_w = impact20_w.where(n_ok == args.lookback_market_days)

    def _melt(wide, name):
        long = wide.stack(dropna=False).rename(name)
        long.index = long.index.set_names(["datetime", "instrument"])
        return long.reset_index()

    long = _melt(impact20_w.loc[start:end], "impact20")
    long = long.merge(_melt(close_w.loc[start:end], "close"), on=["datetime", "instrument"], how="left")
    long = long.merge(_melt(amount_w.loc[start:end], "amount"), on=["datetime", "instrument"], how="left")
    long = long.merge(_melt(n_ok.loc[start:end], "n_valid_window_days"), on=["datetime", "instrument"], how="left")
    long = long.merge(_melt(close_ok.loc[start:end], "close_ok"), on=["datetime", "instrument"], how="left")
    long = long.merge(_melt(amount_ok.loc[start:end], "amount_ok"), on=["datetime", "instrument"], how="left")
    long["datetime"] = pd.to_datetime(long["datetime"]).dt.normalize()
    long["instrument"] = long["instrument"].astype(str)
    long["n_valid_window_days"] = pd.to_numeric(long["n_valid_window_days"], errors="coerce")
    long["close_ok"] = long["close_ok"].fillna(False).astype(bool)
    long["amount_ok"] = long["amount_ok"].fillna(False).astype(bool)
    long["window_complete"] = (long["n_valid_window_days"] == args.lookback_market_days) & long["impact20"].notna()
    long["missing_reason"] = [
        _missing_reason(bool(c), bool(a), bool(w))
        for c, a, w in zip(long["close_ok"], long["amount_ok"], long["window_complete"])
    ]

    out = base.merge(long, on=["datetime", "instrument"], how="left")
    if len(out) != len(base):
        raise RuntimeError(f"left-join changed row count {len(base)} -> {len(out)}")
    out["close_ok"] = out["close_ok"].fillna(False).astype(bool)
    out["amount_ok"] = out["amount_ok"].fillna(False).astype(bool)
    out["window_complete"] = out["window_complete"].fillna(False).astype(bool)
    out["n_valid_window_days"] = pd.to_numeric(out["n_valid_window_days"], errors="coerce")
    out["missing_reason"] = out["missing_reason"].fillna("not_in_raw_panel")
    # rank ONLY on handler-day ∩ finite impact20 (already handler keys)
    ok = out["impact20"].notna() & np.isfinite(out["impact20"])
    out[args.feature_name] = np.nan
    out.loc[ok, args.feature_name] = out.loc[ok].groupby("datetime", sort=False)["impact20"].rank(
        method="average", pct=True
    )
    rank_n = out.loc[ok].groupby("datetime", sort=False)[args.feature_name].transform("size")
    out["rank_n"] = np.nan
    out.loc[ok, "rank_n"] = rank_n
    out = out.sort_values(["datetime", "instrument"], kind="mergesort").reset_index(drop=True)

    if int(out.duplicated(["datetime", "instrument"]).sum()):
        raise RuntimeError("sidecar keys not unique after join")
    if pd.to_datetime(out["datetime"]).min() < start or pd.to_datetime(out["datetime"]).max() > end:
        raise RuntimeError("sidecar datetime outside frozen window")

    # sample recompute of impact20 from raw D.features
    rng = np.random.default_rng(20260918)
    finite = out.loc[ok]
    sample_qc = []
    if args.sample_recompute > 0 and len(finite):
        take = min(int(args.sample_recompute), len(finite))
        picks = finite.sample(n=take, random_state=int(rng.integers(0, 2**31 - 1)))
        for _, row in picks.iterrows():
            got, reason = _recompute_one(
                str(row["instrument"]),
                pd.Timestamp(row["datetime"]).normalize(),
                cal,
                args.close_field,
                args.amount_field,
                int(args.lookback_market_days),
                pd,
                np,
            )
            stored = float(row["impact20"])
            match = got is not None and np.isfinite(got) and abs(got - stored) <= max(1e-12, 1e-9 * abs(stored))
            sample_qc.append(
                {
                    "instrument": str(row["instrument"]),
                    "datetime": pd.Timestamp(row["datetime"]).date().isoformat(),
                    "stored": stored,
                    "recomputed": got,
                    "match": bool(match),
                    "reason": reason,
                }
            )
        n_bad = sum(1 for x in sample_qc if not x["match"])
        if n_bad:
            raise RuntimeError(f"sample impact20 recompute failed: {n_bad}/{len(sample_qc)}")
        print(f"[qc] impact20 recompute ok n={len(sample_qc)}", flush=True)

    # rank consistency on a few days from stored impact20
    rank_qc = []
    days = out.loc[ok, "datetime"].drop_duplicates().tolist()
    if days:
        take_days = min(SAMPLE_RANK_DAYS, len(days))
        day_picks = [days[i] for i in rng.choice(len(days), size=take_days, replace=False)]
        for day in day_picks:
            g = out.loc[out["datetime"] == day]
            valid = g["impact20"].notna() & np.isfinite(g["impact20"])
            recomputed = g.loc[valid, "impact20"].rank(method="average", pct=True)
            stored_r = g.loc[valid, args.feature_name]
            max_diff = float((recomputed - stored_r).abs().max()) if len(recomputed) else 0.0
            rank_qc.append(
                {
                    "datetime": pd.Timestamp(day).date().isoformat(),
                    "n": int(valid.sum()),
                    "max_abs_diff": max_diff,
                }
            )
            if max_diff > 1e-12:
                raise RuntimeError(f"rank recompute mismatch on {day}: {max_diff}")
        print(f"[qc] rank recompute ok days={len(rank_qc)}", flush=True)

    # timing: lookback window ends at t
    timing_ok = True
    if len(finite):
        row = finite.iloc[int(rng.integers(0, len(finite)))]
        t = pd.Timestamp(row["datetime"]).normalize()
        pos = int(cal.get_loc(t))
        window_end = cal[pos]
        timing_ok = bool(window_end == t and cal[pos - args.lookback_market_days] <= t)
        if not timing_ok:
            raise RuntimeError("timing check failed: window uses dates after t")

    parquet_path = out_dir / f"{args.feature_name}.parquet"
    cols = [
        "instrument",
        "datetime",
        "close",
        "amount",
        "impact20",
        args.feature_name,
        "n_valid_window_days",
        "close_ok",
        "amount_ok",
        "window_complete",
        "missing_reason",
        "rank_n",
    ]
    out[cols].to_parquet(parquet_path, index=False)
    sidecar_sha = _sha256(parquet_path)
    key_digest = _key_digest(out)

    n_finite = int(ok.sum())
    manifest = {
        "generated_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "experiment": args.experiment,
        "recorder_id": args.recorder_id,
        "handler_pkl": str(handler_pkl),
        "handler_infer_rows": int(len(infer)),
        "window": {"start": args.start, "end": args.end},
        "provider_uri": str(provider),
        "provider_snapshot": snap,
        "git_commit": commit,
        "close_field": args.close_field,
        "amount_field": args.amount_field,
        "lookback_market_days": int(args.lookback_market_days),
        "require_complete_window": True,
        "impact": args.impact,
        "rank": "pandas.Series.rank(method=average, pct=True) on handler-day ∩ valid impact20",
        "feature_name": args.feature_name,
        "sidecar_path": str(parquet_path),
        "sidecar_sha256": sidecar_sha,
        "key_digest": key_digest,
        "n_rows": int(len(out)),
        "n_instruments": int(out["instrument"].nunique()),
        "n_days": int(out["datetime"].nunique()),
        "n_finite_rank": n_finite,
        "missing_reason_counts": out["missing_reason"].fillna("").value_counts().to_dict(),
        "sample_recompute": sample_qc,
        "rank_recompute": rank_qc,
        "timing_ok": timing_ok,
        "direction": "higher_impact_higher_expected_return",
        "no_sign_flip": True,
        "online_untouched": True,
    }
    if not args.emit_hash_and_key_digest:
        raise ValueError("--emit-hash-and-key-digest is mandatory")
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "sidecar_sha256": sidecar_sha,
                "key_digest": key_digest,
                "rows": int(len(out)),
                "n_finite_rank": n_finite,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    print(f"[out] {parquet_path}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        raise
