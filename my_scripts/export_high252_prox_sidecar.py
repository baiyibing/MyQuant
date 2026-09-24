# -*- coding: utf-8 -*-
"""T5-H52A1: one-shot HIGH252_PROX_RANK sidecar on frozen handler index.

high_close_252 = max(close, d=t-251..t) over 252 market days (window includes t).
high252_prox = close[t] / high_close_252. Rank is on high252_prox itself (no * -1).
Any illegal close in the window → row missing. No expansion, ffill, min_periods,
or “high since listing”. Not MAXRET: max of close levels, not max daily return.
"""
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
FEATURE = "HIGH252_PROX_RANK"
WINDOW = 252  # t-251..t inclusive
WARMUP = WINDOW - 1  # exactly 251 preceding market days for a 2020 start
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
    p = argparse.ArgumentParser(description="Export HIGH252_PROX_RANK sidecar once")
    p.add_argument("--experiment", default=EXPERIMENT)
    p.add_argument("--recorder-id", default=RECORDER_ID)
    p.add_argument("--handler-index-source", default="recorder-handler")
    p.add_argument("--handler-pkl", type=Path, default=DEFAULT_HANDLER_PKL)
    p.add_argument("--provider-uri", default=DEFAULT_PROVIDER)
    p.add_argument("--freeze-provider-snapshot", action="store_true")
    p.add_argument("--close-field", default="$close")
    p.add_argument("--lookback-market-days", type=int, default=WINDOW)
    p.add_argument("--require-complete-window", action="store_true")
    p.add_argument("--anchor", default="highest-close")
    p.add_argument("--ratio", dest="ratio_kind", default="current-close-over-anchor")
    p.add_argument("--no-window-extension", action="store_true")
    p.add_argument("--no-close-imputation", action="store_true")
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
    if int(args.lookback_market_days) != WINDOW:
        raise ValueError(f"lookback-market-days must be {WINDOW} (t-251..t); 250 is forbidden")
    if args.anchor != "highest-close":
        raise ValueError(f"--anchor must be highest-close, got {args.anchor}")
    if args.ratio_kind != "current-close-over-anchor":
        raise ValueError(f"--ratio must be current-close-over-anchor, got {args.ratio_kind}")
    if not args.require_complete_window:
        raise ValueError("--require-complete-window is mandatory")
    if not args.no_window_extension:
        raise ValueError("--no-window-extension is mandatory")
    if not args.no_close_imputation:
        raise ValueError("--no-close-imputation is mandatory")
    if args.rank_method != "average":
        raise ValueError(f"rank-method must be average, got {args.rank_method}")
    if args.rank_pct != "pandas-pct-true":
        raise ValueError(f"rank-pct must be pandas-pct-true, got {args.rank_pct}")
    if args.feature_name != FEATURE:
        raise ValueError(f"feature-name must be {FEATURE}, got {args.feature_name}")
    if not args.freeze_provider_snapshot:
        raise ValueError("--freeze-provider-snapshot is mandatory")
    if not args.emit_source_qc:
        raise ValueError("--emit-source-qc is mandatory")
    if not args.emit_hash_and_key_digest:
        raise ValueError("--emit-hash-and-key-digest is mandatory")


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
    names_flat = []
    for c in infer.columns:
        if isinstance(c, tuple):
            names_flat.append(str(c[-1]))
        else:
            names_flat.append(str(c))
    if FEATURE in names_flat:
        raise RuntimeError(f"{FEATURE} already present in frozen handler; refuse to overwrite")
    base = base.loc[(base["datetime"] >= start) & (base["datetime"] <= end)].copy()
    return infer, base, names_flat


def _missing_reason(close_ok: bool, window_complete: bool) -> str:
    if window_complete and close_ok:
        return ""
    parts = []
    if not close_ok:
        parts.append("close_invalid")
    if not window_complete:
        parts.append("incomplete_window")
    return "|".join(parts) if parts else "unknown"


def _recompute_one(instrument: str, t, calendar, close_field: str, window: int, pd, np):
    from qlib.data import D

    pos = calendar.get_loc(t)
    if isinstance(pos, slice) or (hasattr(pos, "__len__") and not isinstance(pos, (int, np.integer))):
        raise KeyError(t)
    pos = int(pos)
    warmup = window - 1
    if pos < warmup:
        return None, None, None, None, "not_enough_history"
    days = calendar[pos - warmup : pos + 1]  # t-251 .. t  (252 closes)
    if len(days) != window:
        return None, None, None, None, "not_enough_history"
    if days[-1] != t:
        return None, None, None, None, "timing"
    raw = D.features([instrument], [close_field], start_time=days[0], end_time=days[-1])
    if raw is None or raw.empty:
        return None, None, None, None, "empty_features"
    frame = raw.reset_index() if isinstance(raw.index, pd.MultiIndex) else raw.copy()
    frame["datetime"] = pd.to_datetime(frame["datetime"]).dt.normalize()
    frame = frame.set_index("datetime").reindex(days)
    close = pd.to_numeric(frame[close_field], errors="coerce")
    close_ok = close.notna() & np.isfinite(close) & (close > 0)
    if not bool(close_ok.all()) or int(close_ok.sum()) != window:
        return None, None, None, None, "incomplete_window"
    vals = close.to_numpy(dtype=float)
    high = float(np.max(vals))
    # Earliest date among ties; audit only, never used to break rank ties.
    high_idx = int(np.argmax(vals))
    high_date = pd.Timestamp(days[high_idx]).normalize()
    close_t = float(vals[-1])
    prox = close_t / high
    n_close = int(window)
    return high, high_date, prox, n_close, ""


def _rolling_first_high_dates(close_w, close_ok, window: int, np, pd):
    """Earliest date of the window max close. Audit-only; not a feature."""
    from numpy.lib.stride_tricks import sliding_window_view

    n_rows, n_cols = close_w.shape
    date_ns = close_w.index.values.astype("datetime64[ns]")
    values = close_w.to_numpy(dtype=np.float64, copy=False)
    ok_mat = close_ok.to_numpy()
    out = np.empty((n_rows, n_cols), dtype="datetime64[ns]")
    out[:] = np.datetime64("NaT")
    if n_rows < window:
        return pd.DataFrame(out, index=close_w.index, columns=close_w.columns)
    for j in range(n_cols):
        if j and j % 1000 == 0:
            print(f"[high-date] columns {j}/{n_cols}", flush=True)
        col = values[:, j]
        okj = ok_mat[:, j]
        views = sliding_window_view(col, window)
        ok_views = sliding_window_view(okj, window)
        finite = np.isfinite(views)
        complete = ok_views.all(axis=1) & finite.all(axis=1)
        if not bool(complete.any()):
            continue
        work = np.where(finite, views, -np.inf)
        arg = np.argmax(work, axis=1)  # first occurrence of max
        starts = np.arange(n_rows - window + 1)
        chosen = starts + arg
        hd = np.empty(n_rows - window + 1, dtype="datetime64[ns]")
        hd[:] = np.datetime64("NaT")
        hd[complete] = date_ns[chosen[complete]]
        out[window - 1 :, j] = hd
    return pd.DataFrame(out, index=close_w.index, columns=close_w.columns)


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
    infer, base, feat_names = _handler_keys(handler, start, end, pd)
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
    # Exactly 251 preceding market days of warmup for the 2020 start; never read more,
    # never invent earlier days that are not on the frozen calendar.
    if start_pos >= WARMUP:
        look_idx = start_pos - WARMUP
        lookback_available = WARMUP
    else:
        look_idx = 0
        lookback_available = start_pos
    raw_start = cal[look_idx]
    if lookback_available > WARMUP:
        raise RuntimeError("warmup exceeded 251 preceding market days")
    print(
        f"[calendar] raw_start={raw_start.date()} start={start.date()} end={end.date()} "
        f"n={len(cal)} warmup_requested={WARMUP} lookback_available={lookback_available}",
        flush=True,
    )

    instruments = sorted(base["instrument"].unique().tolist())
    print(
        f"[features] D.features n={len(instruments)} field={args.close_field}",
        flush=True,
    )
    raw = D.features(
        instruments,
        [args.close_field],
        start_time=raw_start,
        end_time=end,
    )
    if raw is None or raw.empty:
        raise RuntimeError("close features empty")
    feat = raw.reset_index() if isinstance(raw.index, pd.MultiIndex) else raw.copy()
    if args.close_field not in feat.columns:
        raise ValueError(f"unexpected feature columns: {list(feat.columns)}")
    feat["datetime"] = pd.to_datetime(feat["datetime"]).dt.normalize()
    feat["instrument"] = feat["instrument"].astype(str)
    feat["close"] = pd.to_numeric(feat[args.close_field], errors="coerce")

    cal_window = cal[(cal >= raw_start) & (cal <= end)]
    close_w = feat.pivot_table(index="datetime", columns="instrument", values="close", aggfunc="last")
    close_w = close_w.reindex(cal_window)
    close_w = close_w.reindex(columns=instruments)

    W = int(args.lookback_market_days)
    if W != WINDOW:
        raise RuntimeError("lookback drifted from frozen 252")
    close_ok = close_w.notna() & np.isfinite(close_w) & (close_w > 0)
    close_valid = close_w.where(close_ok)
    n_close = close_ok.astype("int16").rolling(W, min_periods=W).sum()
    high_close_w = close_valid.rolling(W, min_periods=W).max()
    window_complete_w = (n_close == W) & high_close_w.notna() & np.isfinite(high_close_w) & (high_close_w > 0)
    high_close_w = high_close_w.where(window_complete_w)
    prox_w = (close_w / high_close_w).where(window_complete_w)
    print("[high-date] earliest argmax of 252-day close window", flush=True)
    high_date_w = _rolling_first_high_dates(close_w, close_ok, W, np, pd)

    start_map = pd.Series(index=cal_window, dtype="datetime64[ns]")
    start_map.iloc[W - 1 :] = cal_window[: len(cal_window) - (W - 1)]

    def _melt(wide, name):
        long = wide.stack(dropna=False).rename(name)
        long.index = long.index.set_names(["datetime", "instrument"])
        return long.reset_index()

    long = _melt(prox_w.loc[start:end], "high252_prox")
    long = long.merge(_melt(high_close_w.loc[start:end], "high_close_252"), on=["datetime", "instrument"], how="left")
    long = long.merge(_melt(high_date_w.loc[start:end], "high_close_date"), on=["datetime", "instrument"], how="left")
    long = long.merge(_melt(close_w.loc[start:end], "close"), on=["datetime", "instrument"], how="left")
    long = long.merge(_melt(n_close.loc[start:end], "n_valid_close"), on=["datetime", "instrument"], how="left")
    long = long.merge(_melt(close_ok.loc[start:end], "close_ok"), on=["datetime", "instrument"], how="left")
    long = long.merge(
        _melt(window_complete_w.loc[start:end], "window_complete"), on=["datetime", "instrument"], how="left"
    )
    long["datetime"] = pd.to_datetime(long["datetime"]).dt.normalize()
    long["instrument"] = long["instrument"].astype(str)
    long["n_valid_close"] = pd.to_numeric(long["n_valid_close"], errors="coerce")
    long["close_ok"] = long["close_ok"].fillna(False).astype(bool)
    long["window_complete"] = long["window_complete"].fillna(False).astype(bool)
    long["window_end"] = long["datetime"]
    long["window_start"] = long["datetime"].map(start_map)
    long["high_close_date"] = pd.to_datetime(long["high_close_date"], errors="coerce")
    long["missing_reason"] = [
        _missing_reason(bool(c), bool(w))
        for c, w in zip(long["close_ok"], long["window_complete"])
    ]

    finite_prox = long["high252_prox"].notna() & np.isfinite(long["high252_prox"])
    bad_lo = int((finite_prox & (long["high252_prox"] <= 0)).sum())
    bad_hi = int((finite_prox & (long["high252_prox"] > 1)).sum())
    if bad_lo or bad_hi:
        raise RuntimeError(
            f"high252_prox out of (0, 1]: n_le0={bad_lo} n_gt1={bad_hi}; refuse to clip"
        )

    out = base.merge(long, on=["datetime", "instrument"], how="left")
    if len(out) != len(base):
        raise RuntimeError(f"left-join changed row count {len(base)} -> {len(out)}")
    out["close_ok"] = out["close_ok"].fillna(False).astype(bool)
    out["window_complete"] = out["window_complete"].fillna(False).astype(bool)
    out["n_valid_close"] = pd.to_numeric(out["n_valid_close"], errors="coerce")
    out["missing_reason"] = out["missing_reason"].fillna("not_in_raw_panel")
    first_ok_t = cal[WARMUP] if len(cal) > WARMUP else cal[-1]
    too_early = pd.to_datetime(out["datetime"]) < pd.Timestamp(first_ok_t)
    out.loc[too_early, "missing_reason"] = out.loc[too_early, "missing_reason"].replace(
        "", "not_enough_history"
    )
    out.loc[too_early & ~out["window_complete"], "missing_reason"] = "not_enough_history"

    ok = (
        out["high252_prox"].notna()
        & np.isfinite(out["high252_prox"])
        & out["window_complete"]
        & (out["high252_prox"] > 0)
        & (out["high252_prox"] <= 1)
    )
    out[args.feature_name] = np.nan
    # Rank high252_prox itself. Never multiply by -1. Never rank(1-x). Never re-rank on A subsample.
    out.loc[ok, args.feature_name] = out.loc[ok, "high252_prox"].groupby(
        out.loc[ok, "datetime"], sort=False
    ).rank(method="average", pct=True)
    rank_n = out.loc[ok].groupby("datetime", sort=False)[args.feature_name].transform("size")
    out["rank_n"] = np.nan
    out.loc[ok, "rank_n"] = rank_n
    out = out.sort_values(["datetime", "instrument"], kind="mergesort").reset_index(drop=True)

    if int(out.duplicated(["datetime", "instrument"]).sum()):
        raise RuntimeError("sidecar keys not unique after join")
    if pd.to_datetime(out["datetime"]).min() < start or pd.to_datetime(out["datetime"]).max() > end:
        raise RuntimeError("sidecar datetime outside frozen window")
    if int((out.loc[ok, args.feature_name].isna()).sum()):
        raise RuntimeError("finite high252_prox produced NaN rank")
    finite_out = out["high252_prox"].notna() & np.isfinite(out["high252_prox"])
    if int((finite_out & ((out["high252_prox"] <= 0) | (out["high252_prox"] > 1))).sum()):
        raise RuntimeError("handler-joined high252_prox out of (0, 1]; refuse to clip")

    rng = np.random.default_rng(20260918)
    finite = out.loc[ok]
    sample_qc = []
    if args.sample_recompute > 0 and len(finite):
        take = min(int(args.sample_recompute), len(finite))
        picks = finite.sample(n=take, random_state=int(rng.integers(0, 2**31 - 1)))
        for _, row in picks.iterrows():
            high_got, date_got, prox_got, n_got, reason = _recompute_one(
                str(row["instrument"]),
                pd.Timestamp(row["datetime"]).normalize(),
                cal,
                args.close_field,
                W,
                pd,
                np,
            )
            stored_prox = float(row["high252_prox"])
            stored_high = float(row["high_close_252"])
            prox_match = (
                prox_got is not None
                and np.isfinite(prox_got)
                and abs(prox_got - stored_prox) <= max(1e-12, 1e-9 * max(1.0, abs(stored_prox)))
            )
            high_match = (
                high_got is not None
                and np.isfinite(high_got)
                and abs(high_got - stored_high) <= max(1e-12, 1e-9 * max(1.0, abs(stored_high)))
            )
            stored_date = (
                pd.Timestamp(row["high_close_date"]).normalize() if pd.notna(row["high_close_date"]) else None
            )
            date_match = date_got is not None and stored_date is not None and date_got == stored_date
            match = bool(prox_match and high_match and date_match)
            sample_qc.append(
                {
                    "instrument": str(row["instrument"]),
                    "datetime": pd.Timestamp(row["datetime"]).date().isoformat(),
                    "stored_prox": stored_prox,
                    "recomputed_prox": prox_got,
                    "stored_high": stored_high,
                    "recomputed_high": high_got,
                    "stored_high_date": stored_date.date().isoformat() if stored_date is not None else None,
                    "recomputed_high_date": date_got.date().isoformat() if date_got is not None else None,
                    "n_valid_close_recomputed": n_got,
                    "match": match,
                    "reason": reason,
                }
            )
        n_bad = sum(1 for x in sample_qc if not x["match"])
        if n_bad:
            raise RuntimeError(f"sample high252 recompute failed: {n_bad}/{len(sample_qc)} {sample_qc[:3]}")
        print(f"[qc] high252_prox recompute ok n={len(sample_qc)}", flush=True)

    rank_qc = []
    days = out.loc[ok, "datetime"].drop_duplicates().tolist()
    if days:
        take_days = min(SAMPLE_RANK_DAYS, len(days))
        day_picks = [days[i] for i in rng.choice(len(days), size=take_days, replace=False)]
        for day in day_picks:
            g = out.loc[out["datetime"] == day]
            valid = (
                g["high252_prox"].notna()
                & np.isfinite(g["high252_prox"])
                & (g["high252_prox"] > 0)
                & (g["high252_prox"] <= 1)
            )
            recomputed = g.loc[valid, "high252_prox"].rank(method="average", pct=True)
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
        print(f"[qc] rank(high252_prox) recompute ok days={len(rank_qc)}", flush=True)

    timing_ok = True
    if len(finite):
        row = finite.iloc[int(rng.integers(0, len(finite)))]
        t = pd.Timestamp(row["datetime"]).normalize()
        pos = int(cal.get_loc(t))
        window_end = cal[pos]
        window_start = cal[pos - WARMUP]
        timing_ok = bool(window_end == t and window_start <= t and cal[pos] <= t)
        if pd.Timestamp(row["window_end"]).normalize() != t:
            timing_ok = False
        stored_start = pd.Timestamp(row["window_start"]).normalize() if pd.notna(row["window_start"]) else None
        if stored_start is not None and stored_start != window_start:
            timing_ok = False
        stored_high_date = (
            pd.Timestamp(row["high_close_date"]).normalize() if pd.notna(row["high_close_date"]) else None
        )
        if stored_high_date is not None and stored_high_date > t:
            timing_ok = False
        if not timing_ok:
            raise RuntimeError("timing check failed: window uses dates after t")

    parquet_path = out_dir / f"{args.feature_name}.parquet"
    cols = [
        "instrument",
        "datetime",
        "window_start",
        "window_end",
        "close",
        "high_close_252",
        "high_close_date",
        "high252_prox",
        args.feature_name,
        "n_valid_close",
        "close_ok",
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
        "lookback_market_days": int(args.lookback_market_days),
        "warmup_preceding_market_days": WARMUP,
        "lookback_available": int(lookback_available),
        "raw_start": str(raw_start.date()),
        "require_complete_window": True,
        "no_window_extension": True,
        "no_close_imputation": True,
        "anchor": "highest-close",
        "ratio": "current-close-over-anchor",
        "multiply_before_rank": 1,
        "no_sign_flip": True,
        "not_maxret": True,
        "not_intraday_high": True,
        "formula": (
            "high_close_252=max(close[d], d=t-251..t) over 252 market days (window includes t); "
            "all 252 closes finite and >0 else missing; "
            "high252_prox=close[t]/high_close_252 (legal 0<prox<=1, never clipped); "
            "HIGH252_PROX_RANK = rank_pct(high252_prox) on handler-day ∩ finite high252_prox; "
            "no multiply by -1; ties in rank use average; high_close_date is earliest max for audit only"
        ),
        "rank": "pandas.Series.rank(method=average, pct=True) on high252_prox itself; never 1-rank(x); never rank(-prox)",
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
        "direction": "higher_HIGH252_PROX_RANK_higher_expected_return",
        "online_untouched": True,
        "handler_feature_names_sample": feat_names[:8],
    }
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
                "lookback_available": int(lookback_available),
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
