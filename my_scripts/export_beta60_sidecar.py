# -*- coding: utf-8 -*-
"""T5-BETA1: one-shot BETA60_ANTI_RANK sidecar on frozen handler index.

beta60 is intercept OLS of stock close-to-close simple returns on SH000300
returns over a fixed 60 market-day window; rank is on (-beta60) after OLS.
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
FEATURE = "BETA60_ANTI_RANK"
LOOKBACK = 60
MIN_VALID_PAIRS = 40
BENCHMARK = "SH000300"
FORBIDDEN_BENCHMARKS = {"000300.SH", "000300.SH".lower(), "510300", "SH510300", "CSI300"}
SAMPLE_RECOMPUTE = 16
SAMPLE_RANK_DAYS = 3
DENOM_EPS = 1e-18


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


def benchmark_series_digest(dates, closes) -> str:
    """Fingerprint of frozen SH000300 date+close sequence. No interpolation."""
    import numpy as np
    import pandas as pd

    h = hashlib.sha256()
    h.update(b"benchmark=SH000300\n")
    for d, c in zip(dates, closes):
        h.update(pd.Timestamp(d).strftime("%Y-%m-%d").encode("utf-8"))
        h.update(b"|")
        cv = np.float64(c) if c is not None and np.isfinite(c) else None
        if cv is None:
            h.update(b"nan")
        else:
            h.update(np.float64(cv).tobytes())
        h.update(b"\n")
    return h.hexdigest()


def _rolling_sum(a, w: int):
    import numpy as np

    cs = np.cumsum(a, axis=0)
    out = np.empty(cs.shape, dtype=np.float64)
    out[: w - 1] = np.nan
    out[w - 1] = cs[w - 1]
    out[w:] = cs[w:] - cs[:-w]
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Export BETA60_ANTI_RANK sidecar once")
    p.add_argument("--experiment", default=EXPERIMENT)
    p.add_argument("--recorder-id", default=RECORDER_ID)
    p.add_argument("--handler-index-source", default="recorder-handler")
    p.add_argument("--handler-pkl", type=Path, default=DEFAULT_HANDLER_PKL)
    p.add_argument("--provider-uri", default=DEFAULT_PROVIDER)
    p.add_argument("--freeze-provider-snapshot", action="store_true")
    p.add_argument("--close-field", default="$close")
    p.add_argument("--benchmark", default=BENCHMARK)
    p.add_argument("--lookback-market-days", type=int, default=LOOKBACK)
    p.add_argument("--return", dest="return_kind", default="close-to-close")
    p.add_argument("--ols-with-intercept", action="store_true")
    p.add_argument("--min-valid-pairs", type=int, default=MIN_VALID_PAIRS)
    p.add_argument("--no-window-extension", action="store_true")
    p.add_argument("--no-return-imputation", action="store_true")
    p.add_argument("--multiply-before-rank", type=int, default=-1)
    p.add_argument("--rank-method", default="average")
    p.add_argument("--rank-pct", default="pandas-pct-true")
    p.add_argument("--feature-name", default=FEATURE)
    p.add_argument("--start", default="2020-01-02")
    p.add_argument("--end", default="2026-09-14")
    p.add_argument("--emit-source-qc", action="store_true")
    p.add_argument("--emit-benchmark-digest", action="store_true")
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
    if str(args.benchmark) != BENCHMARK:
        raise ValueError(f"benchmark must be {BENCHMARK}, got {args.benchmark}")
    if str(args.benchmark) in FORBIDDEN_BENCHMARKS or str(args.benchmark).upper() in {"000300.SH", "510300"}:
        raise ValueError(f"forbidden benchmark {args.benchmark}")
    if int(args.lookback_market_days) != LOOKBACK:
        raise ValueError(f"lookback-market-days must be {LOOKBACK}")
    if args.return_kind != "close-to-close":
        raise ValueError(f"--return must be close-to-close, got {args.return_kind}")
    if not args.ols_with_intercept:
        raise ValueError("--ols-with-intercept is mandatory (no intercept-free / rolling-corr beta)")
    if int(args.min_valid_pairs) != MIN_VALID_PAIRS:
        raise ValueError(f"min-valid-pairs must be {MIN_VALID_PAIRS}")
    if not args.no_window_extension:
        raise ValueError("--no-window-extension is mandatory")
    if not args.no_return_imputation:
        raise ValueError("--no-return-imputation is mandatory")
    if int(args.multiply_before_rank) != -1:
        raise ValueError(f"multiply-before-rank must be -1 (beta then * -1), got {args.multiply_before_rank}")
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
    if not args.emit_benchmark_digest:
        raise ValueError("--emit-benchmark-digest is mandatory")
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
    feat_cols = [c for c in infer.columns if (isinstance(c, tuple) and c[0] == "feature") or c == "feature"]
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


def _ols_beta_one(x, y, np):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = int(len(x))
    if n < MIN_VALID_PAIRS:
        return None, "insufficient_valid_pairs"
    sx = float(x.sum())
    sy = float(y.sum())
    sxy = float(np.dot(x, y))
    sx2 = float(np.dot(x, x))
    denom = n * sx2 - sx * sx
    scale = max(1.0, abs(n * sx2))
    if abs(denom) <= DENOM_EPS * scale:
        return None, "rank_deficient"
    beta = (n * sxy - sx * sy) / denom
    if not np.isfinite(beta):
        return None, "beta_nonfinite"
    return float(beta), ""


def _recompute_one(instrument: str, t, calendar, close_field: str, lookback: int, pd, np):
    from qlib.data import D

    pos = calendar.get_loc(t)
    if isinstance(pos, slice) or (hasattr(pos, "__len__") and not isinstance(pos, (int, np.integer))):
        raise KeyError(t)
    pos = int(pos)
    if pos < lookback:
        return None, None, "not_enough_history"
    days_close = calendar[pos - lookback : pos + 1]
    days_ret = calendar[pos - lookback + 1 : pos + 1]
    if len(days_close) != lookback + 1 or len(days_ret) != lookback:
        return None, None, "not_enough_history"
    if days_ret[-1] != t:
        return None, None, "timing"

    def _load(code: str):
        raw = D.features([code], [close_field], start_time=days_close[0], end_time=days_close[-1])
        if raw is None or raw.empty:
            return None
        frame = raw.reset_index() if isinstance(raw.index, pd.MultiIndex) else raw.copy()
        frame["datetime"] = pd.to_datetime(frame["datetime"]).dt.normalize()
        frame = frame.set_index("datetime").reindex(days_close)
        return pd.to_numeric(frame[close_field], errors="coerce")

    stock_c = _load(instrument)
    bench_c = _load(BENCHMARK)
    if stock_c is None:
        return None, None, "empty_features"
    if bench_c is None:
        return None, None, "benchmark_empty"
    stock_prev = stock_c.shift(1)
    bench_prev = bench_c.shift(1)
    stock_ret = stock_c / stock_prev - 1.0
    bench_ret = bench_c / bench_prev - 1.0
    stock_ok = stock_c.notna() & np.isfinite(stock_c) & (stock_c > 0)
    stock_prev_ok = stock_prev.notna() & np.isfinite(stock_prev) & (stock_prev > 0)
    bench_ok = bench_c.notna() & np.isfinite(bench_c) & (bench_c > 0)
    bench_prev_ok = bench_prev.notna() & np.isfinite(bench_prev) & (bench_prev > 0)
    s_ret = stock_ret.loc[days_ret]
    b_ret = bench_ret.loc[days_ret]
    s_pair = (stock_ok & stock_prev_ok).loc[days_ret]
    b_pair = (bench_ok & bench_prev_ok).loc[days_ret]
    if not bool(b_pair.all()) or not np.isfinite(b_ret.to_numpy(dtype=float)).all():
        return None, None, "benchmark_incomplete"
    bvar = float(np.var(b_ret.to_numpy(dtype=float), ddof=1))
    if not np.isfinite(bvar) or bvar <= 0:
        return None, None, "benchmark_zero_variance"
    valid = s_pair & b_pair & np.isfinite(s_ret) & np.isfinite(b_ret)
    n = int(valid.sum())
    if n < MIN_VALID_PAIRS:
        return None, n, "insufficient_valid_pairs"
    beta, reason = _ols_beta_one(b_ret.loc[valid].to_numpy(dtype=float), s_ret.loc[valid].to_numpy(dtype=float), np)
    if reason:
        return None, n, reason
    return float(beta), n, ""


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
    if "BETA60" in feat_names:
        print("[freeze] handler has Alpha158 BETA60 (price-vs-time); will not read or anti-rank it", flush=True)
    if base.empty:
        raise RuntimeError("handler index empty in sidecar window")
    if int(base.duplicated(["datetime", "instrument"]).sum()):
        raise RuntimeError("handler keys not unique")
    if BENCHMARK in set(base["instrument"].astype(str)):
        raise RuntimeError("SH000300 is inside handler universe; refuse to rank the benchmark as a stock")
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
    look_idx = max(0, start_pos - int(args.lookback_market_days))
    raw_start = cal[look_idx]
    print(
        f"[calendar] raw_start={raw_start.date()} start={start.date()} end={end.date()} "
        f"n={len(cal)} lookback_available={start_pos - look_idx}",
        flush=True,
    )

    instruments = sorted(base["instrument"].unique().tolist())
    instruments = [c for c in instruments if c != BENCHMARK]
    print(f"[features] D.features n={len(instruments)} field={args.close_field}", flush=True)
    raw = D.features(instruments, [args.close_field], start_time=raw_start, end_time=end)
    if raw is None or raw.empty:
        raise RuntimeError("close features empty")
    feat = raw.reset_index() if isinstance(raw.index, pd.MultiIndex) else raw.copy()
    if args.close_field not in feat.columns:
        raise ValueError(f"unexpected feature columns: {list(feat.columns)}")
    feat["datetime"] = pd.to_datetime(feat["datetime"]).dt.normalize()
    feat["instrument"] = feat["instrument"].astype(str)
    feat["close"] = pd.to_numeric(feat[args.close_field], errors="coerce")

    print(f"[benchmark] fetch {BENCHMARK} $close (no substitute)", flush=True)
    raw_b = D.features([BENCHMARK], [args.close_field], start_time=raw_start, end_time=end)
    if raw_b is None or raw_b.empty:
        raise RuntimeError("BETA_DATA_INVALID: SH000300 close empty; refuse substitute benchmark")
    bench = raw_b.reset_index() if isinstance(raw_b.index, pd.MultiIndex) else raw_b.copy()
    if args.close_field not in bench.columns:
        raise ValueError(f"unexpected benchmark columns: {list(bench.columns)}")
    bench["datetime"] = pd.to_datetime(bench["datetime"]).dt.normalize()
    if "instrument" in bench.columns:
        codes = sorted(set(bench["instrument"].astype(str)))
        if codes != [BENCHMARK]:
            raise RuntimeError(f"BETA_DATA_INVALID: benchmark codes {codes} != [{BENCHMARK}]")
    bench["close"] = pd.to_numeric(bench[args.close_field], errors="coerce")
    if int(bench.duplicated("datetime").sum()):
        raise RuntimeError("BETA_DATA_INVALID: SH000300 dates not unique")

    cal_window = cal[(cal >= raw_start) & (cal <= end)]
    close_w = feat.pivot_table(index="datetime", columns="instrument", values="close", aggfunc="last")
    close_w = close_w.reindex(cal_window)
    close_w = close_w.reindex(columns=instruments)

    bench_c = bench.set_index("datetime")["close"].reindex(cal_window)
    bench_arr = bench_c.to_numpy(dtype=float)
    n_bench_miss = int((~np.isfinite(bench_arr) | (bench_arr <= 0)).sum())
    print(f"[benchmark] days={len(bench_c)} missing_or_nonpositive={n_bench_miss}", flush=True)

    prev_s = close_w.shift(1)
    ret_s = close_w / prev_s - 1.0
    close_ok = close_w.notna() & np.isfinite(close_w) & (close_w > 0)
    prev_ok = prev_s.notna() & np.isfinite(prev_s) & (prev_s > 0)
    stock_ret_ok = close_ok & prev_ok
    ret_s = ret_s.where(stock_ret_ok)

    prev_b = bench_c.shift(1)
    ret_b = bench_c / prev_b - 1.0
    bench_ok = bench_c.notna() & np.isfinite(bench_c) & (bench_c > 0)
    bench_prev_ok = prev_b.notna() & np.isfinite(prev_b) & (prev_b > 0)
    bench_ret_ok = bench_ok & bench_prev_ok
    ret_b = ret_b.where(bench_ret_ok)

    digest = benchmark_series_digest(cal_window, bench_c.to_numpy(dtype=float))
    print(f"[benchmark] digest={digest}", flush=True)

    W = int(args.lookback_market_days)
    x = ret_b.to_numpy(dtype=float)
    Y = ret_s.to_numpy(dtype=float)
    bench_ok_a = bench_ret_ok.to_numpy()
    stock_ok_a = stock_ret_ok.to_numpy()
    pair = stock_ok_a & bench_ok_a[:, None] & np.isfinite(Y) & np.isfinite(x)[:, None]

    x_safe = np.where(np.isfinite(x) & bench_ok_a, x, 0.0)
    Y_safe = np.where(pair, Y, 0.0)
    M = pair.astype(np.float64)
    X2d = x_safe[:, None] * M
    XY = X2d * Y_safe
    X2 = X2d * x_safe[:, None]

    n_w = _rolling_sum(M, W)
    sx = _rolling_sum(X2d, W)
    sy = _rolling_sum(Y_safe, W)
    sxy = _rolling_sum(XY, W)
    sx2 = _rolling_sum(X2, W)
    denom = n_w * sx2 - sx * sx
    numer = n_w * sxy - sx * sy
    scale = np.maximum(1.0, np.abs(n_w * sx2))
    rank_ok = np.isfinite(denom) & (np.abs(denom) > DENOM_EPS * scale) & (n_w >= MIN_VALID_PAIRS)
    beta_a = np.full(n_w.shape, np.nan, dtype=np.float64)
    np.divide(numer, denom, out=beta_a, where=rank_ok)
    beta_a = np.where(np.isfinite(beta_a), beta_a, np.nan)

    n_b = _rolling_sum(bench_ok_a.astype(np.float64), W)
    sx_b = _rolling_sum(x_safe, W)
    sx2_b = _rolling_sum(x_safe * x_safe, W)
    var_b = (sx2_b - sx_b * sx_b / float(W)) / float(W - 1)
    bench_complete = n_b == float(W)
    bench_var_ok = bench_complete & np.isfinite(var_b) & (var_b > 0)

    enough_pairs = n_w >= float(MIN_VALID_PAIRS)
    valid_beta = bench_var_ok[:, None] & enough_pairs & rank_ok & np.isfinite(beta_a)
    beta_a = np.where(valid_beta, beta_a, np.nan)

    first_ok_t = cal[LOOKBACK] if len(cal) > LOOKBACK else cal[-1]
    # window formed in the numpy panel when index >= W-1, but 61 closes need index >= W
    # relative to full calendar; relative to cal_window which starts at raw_start=cal[0], same.

    beta_w = pd.DataFrame(beta_a, index=cal_window, columns=instruments)
    n_w_df = pd.DataFrame(n_w, index=cal_window, columns=instruments)
    valid_w = pd.DataFrame(valid_beta, index=cal_window, columns=instruments)
    var_s = pd.Series(var_b, index=cal_window)
    n_b_s = pd.Series(n_b, index=cal_window)
    bench_complete_s = pd.Series(bench_complete, index=cal_window)
    start_map = pd.Series(index=cal_window, dtype="datetime64[ns]")
    start_map.iloc[W - 1 :] = cal_window[: len(cal_window) - (W - 1)]

    def _melt(wide, name):
        long = wide.stack(dropna=False).rename(name)
        long.index = long.index.set_names(["datetime", "instrument"])
        return long.reset_index()

    long = _melt(beta_w.loc[start:end], "beta60")
    long = long.merge(_melt(close_w.loc[start:end], "close"), on=["datetime", "instrument"], how="left")
    long = long.merge(_melt(n_w_df.loc[start:end], "n_valid_pairs"), on=["datetime", "instrument"], how="left")
    long = long.merge(_melt(valid_w.loc[start:end], "valid_beta"), on=["datetime", "instrument"], how="left")
    long = long.merge(_melt(close_ok.loc[start:end], "close_ok"), on=["datetime", "instrument"], how="left")
    long["datetime"] = pd.to_datetime(long["datetime"]).dt.normalize()
    long["instrument"] = long["instrument"].astype(str)
    long["window_end"] = long["datetime"]
    long["window_start"] = long["datetime"].map(start_map)
    long["bench_var"] = long["datetime"].map(var_s)
    long["bench_n_valid"] = long["datetime"].map(n_b_s)
    long["bench_complete"] = long["datetime"].map(bench_complete_s).fillna(False).astype(bool)
    long["close_ok"] = long["close_ok"].fillna(False).astype(bool)
    long["valid_beta"] = long["valid_beta"].fillna(False).astype(bool)
    long["n_valid_pairs"] = pd.to_numeric(long["n_valid_pairs"], errors="coerce")

    n = len(long)
    dt = pd.to_datetime(long["datetime"])
    reasons = np.full(n, "", dtype=object)
    not_enough = dt < pd.Timestamp(first_ok_t)
    reasons = np.where(not_enough, "not_enough_history", reasons)
    rest = ~not_enough
    bench_bad = rest & (~long["bench_complete"].to_numpy())
    reasons = np.where(bench_bad, "benchmark_incomplete", reasons)
    rest = rest & ~bench_bad
    var_bad = rest & (~np.isfinite(long["bench_var"].to_numpy(dtype=float)) | (long["bench_var"].to_numpy(dtype=float) <= 0))
    reasons = np.where(var_bad, "benchmark_zero_variance", reasons)
    rest = rest & ~var_bad
    nvp = long["n_valid_pairs"].to_numpy(dtype=float)
    pair_bad = rest & (~np.isfinite(nvp) | (nvp < MIN_VALID_PAIRS))
    reasons = np.where(pair_bad, "insufficient_valid_pairs", reasons)
    rest = rest & ~pair_bad
    beta_v = long["beta60"].to_numpy(dtype=float)
    rank_bad = rest & ~np.isfinite(beta_v)
    # among remaining, nonfinite beta after n>=40 and bench ok => rank_deficient or beta_nonfinite
    reasons = np.where(rank_bad, "rank_deficient", reasons)
    long["missing_reason"] = reasons
    long.loc[long["valid_beta"] & np.isfinite(long["beta60"]), "missing_reason"] = ""
    long.loc[~long["valid_beta"], "beta60"] = np.nan

    out = base.merge(long, on=["datetime", "instrument"], how="left")
    if len(out) != len(base):
        raise RuntimeError(f"left-join changed row count {len(base)} -> {len(out)}")
    out["close_ok"] = out["close_ok"].fillna(False).astype(bool)
    out["valid_beta"] = out["valid_beta"].fillna(False).astype(bool)
    out["bench_complete"] = out["bench_complete"].fillna(False).astype(bool)
    out["n_valid_pairs"] = pd.to_numeric(out["n_valid_pairs"], errors="coerce")
    out["missing_reason"] = out["missing_reason"].fillna("not_in_raw_panel")
    out.loc[pd.to_datetime(out["datetime"]) < pd.Timestamp(first_ok_t), "missing_reason"] = "not_enough_history"

    ok = out["beta60"].notna() & np.isfinite(out["beta60"]) & out["valid_beta"]
    out[args.feature_name] = np.nan
    # beta first, then * -1, then rank. Never negate returns before OLS.
    neg = -out.loc[ok, "beta60"]
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
        raise RuntimeError("finite beta60 produced NaN rank")

    rng = np.random.default_rng(20260918)
    finite = out.loc[ok]
    sample_qc = []
    if args.sample_recompute > 0 and len(finite):
        take = min(int(args.sample_recompute), len(finite))
        picks = finite.sample(n=take, random_state=int(rng.integers(0, 2**31 - 1)))
        for _, row in picks.iterrows():
            got, n_got, reason = _recompute_one(
                str(row["instrument"]),
                pd.Timestamp(row["datetime"]).normalize(),
                cal,
                args.close_field,
                int(args.lookback_market_days),
                pd,
                np,
            )
            stored = float(row["beta60"])
            match = (
                got is not None
                and np.isfinite(got)
                and abs(got - stored) <= max(1e-12, 1e-8 * max(1.0, abs(stored)))
            )
            sample_qc.append(
                {
                    "instrument": str(row["instrument"]),
                    "datetime": pd.Timestamp(row["datetime"]).date().isoformat(),
                    "stored": stored,
                    "recomputed": got,
                    "n_valid_pairs_stored": float(row["n_valid_pairs"]) if pd.notna(row["n_valid_pairs"]) else None,
                    "n_valid_pairs_recomputed": n_got,
                    "match": bool(match),
                    "reason": reason,
                }
            )
        n_bad = sum(1 for x in sample_qc if not x["match"])
        if n_bad:
            raise RuntimeError(f"sample beta60 recompute failed: {n_bad}/{len(sample_qc)} {sample_qc[:3]}")
        print(f"[qc] beta60 recompute ok n={len(sample_qc)}", flush=True)

    rank_qc = []
    days = out.loc[ok, "datetime"].drop_duplicates().tolist()
    if days:
        take_days = min(SAMPLE_RANK_DAYS, len(days))
        day_picks = [days[i] for i in rng.choice(len(days), size=take_days, replace=False)]
        for day in day_picks:
            g = out.loc[out["datetime"] == day]
            valid = g["beta60"].notna() & np.isfinite(g["beta60"])
            recomputed = (-g.loc[valid, "beta60"]).rank(method="average", pct=True)
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
        print(f"[qc] rank(-beta60) recompute ok days={len(rank_qc)}", flush=True)

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
        if not timing_ok:
            raise RuntimeError("timing check failed: window uses dates after t")

    parquet_path = out_dir / f"{args.feature_name}.parquet"
    cols = [
        "instrument",
        "datetime",
        "window_start",
        "window_end",
        "close",
        "beta60",
        args.feature_name,
        "n_valid_pairs",
        "bench_var",
        "bench_n_valid",
        "bench_complete",
        "close_ok",
        "valid_beta",
        "missing_reason",
        "rank_n",
    ]
    out[cols].to_parquet(parquet_path, index=False)
    sidecar_sha = _sha256(parquet_path)
    key_digest = _key_digest(out)

    bench_path = out_dir / "benchmark_SH000300.csv"
    pd.DataFrame(
        {
            "datetime": pd.to_datetime(cal_window).strftime("%Y-%m-%d"),
            "close": bench_c.to_numpy(dtype=float),
            "ret": ret_b.to_numpy(dtype=float),
        }
    ).to_csv(bench_path, index=False, encoding="utf-8", lineterminator="\n")

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
        "benchmark": {
            "code": BENCHMARK,
            "digest_sha256": digest,
            "n_days": int(len(bench_c)),
            "n_missing_or_nonpositive": int(n_bench_miss),
            "first": str(cal_window[0].date()),
            "last": str(cal_window[-1].date()),
            "no_interpolation": True,
            "no_ffill": True,
            "no_cross_section_mean": True,
            "no_equal_weight_market": True,
            "path": str(bench_path),
        },
        "lookback_market_days": int(args.lookback_market_days),
        "min_valid_pairs": MIN_VALID_PAIRS,
        "ols_with_intercept": True,
        "no_window_extension": True,
        "no_return_imputation": True,
        "daily_return": "close-to-close",
        "multiply_before_rank": -1,
        "formula": (
            "r=close_d/close_{d-1}-1 for stock and SH000300 over d=t-59..t (60 market days, 61 closes); "
            "OLS with intercept r_i = a + beta60 * r_m; all finite pairs in the fixed window enter "
            "(min 40, not 'latest 40'); BETA60_ANTI_RANK = rank_pct(-beta60) on handler-day ∩ finite beta60"
        ),
        "rank": "pandas.Series.rank(method=average, pct=True) on -beta60; OLS first then * -1; never OLS(-r)",
        "not_alpha158_BETA60": True,
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
        "direction": "higher_BETA60_ANTI_RANK_higher_expected_return",
        "no_sign_flip": True,
        "online_untouched": True,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "sidecar_sha256": sidecar_sha,
                "key_digest": key_digest,
                "benchmark_digest": digest,
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
