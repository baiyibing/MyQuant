# -*- coding: utf-8 -*-
"""T5-DSV1: one-shot DSEM20_ANTI_RANK sidecar on frozen handler index.

dsem20 is RMS of min(r,0) over a fixed 20 market-day window of close-to-close
simple returns (denominator 20, zeros from up-days included). Rank is on
(-dsem20). dsem20=0 (no down days) is a valid value, not missing.
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
FEATURE = "DSEM20_ANTI_RANK"
LOOKBACK = 20
DENOMINATOR = 20
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
    p = argparse.ArgumentParser(description="Export DSEM20_ANTI_RANK sidecar once")
    p.add_argument("--experiment", default=EXPERIMENT)
    p.add_argument("--recorder-id", default=RECORDER_ID)
    p.add_argument("--handler-index-source", default="recorder-handler")
    p.add_argument("--handler-pkl", type=Path, default=DEFAULT_HANDLER_PKL)
    p.add_argument("--provider-uri", default=DEFAULT_PROVIDER)
    p.add_argument("--freeze-provider-snapshot", action="store_true")
    p.add_argument("--close-field", default="$close")
    p.add_argument("--lookback-market-days", type=int, default=LOOKBACK)
    p.add_argument("--return", dest="return_kind", default="close-to-close-simple")
    p.add_argument("--downside-target", default="zero")
    p.add_argument("--root-mean-square", action="store_true")
    p.add_argument("--denominator", type=int, default=DENOMINATOR)
    p.add_argument("--require-complete-window", action="store_true")
    p.add_argument("--no-window-extension", action="store_true")
    p.add_argument("--no-return-imputation", action="store_true")
    p.add_argument("--multiply-before-rank", type=int, default=-1)
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
    if int(args.lookback_market_days) != LOOKBACK:
        raise ValueError(f"lookback-market-days must be {LOOKBACK}")
    if args.return_kind != "close-to-close-simple":
        raise ValueError(f"--return must be close-to-close-simple, got {args.return_kind}")
    if args.downside_target != "zero":
        raise ValueError(f"--downside-target must be zero, got {args.downside_target}")
    if not args.root_mean_square:
        raise ValueError("--root-mean-square is mandatory")
    if int(args.denominator) != DENOMINATOR:
        raise ValueError(f"--denominator must be {DENOMINATOR} (not 19, not downside-day count)")
    if not args.require_complete_window:
        raise ValueError("--require-complete-window is mandatory")
    if not args.no_window_extension:
        raise ValueError("--no-window-extension is mandatory")
    if not args.no_return_imputation:
        raise ValueError("--no-return-imputation is mandatory")
    if int(args.multiply_before_rank) != -1:
        raise ValueError(f"multiply-before-rank must be -1 (dsem20 then * -1), got {args.multiply_before_rank}")
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


def _missing_reason(close_ok: bool, window_complete: bool, n_closes: float) -> str:
    if window_complete and close_ok:
        return ""
    parts = []
    if not close_ok:
        parts.append("close_invalid")
    if not window_complete:
        if n_closes == n_closes and n_closes < 21:
            parts.append("incomplete_window")
        else:
            parts.append("incomplete_window")
    return "|".join(parts) if parts else "unknown"


def _recompute_one(instrument: str, t, calendar, close_field: str, lookback: int, pd, np):
    from qlib.data import D

    pos = calendar.get_loc(t)
    if isinstance(pos, slice) or (hasattr(pos, "__len__") and not isinstance(pos, (int, np.integer))):
        raise KeyError(t)
    pos = int(pos)
    if pos < lookback:
        return None, None, None, "not_enough_history"
    days_close = calendar[pos - lookback : pos + 1]  # t-20 .. t  (21 closes)
    days_ret = calendar[pos - lookback + 1 : pos + 1]  # t-19 .. t
    if len(days_close) != lookback + 1 or len(days_ret) != lookback:
        return None, None, None, "not_enough_history"
    if days_ret[-1] != t:
        return None, None, None, "timing"
    raw = D.features([instrument], [close_field], start_time=days_close[0], end_time=days_close[-1])
    if raw is None or raw.empty:
        return None, None, None, "empty_features"
    frame = raw.reset_index() if isinstance(raw.index, pd.MultiIndex) else raw.copy()
    frame["datetime"] = pd.to_datetime(frame["datetime"]).dt.normalize()
    frame = frame.set_index("datetime").reindex(days_close)
    close = pd.to_numeric(frame[close_field], errors="coerce")
    close_ok = close.notna() & np.isfinite(close) & (close > 0)
    if not bool(close_ok.all()) or int(close_ok.sum()) != lookback + 1:
        return None, None, None, "incomplete_window"
    prev = close.shift(1)
    ret = close / prev - 1.0
    window_ret = ret.loc[days_ret]
    if not np.isfinite(window_ret.to_numpy(dtype=float)).all():
        return None, None, None, "nonfinite_return"
    down = np.minimum(window_ret.to_numpy(dtype=float), 0.0)
    n_neg = int((down < 0).sum())
    dsem = float(np.sqrt(np.mean(down * down)))  # denominator 20, zeros included
    return dsem, n_neg, 20, ""


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
    # Exactly 20 preceding market days of warmup for the 2020 start; do not invent earlier days.
    look_idx = max(0, start_pos - int(args.lookback_market_days))
    raw_start = cal[look_idx]
    print(
        f"[calendar] raw_start={raw_start.date()} start={start.date()} end={end.date()} "
        f"n={len(cal)} lookback_available={start_pos - look_idx}",
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

    prev = close_w.shift(1)
    ret = close_w / prev - 1.0
    close_ok = close_w.notna() & np.isfinite(close_w) & (close_w > 0)
    prev_ok = prev.notna() & np.isfinite(prev) & (prev > 0)
    daily_ok = close_ok & prev_ok
    ret_d = ret.where(daily_ok)
    down = ret_d.clip(upper=0.0)  # min(r, 0); up-days become 0 and still enter the mean square
    down2 = down * down
    W = int(args.lookback_market_days)
    n_ok = daily_ok.astype("int16").rolling(W, min_periods=W).sum()
    n_close_21 = close_ok.astype("int16").rolling(W + 1, min_periods=W + 1).sum()
    n_neg = (ret_d < 0).astype("int16").rolling(W, min_periods=W).sum()
    sum_down2 = down2.rolling(W, min_periods=W).sum()
    dsem20_w = np.sqrt(sum_down2 / float(DENOMINATOR))
    window_complete_w = (n_ok == W) & (n_close_21 == (W + 1)) & dsem20_w.notna()
    # Keep dsem20=0 (no negative days) as valid; never convert 0 to missing.
    dsem20_w = dsem20_w.where(window_complete_w)
    n_neg = n_neg.where(window_complete_w)
    close_lag20_w = close_w.shift(W)

    start_map = pd.Series(index=cal_window, dtype="datetime64[ns]")
    start_map.iloc[W - 1 :] = cal_window[: len(cal_window) - (W - 1)]

    def _melt(wide, name):
        long = wide.stack(dropna=False).rename(name)
        long.index = long.index.set_names(["datetime", "instrument"])
        return long.reset_index()

    long = _melt(dsem20_w.loc[start:end], "dsem20")
    long = long.merge(_melt(close_w.loc[start:end], "close"), on=["datetime", "instrument"], how="left")
    long = long.merge(_melt(close_lag20_w.loc[start:end], "close_lag20"), on=["datetime", "instrument"], how="left")
    long = long.merge(_melt(n_ok.loc[start:end], "n_valid_return_days"), on=["datetime", "instrument"], how="left")
    long = long.merge(_melt(n_close_21.loc[start:end], "n_valid_close_21"), on=["datetime", "instrument"], how="left")
    long = long.merge(_melt(n_neg.loc[start:end], "n_negative_days"), on=["datetime", "instrument"], how="left")
    long = long.merge(_melt(close_ok.loc[start:end], "close_ok"), on=["datetime", "instrument"], how="left")
    long = long.merge(_melt(window_complete_w.loc[start:end], "window_complete"), on=["datetime", "instrument"], how="left")
    long["datetime"] = pd.to_datetime(long["datetime"]).dt.normalize()
    long["instrument"] = long["instrument"].astype(str)
    long["n_valid_return_days"] = pd.to_numeric(long["n_valid_return_days"], errors="coerce")
    long["n_valid_close_21"] = pd.to_numeric(long["n_valid_close_21"], errors="coerce")
    long["n_negative_days"] = pd.to_numeric(long["n_negative_days"], errors="coerce")
    long["close_ok"] = long["close_ok"].fillna(False).astype(bool)
    long["window_complete"] = long["window_complete"].fillna(False).astype(bool)
    long["window_end"] = long["datetime"]
    long["window_start"] = long["datetime"].map(start_map)
    long["missing_reason"] = [
        _missing_reason(bool(c), bool(w), float(n) if pd.notna(n) else float("nan"))
        for c, w, n in zip(long["close_ok"], long["window_complete"], long["n_valid_close_21"])
    ]

    out = base.merge(long, on=["datetime", "instrument"], how="left")
    if len(out) != len(base):
        raise RuntimeError(f"left-join changed row count {len(base)} -> {len(out)}")
    out["close_ok"] = out["close_ok"].fillna(False).astype(bool)
    out["window_complete"] = out["window_complete"].fillna(False).astype(bool)
    out["n_valid_return_days"] = pd.to_numeric(out["n_valid_return_days"], errors="coerce")
    out["n_valid_close_21"] = pd.to_numeric(out["n_valid_close_21"], errors="coerce")
    out["n_negative_days"] = pd.to_numeric(out["n_negative_days"], errors="coerce")
    out["missing_reason"] = out["missing_reason"].fillna("not_in_raw_panel")
    first_ok_t = cal[LOOKBACK] if len(cal) > LOOKBACK else cal[-1]
    out.loc[pd.to_datetime(out["datetime"]) < pd.Timestamp(first_ok_t), "missing_reason"] = (
        out.loc[pd.to_datetime(out["datetime"]) < pd.Timestamp(first_ok_t), "missing_reason"].replace(
            "", "not_enough_history"
        )
    )
    out.loc[
        (pd.to_datetime(out["datetime"]) < pd.Timestamp(first_ok_t)) & ~out["window_complete"],
        "missing_reason",
    ] = "not_enough_history"

    ok = out["dsem20"].notna() & np.isfinite(out["dsem20"]) & out["window_complete"]
    n_zero = int((ok & (out["dsem20"] == 0)).sum())
    if n_zero:
        print(f"[qc] dsem20==0 kept as valid (not missing) n={n_zero}", flush=True)
    out[args.feature_name] = np.nan
    # dsem20 first, then * -1, then rank. Never rank(1-x). Never re-rank on A subsample.
    neg = -out.loc[ok, "dsem20"]
    out.loc[ok, args.feature_name] = neg.groupby(out.loc[ok, "datetime"], sort=False).rank(
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
    if int((out.loc[ok, args.feature_name].isna()).sum()):
        raise RuntimeError("finite dsem20 produced NaN rank")

    rng = np.random.default_rng(20260918)
    finite = out.loc[ok]
    sample_qc = []
    if args.sample_recompute > 0 and len(finite):
        take = min(int(args.sample_recompute), len(finite))
        picks = finite.sample(n=take, random_state=int(rng.integers(0, 2**31 - 1)))
        for _, row in picks.iterrows():
            got, n_neg_got, n_ret_got, reason = _recompute_one(
                str(row["instrument"]),
                pd.Timestamp(row["datetime"]).normalize(),
                cal,
                args.close_field,
                int(args.lookback_market_days),
                pd,
                np,
            )
            stored = float(row["dsem20"])
            match = (
                got is not None
                and np.isfinite(got)
                and abs(got - stored) <= max(1e-12, 1e-9 * max(1.0, abs(stored)))
            )
            sample_qc.append(
                {
                    "instrument": str(row["instrument"]),
                    "datetime": pd.Timestamp(row["datetime"]).date().isoformat(),
                    "stored": stored,
                    "recomputed": got,
                    "n_negative_days_stored": float(row["n_negative_days"]) if pd.notna(row["n_negative_days"]) else None,
                    "n_negative_days_recomputed": n_neg_got,
                    "n_valid_return_days_recomputed": n_ret_got,
                    "match": bool(match),
                    "reason": reason,
                }
            )
        n_bad = sum(1 for x in sample_qc if not x["match"])
        if n_bad:
            raise RuntimeError(f"sample dsem20 recompute failed: {n_bad}/{len(sample_qc)} {sample_qc[:3]}")
        print(f"[qc] dsem20 recompute ok n={len(sample_qc)}", flush=True)

    rank_qc = []
    days = out.loc[ok, "datetime"].drop_duplicates().tolist()
    if days:
        take_days = min(SAMPLE_RANK_DAYS, len(days))
        day_picks = [days[i] for i in rng.choice(len(days), size=take_days, replace=False)]
        for day in day_picks:
            g = out.loc[out["datetime"] == day]
            valid = g["dsem20"].notna() & np.isfinite(g["dsem20"])
            recomputed = (-g.loc[valid, "dsem20"]).rank(method="average", pct=True)
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
        print(f"[qc] rank(-dsem20) recompute ok days={len(rank_qc)}", flush=True)

    timing_ok = True
    if len(finite):
        row = finite.iloc[int(rng.integers(0, len(finite)))]
        t = pd.Timestamp(row["datetime"]).normalize()
        pos = int(cal.get_loc(t))
        window_end = cal[pos]
        window_start = cal[pos - args.lookback_market_days + 1]
        timing_ok = bool(window_end == t and window_start <= t and cal[pos] <= t)
        if pd.Timestamp(row["window_end"]).normalize() != t:
            timing_ok = False
        stored_start = pd.Timestamp(row["window_start"]).normalize() if pd.notna(row["window_start"]) else None
        if stored_start is not None and stored_start != window_start:
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
        "close_lag20",
        "dsem20",
        args.feature_name,
        "n_valid_return_days",
        "n_valid_close_21",
        "n_negative_days",
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
        "denominator": DENOMINATOR,
        "require_complete_window": True,
        "no_window_extension": True,
        "no_return_imputation": True,
        "daily_return": "close-to-close-simple",
        "downside_target": "zero",
        "root_mean_square": True,
        "multiply_before_rank": -1,
        "zero_dsem_is_valid": True,
        "n_zero_dsem20": n_zero,
        "negative_day_count_is_qc_only": True,
        "formula": (
            "r=close_d/close_{d-1}-1 for d=t-19..t (20 market days, 21 closes all finite >0); "
            "down=min(r,0); dsem20=sqrt(mean(down^2)) with denominator 20 "
            "(up-days contribute 0; all-up window → dsem20=0 valid); "
            "DSEM20_ANTI_RANK = rank_pct(-dsem20) on handler-day ∩ finite dsem20"
        ),
        "rank": "pandas.Series.rank(method=average, pct=True) on -dsem20; dsem20 first then * -1; never 1-rank(x)",
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
        "direction": "higher_DSEM20_ANTI_RANK_higher_expected_return",
        "no_sign_flip": True,
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
                "n_zero_dsem20": n_zero,
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
