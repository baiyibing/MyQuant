# -*- coding: utf-8 -*-
"""T5-DSTR1: one-shot DOWNSTREAK5_RANK sidecar on frozen handler index.

downstreak5 = length of the consecutive close-to-close negative-return run
ending at t, capped at 5. r = close/prev - 1; r==0 or r>0 breaks the run.
Requires t-5..t (6 market-day closes) all finite and >0; else missing.
Rank is on downstreak5 itself (no * -1). Not CNTN5 / ROC5 / SUMN5.
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
FEATURE = "DOWNSTREAK5_RANK"
MAX_DAYS = 5
N_CLOSE = MAX_DAYS + 1  # t-5..t
WARMUP = MAX_DAYS  # exactly 5 preceding market days for a 2020 start
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


def prefix_streak_from_bitmap(bits: str) -> int:
    """Walk from t (left) until the first non-negative bit. Cap 5."""
    n = 0
    for ch in str(bits):
        if ch == "1":
            n += 1
            if n >= MAX_DAYS:
                break
        else:
            break
    return n


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Export DOWNSTREAK5_RANK sidecar once")
    p.add_argument("--experiment", default=EXPERIMENT)
    p.add_argument("--recorder-id", default=RECORDER_ID)
    p.add_argument("--handler-index-source", default="recorder-handler")
    p.add_argument("--handler-pkl", type=Path, default=DEFAULT_HANDLER_PKL)
    p.add_argument("--provider-uri", default=DEFAULT_PROVIDER)
    p.add_argument("--freeze-provider-snapshot", action="store_true")
    p.add_argument("--close-field", default="$close")
    p.add_argument("--streak-side", default="down")
    p.add_argument("--max-market-days", type=int, default=MAX_DAYS)
    p.add_argument("--exclude-zero-return", action="store_true")
    p.add_argument("--require-complete-window", action="store_true")
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
    if args.streak_side != "down":
        raise ValueError(f"--streak-side must be down, got {args.streak_side}")
    if int(args.max_market_days) != MAX_DAYS:
        raise ValueError(f"--max-market-days must be {MAX_DAYS}; 3/10/20 caps are forbidden")
    if not args.exclude_zero_return:
        raise ValueError("--exclude-zero-return is mandatory (r==0 breaks streak)")
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
    banned = {FEATURE, "downstreak5", "upstreak5"}
    hit = [x for x in names_flat if x in banned]
    if hit:
        raise RuntimeError(f"{hit} already present in frozen handler; refuse to overwrite")
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


def _recompute_one(instrument: str, t, calendar, close_field: str, pd, np):
    from qlib.data import D

    pos = calendar.get_loc(t)
    if isinstance(pos, slice) or (hasattr(pos, "__len__") and not isinstance(pos, (int, np.integer))):
        raise KeyError(t)
    pos = int(pos)
    if pos < WARMUP:
        return None, None, None, "not_enough_history"
    days = calendar[pos - WARMUP : pos + 1]
    if len(days) != N_CLOSE:
        return None, None, None, "not_enough_history"
    if days[-1] != t:
        return None, None, None, "timing"
    raw = D.features([instrument], [close_field], start_time=days[0], end_time=days[-1])
    if raw is None or raw.empty:
        return None, None, None, "empty_features"
    frame = raw.reset_index() if isinstance(raw.index, pd.MultiIndex) else raw.copy()
    frame["datetime"] = pd.to_datetime(frame["datetime"]).dt.normalize()
    frame = frame.set_index("datetime").reindex(days)
    close = pd.to_numeric(frame[close_field], errors="coerce")
    close_ok = close.notna() & np.isfinite(close) & (close > 0)
    if not bool(close_ok.all()) or int(close_ok.sum()) != N_CLOSE:
        return None, None, None, "incomplete_window"
    vals = close.to_numpy(dtype=float)
    # r[t], r[t-1], ... r[t-4]  from current close backward.
    rets = []
    for k in range(MAX_DAYS):
        cur = vals[-(1 + k)]
        prev = vals[-(2 + k)]
        rets.append(cur / prev - 1.0)
    bits = "".join("1" if r < 0 else "0" for r in rets)
    streak = prefix_streak_from_bitmap(bits)
    return streak, bits, [float(x) for x in rets], ""


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
    # Exactly 5 preceding market days of warmup for the 2020 start; never read more.
    if start_pos >= WARMUP:
        look_idx = start_pos - WARMUP
        lookback_available = WARMUP
    else:
        look_idx = 0
        lookback_available = start_pos
    raw_start = cal[look_idx]
    if lookback_available > WARMUP:
        raise RuntimeError("warmup exceeded 5 preceding market days")
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

    close_ok = close_w.notna() & np.isfinite(close_w) & (close_w > 0)
    n_close = close_ok.astype("int16").rolling(N_CLOSE, min_periods=N_CLOSE).sum()
    window_complete_w = n_close == N_CLOSE
    # r[t] = close[t]/close[t-1]-1. Zero returns are NOT negative: they break the run.
    prev_ok = close_ok.shift(1)
    r_w = (close_w / close_w.shift(1) - 1.0).where(close_ok & prev_ok)
    neg = r_w < 0
    c1 = neg
    c2 = neg & neg.shift(1)
    c3 = c2 & neg.shift(2)
    c4 = c3 & neg.shift(3)
    c5 = c4 & neg.shift(4)
    streak_w = (
        c1.astype("int8") + c2.astype("int8") + c3.astype("int8") + c4.astype("int8") + c5.astype("int8")
    )
    streak_w = streak_w.where(window_complete_w)

    date_s = pd.Series(cal_window, index=cal_window)
    lag_close = {k: close_w.shift(k) for k in range(N_CLOSE)}
    lag_ok = {k: close_ok.shift(k) for k in range(N_CLOSE)}
    lag_ret = {k: r_w.shift(k) for k in range(MAX_DAYS)}

    start_map = pd.Series(index=cal_window, dtype="datetime64[ns]")
    start_map.iloc[N_CLOSE - 1 :] = cal_window[: len(cal_window) - (N_CLOSE - 1)]

    def _melt(wide, name):
        long = wide.stack(dropna=False).rename(name)
        long.index = long.index.set_names(["datetime", "instrument"])
        return long.reset_index()

    long = _melt(streak_w.loc[start:end], "downstreak5")
    long = long.merge(_melt(close_w.loc[start:end], "close_t"), on=["datetime", "instrument"], how="left")
    long = long.merge(_melt(close_ok.loc[start:end], "close_ok_t"), on=["datetime", "instrument"], how="left")
    long = long.merge(_melt(n_close.loc[start:end], "n_valid_close"), on=["datetime", "instrument"], how="left")
    long = long.merge(
        _melt(window_complete_w.loc[start:end], "window_complete"), on=["datetime", "instrument"], how="left"
    )
    for k, col in enumerate(["ret_t", "ret_tm1", "ret_tm2", "ret_tm3", "ret_tm4"]):
        long = long.merge(_melt(lag_ret[k].loc[start:end], col), on=["datetime", "instrument"], how="left")
    for k, col in enumerate(["close_tm1", "close_tm2", "close_tm3", "close_tm4", "close_tm5"], start=1):
        long = long.merge(_melt(lag_close[k].loc[start:end], col), on=["datetime", "instrument"], how="left")
    for k, col in enumerate(["ok_tm1", "ok_tm2", "ok_tm3", "ok_tm4", "ok_tm5"], start=1):
        long = long.merge(_melt(lag_ok[k].loc[start:end], col), on=["datetime", "instrument"], how="left")

    long["datetime"] = pd.to_datetime(long["datetime"]).dt.normalize()
    long["instrument"] = long["instrument"].astype(str)
    long["n_valid_close"] = pd.to_numeric(long["n_valid_close"], errors="coerce")
    long["close_ok_t"] = long["close_ok_t"].fillna(False).astype(bool)
    long["window_complete"] = long["window_complete"].fillna(False).astype(bool)
    for col in ["ok_tm1", "ok_tm2", "ok_tm3", "ok_tm4", "ok_tm5"]:
        long[col] = long[col].fillna(False).astype(bool)
    long["window_end"] = long["datetime"]
    long["window_start"] = long["datetime"].map(start_map)
    long["date_t"] = long["datetime"]
    # Market-calendar dates of the 6 closes depend only on t, not on instrument.
    long["date_tm1"] = long["datetime"].map(date_s.shift(1))
    long["date_tm2"] = long["datetime"].map(date_s.shift(2))
    long["date_tm3"] = long["datetime"].map(date_s.shift(3))
    long["date_tm4"] = long["datetime"].map(date_s.shift(4))
    long["date_tm5"] = long["datetime"].map(date_s.shift(5))
    six_ok = (
        long["close_ok_t"]
        & long["ok_tm1"]
        & long["ok_tm2"]
        & long["ok_tm3"]
        & long["ok_tm4"]
        & long["ok_tm5"]
    )
    long["close_ok"] = six_ok
    long["missing_reason"] = [
        _missing_reason(bool(c), bool(w)) for c, w in zip(long["close_ok"], long["window_complete"])
    ]

    ret_cols = ["ret_t", "ret_tm1", "ret_tm2", "ret_tm3", "ret_tm4"]
    complete = long["window_complete"] & six_ok
    bit_s = None
    for col in ret_cols:
        piece = pd.Series(
            np.where(long.loc[complete, col].to_numpy() < 0, "1", "0"),
            index=long.index[complete],
            dtype="object",
        )
        bit_s = piece if bit_s is None else bit_s + piece
    long["neg_bitmap"] = ""
    if bit_s is not None:
        long.loc[complete, "neg_bitmap"] = bit_s

    finite_streak = complete & long["downstreak5"].notna() & np.isfinite(long["downstreak5"])
    vals = long.loc[finite_streak, "downstreak5"].to_numpy(dtype=float)
    if len(vals):
        if np.any(np.mod(vals, 1.0) != 0.0):
            raise RuntimeError("downstreak5 is not integer-valued")
        if int((vals < 0).sum()) or int((vals > MAX_DAYS).sum()):
            raise RuntimeError("downstreak5 outside {0,1,2,3,4,5}")

    out = base.merge(long, on=["datetime", "instrument"], how="left")
    if len(out) != len(base):
        raise RuntimeError(f"left-join changed row count {len(base)} -> {len(out)}")
    out["close_ok"] = out["close_ok"].fillna(False).astype(bool)
    out["window_complete"] = out["window_complete"].fillna(False).astype(bool)
    out["n_valid_close"] = pd.to_numeric(out["n_valid_close"], errors="coerce")
    out["missing_reason"] = out["missing_reason"].fillna("not_in_raw_panel")
    out["neg_bitmap"] = out["neg_bitmap"].fillna("").astype(str)
    first_ok_t = cal[WARMUP] if len(cal) > WARMUP else cal[-1]
    too_early = pd.to_datetime(out["datetime"]) < pd.Timestamp(first_ok_t)
    out.loc[too_early, "missing_reason"] = out.loc[too_early, "missing_reason"].replace(
        "", "not_enough_history"
    )
    out.loc[too_early & ~out["window_complete"], "missing_reason"] = "not_enough_history"

    ok = (
        out["downstreak5"].notna()
        & np.isfinite(out["downstreak5"])
        & out["window_complete"]
        & out["close_ok"]
        & (out["downstreak5"] >= 0)
        & (out["downstreak5"] <= MAX_DAYS)
    )
    # Bitmap prefix must reproduce the consecutive run. Mismatch that is not
    # truncation at the first non-negative bit → DSTR_DATA_INVALID.
    if int(ok.sum()):
        stored = out.loc[ok, "downstreak5"].to_numpy(dtype=int)
        bm = out.loc[ok, "neg_bitmap"].astype(str)
        pref = np.zeros(int(ok.sum()), dtype=int)
        still = np.ones(int(ok.sum()), dtype=bool)
        for i in range(MAX_DAYS):
            ch = bm.str[i].to_numpy()
            is_neg = still & (ch == "1")
            pref = pref + is_neg.astype(int)
            still = still & is_neg
        if int((pref != stored).sum()):
            n_bad = int((pref != stored).sum())
            raise RuntimeError(
                f"DSTR_DATA_INVALID: neg_bitmap prefix != downstreak5 on {n_bad} rows"
            )
        n_down = (
            (bm.str[0] == "1").astype(int)
            + (bm.str[1] == "1").astype(int)
            + (bm.str[2] == "1").astype(int)
            + (bm.str[3] == "1").astype(int)
            + (bm.str[4] == "1").astype(int)
        ).to_numpy()
        interleaved = (bm.str.contains("01", regex=False)).to_numpy()
        if int(interleaved.sum()) and int((interleaved & (stored == n_down)).sum()):
            raise RuntimeError(
                "DSTR_DATA_INVALID: interleaved yin/yang rows have streak==down-day-count; "
                "that is CNTN5, not a consecutive run"
            )
        starts_zero = (bm.str[0] == "0").to_numpy()
        if int((starts_zero & (stored != 0)).sum()):
            raise RuntimeError("DSTR_DATA_INVALID: empty product treated as 1 (streak>=1 when r[t]>=0)")

    out[args.feature_name] = np.nan
    # Rank downstreak5 itself. Never multiply by -1. Never re-rank on A subsample.
    out.loc[ok, args.feature_name] = out.loc[ok, "downstreak5"].groupby(
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
        raise RuntimeError("finite downstreak5 produced NaN rank")
    finite_rank = out[args.feature_name].notna() & np.isfinite(out[args.feature_name])
    if int((finite_rank & ((out[args.feature_name] <= 0) | (out[args.feature_name] > 1))).sum()):
        raise RuntimeError("DOWNSTREAK5_RANK out of (0, 1]; refuse to clip")

    rng = np.random.default_rng(20260918)
    finite = out.loc[ok]
    sample_qc = []
    if args.sample_recompute > 0 and len(finite):
        take = min(int(args.sample_recompute), len(finite))
        picks = finite.sample(n=take, random_state=int(rng.integers(0, 2**31 - 1)))
        for _, row in picks.iterrows():
            streak_got, bits_got, rets_got, reason = _recompute_one(
                str(row["instrument"]),
                pd.Timestamp(row["datetime"]).normalize(),
                cal,
                args.close_field,
                pd,
                np,
            )
            stored_st = int(row["downstreak5"])
            stored_bits = str(row["neg_bitmap"])
            match = (
                streak_got is not None
                and int(streak_got) == stored_st
                and bits_got == stored_bits
                and prefix_streak_from_bitmap(stored_bits) == stored_st
            )
            sample_qc.append(
                {
                    "instrument": str(row["instrument"]),
                    "datetime": pd.Timestamp(row["datetime"]).date().isoformat(),
                    "stored_downstreak5": stored_st,
                    "recomputed_downstreak5": streak_got,
                    "stored_neg_bitmap": stored_bits,
                    "recomputed_neg_bitmap": bits_got,
                    "recomputed_rets": rets_got,
                    "match": match,
                    "reason": reason,
                }
            )
        n_bad = sum(1 for x in sample_qc if not x["match"])
        if n_bad:
            raise RuntimeError(f"sample downstreak recompute failed: {n_bad}/{len(sample_qc)} {sample_qc[:3]}")
        print(f"[qc] downstreak5 recompute ok n={len(sample_qc)}", flush=True)

    rank_qc = []
    days = out.loc[ok, "datetime"].drop_duplicates().tolist()
    if days:
        take_days = min(SAMPLE_RANK_DAYS, len(days))
        day_picks = [days[i] for i in rng.choice(len(days), size=take_days, replace=False)]
        for day in day_picks:
            g = out.loc[out["datetime"] == day]
            valid = (
                g["downstreak5"].notna()
                & np.isfinite(g["downstreak5"])
                & (g["downstreak5"] >= 0)
                & (g["downstreak5"] <= MAX_DAYS)
                & g["window_complete"]
                & g["close_ok"]
            )
            recomputed = g.loc[valid, "downstreak5"].rank(method="average", pct=True)
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
        print(f"[qc] rank(downstreak5) recompute ok days={len(rank_qc)}", flush=True)

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
        for col in ["date_tm1", "date_tm2", "date_tm3", "date_tm4", "date_tm5"]:
            if pd.notna(row.get(col)) and pd.Timestamp(row[col]).normalize() > t:
                timing_ok = False
        if not timing_ok:
            raise RuntimeError("timing check failed: window uses dates after t")

    parquet_path = out_dir / f"{args.feature_name}.parquet"
    cols = [
        "instrument",
        "datetime",
        "window_start",
        "window_end",
        "date_t",
        "date_tm1",
        "date_tm2",
        "date_tm3",
        "date_tm4",
        "date_tm5",
        "close_t",
        "close_tm1",
        "close_tm2",
        "close_tm3",
        "close_tm4",
        "close_tm5",
        "close_ok_t",
        "ok_tm1",
        "ok_tm2",
        "ok_tm3",
        "ok_tm4",
        "ok_tm5",
        "close_ok",
        "ret_t",
        "ret_tm1",
        "ret_tm2",
        "ret_tm3",
        "ret_tm4",
        "neg_bitmap",
        "downstreak5",
        args.feature_name,
        "n_valid_close",
        "window_complete",
        "missing_reason",
        "rank_n",
    ]
    out[cols].to_parquet(parquet_path, index=False)
    sidecar_sha = _sha256(parquet_path)
    key_digest = _key_digest(out)

    n_finite = int(ok.sum())
    streak_counts = (
        out.loc[ok, "downstreak5"].astype(int).value_counts().sort_index().to_dict()
        if n_finite
        else {}
    )
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
        "streak_side": "down",
        "max_market_days": MAX_DAYS,
        "n_close_required": N_CLOSE,
        "warmup_preceding_market_days": WARMUP,
        "lookback_available": int(lookback_available),
        "raw_start": str(raw_start.date()),
        "require_complete_window": True,
        "no_window_extension": True,
        "no_close_imputation": True,
        "exclude_zero_return": True,
        "multiply_before_rank": 1,
        "no_sign_flip": True,
        "not_cntn5": True,
        "not_roc5": True,
        "not_sumn5": True,
        "formula": (
            "r=close[d]/close[prev_market_day(d)]-1; "
            "downstreak5=sum(k=1..5, product(j=0..k-1, 1[r[t-j]<0])); "
            "empty product is not 1; r==0 breaks the run; "
            "requires t-5..t (6 closes) all finite and >0 else missing; "
            "DOWNSTREAK5_RANK = rank_pct(downstreak5) on handler-day ∩ finite downstreak5; "
            "no multiply by -1; ties use average; neg_bitmap is 5 bits from t backward"
        ),
        "rank": "pandas.Series.rank(method=average, pct=True) on downstreak5 itself; never 1-rank(x); never rank(-x)",
        "feature_name": args.feature_name,
        "sidecar_path": str(parquet_path),
        "sidecar_sha256": sidecar_sha,
        "key_digest": key_digest,
        "n_rows": int(len(out)),
        "n_instruments": int(out["instrument"].nunique()),
        "n_days": int(out["datetime"].nunique()),
        "n_finite_rank": n_finite,
        "downstreak5_value_counts": {str(k): int(v) for k, v in streak_counts.items()},
        "missing_reason_counts": out["missing_reason"].fillna("").value_counts().to_dict(),
        "sample_recompute": sample_qc,
        "rank_recompute": rank_qc,
        "timing_ok": timing_ok,
        "direction": "higher_DOWNSTREAK5_RANK_higher_expected_reversal_return",
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
