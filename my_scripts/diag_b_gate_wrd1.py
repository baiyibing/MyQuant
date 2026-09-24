# -*- coding: utf-8 -*-
"""T5-WRD1 B-gate autopsy: read-only daily / Top10 / feature diagnostics.

No retrain, no PortAna, no sidecar rewrite, no 伪实验.
Diagnostic Top10Spread = equal-weight Top10 − common-universe equal-weight label.
Frozen B-gate Top10Spread (Top−Bottom) is reproduced only as an alignment check.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import host_env  # noqa: F401
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
REPO = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

LABEL = "Ref($close,-2)/Ref($close,-1)-1"
FEATURE = "BROKER_WR_GAP"
TOPK = 10
SIDECAR_SHA = "34453f4679ded0ba8233c16eee33c916e87d5eecca16fee15c7e5173424a6d65"
PROVIDER = r"C:/Users/wangc/.qlib/qlib_data/my_data"
WINDOWS = (("2025_valid", "2025-01-03", "2025-12-31"), ("2026_oos", "2026-01-01", "2026-09-14"))
CAND_RECORDER = "5ef339db2fdc4f56815edf78d17e3017"
CTRL_RECORDER = "8a061ea428e04bb3a199a485ade49d0e"
PARAMS_PKL = (
    SCRIPT_DIR
    / "mlruns"
    / "649535496764271729"
    / CAND_RECORDER
    / "artifacts"
    / "params.pkl"
)
BOOT_BLOCK = 5
BOOT_REPS = 10_000
BOOT_SEED = 20260919
GIT_HEAD = "397c904"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_pred(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    out = df[[cols["datetime"], cols.get("instrument") or cols["asset"], cols["score"]]].copy()
    out.columns = ["datetime", "instrument", "score"]
    out["datetime"] = pd.to_datetime(out["datetime"]).dt.normalize()
    out["instrument"] = out["instrument"].astype(str)
    out["score"] = pd.to_numeric(out["score"], errors="coerce")
    return out.dropna(subset=["score"])


def load_labels(instruments, start: str, end: str) -> pd.DataFrame:
    from qlib.data import D

    raw = D.features(list(instruments), [LABEL], start_time=start, end_time=end)
    frame = raw.reset_index() if isinstance(raw.index, pd.MultiIndex) else raw.copy()
    if LABEL not in frame.columns:
        vals = [c for c in frame.columns if c not in {"datetime", "instrument"}]
        frame = frame.rename(columns={vals[0]: LABEL})
    out = frame[["datetime", "instrument", LABEL]].rename(columns={LABEL: "label"})
    out["datetime"] = pd.to_datetime(out["datetime"]).dt.normalize()
    out["instrument"] = out["instrument"].astype(str)
    out["label"] = pd.to_numeric(out["label"], errors="coerce")
    return out


def _spearman(a: pd.Series, b: pd.Series) -> float:
    if len(a) < 4:
        return float("nan")
    return float(a.corr(b, method="spearman"))


def pick_out_dir(preferred: Path) -> Path:
    if preferred.exists():
        raise SystemExit(f"[FAIL] out-dir exists (fail-closed): {preferred}")
    preferred.mkdir(parents=True, exist_ok=False)
    return preferred


def moving_block_bootstrap_ci(x: np.ndarray, block: int, reps: int, seed: int):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < block + 1:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = np.empty(reps, dtype=float)
    n_blocks = int(np.ceil(n / block))
    for i in range(reps):
        starts = rng.integers(0, n - block + 1, size=n_blocks)
        chunks = [x[s : s + block] for s in starts]
        sample = np.concatenate(chunks)[:n]
        means[i] = sample.mean()
    lo, hi = np.quantile(means, [0.025, 0.975])
    return float(x.mean()), float(lo), float(hi)


def try_feature_importance() -> dict:
    out: dict = {"loaded": False, "params_pkl": str(PARAMS_PKL)}
    if not PARAMS_PKL.is_file():
        out["reason"] = f"missing {PARAMS_PKL}"
        return out
    try:
        import pickle

        with PARAMS_PKL.open("rb") as f:
            model = pickle.load(f)
        names = None
        gains = None
        splits = None
        booster = getattr(model, "model", model)
        if hasattr(model, "get_feature_importance"):
            try:
                ser = model.get_feature_importance()
                if ser is not None and len(ser):
                    names = [str(x) for x in ser.index]
                    gains = [float(x) for x in ser.values]
            except Exception:
                pass
        if hasattr(booster, "feature_importance"):
            if gains is None:
                raw = booster.feature_importance(importance_type="gain")
                gains = [float(x) for x in np.asarray(raw).ravel()]
            try:
                raw_s = booster.feature_importance(importance_type="split")
                splits = [float(x) for x in np.asarray(raw_s).ravel()]
            except Exception:
                splits = None
            if names is None and hasattr(booster, "feature_name"):
                try:
                    names = [str(x) for x in booster.feature_name()]
                except Exception:
                    names = None
        if gains is None:
            out["reason"] = f"no importance API on {type(model)}"
            return out
        if names is None:
            names = [f"Column_{i}" for i in range(len(gains))]
        if len(names) != len(gains):
            names = [f"Column_{i}" for i in range(len(gains))]
        total_g = float(sum(gains)) or 1.0
        gain_pairs = sorted(zip(names, gains), key=lambda z: -z[1])
        last_name = names[-1]
        # sidecar was left-joined as the last extra column (lineage n_feat=184)
        target_names = {FEATURE, last_name, f"Column_{len(gains) - 1}"}
        rank_gain = None
        match = None
        for i, (n, g) in enumerate(gain_pairs, start=1):
            if n in target_names or FEATURE.lower() in n.lower() or "broker_wr" in n.lower():
                rank_gain = i
                match = {"name": n, "gain": g, "share": g / total_g}
                break
        if match is None:
            n, g = last_name, gains[-1]
            rank_gain = next(i for i, (nn, _) in enumerate(gain_pairs, start=1) if nn == n)
            match = {"name": n, "gain": g, "share": g / total_g, "assumed_last_column": True}
        med = float(np.median(gains))
        rank_split = None
        split_share = None
        if splits is not None and len(splits) == len(names):
            total_s = float(sum(splits)) or 1.0
            split_pairs = sorted(zip(names, splits), key=lambda z: -z[1])
            for i, (n, s) in enumerate(split_pairs, start=1):
                if n == match["name"]:
                    rank_split = i
                    split_share = s / total_s
                    match["split"] = s
                    match["split_share"] = split_share
                    break
        out.update(
            {
                "loaded": True,
                "model_type": str(type(model)),
                "n_features": len(gains),
                "total_gain": total_g,
                "median_gain": med,
                "last_column": last_name,
                "feature_match": match,
                "gain_rank": rank_gain,
                "split_rank": rank_split,
                "gain_vs_median": (match["gain"] / med) if med else None,
                "top20_gain": [{"name": n, "gain": g, "share": g / total_g} for n, g in gain_pairs[:20]],
            }
        )
        return out
    except Exception as exc:
        out["reason"] = f"{type(exc).__name__}: {exc}"
        return out


def analyze_days(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    swap_rows = []
    for dt, g in df.groupby("datetime", sort=True):
        g = g.dropna(subset=["score_ctrl", "score_cand", "label"]).copy()
        n = len(g)
        if n < TOPK * 2:
            continue
        ric0 = _spearman(g["score_ctrl"], g["label"])
        ric1 = _spearman(g["score_cand"], g["label"])
        # B-gate sort (unstable default) for frozen Top−Bottom alignment
        g0 = g.sort_values("score_ctrl", ascending=False)
        g1 = g.sort_values("score_cand", ascending=False)
        t0 = g0.head(TOPK)
        t1 = g1.head(TOPK)
        b0 = g0.tail(TOPK)
        b1 = g1.tail(TOPK)
        univ = float(g["label"].mean())
        top0 = float(t0["label"].mean())
        top1 = float(t1["label"].mean())
        bot0 = float(b0["label"].mean())
        bot1 = float(b1["label"].mean())
        sp0_univ = top0 - univ
        sp1_univ = top1 - univ
        sp0_tb = top0 - bot0
        sp1_tb = top1 - bot1
        s0 = set(t0["instrument"])
        s1 = set(t1["instrument"])
        inter = s0 & s1
        union = s0 | s1
        overlap = len(inter)
        jaccard = overlap / len(union) if union else float("nan")
        turnover = (TOPK - overlap) / TOPK
        added = s1 - s0
        dropped = s0 - s1
        feat = g.dropna(subset=[FEATURE])
        g["feat_pct"] = g[FEATURE].rank(method="average", pct=True)
        feat_cov = float(len(feat) / n) if n else float("nan")
        ric_feat = _spearman(feat[FEATURE], feat["label"]) if len(feat) >= 4 else float("nan")
        rho_ctrl_feat = _spearman(feat["score_ctrl"], feat[FEATURE]) if len(feat) >= 4 else float("nan")
        rho_cand_feat = _spearman(feat["score_cand"], feat[FEATURE]) if len(feat) >= 4 else float("nan")
        rho_scores = _spearman(g["score_ctrl"], g["score_cand"])
        t0f = t0.dropna(subset=[FEATURE])
        t1f = t1.dropna(subset=[FEATURE])
        univ_feat = float(feat[FEATURE].mean()) if len(feat) else float("nan")
        add_g = g[g["instrument"].isin(added)]
        drop_g = g[g["instrument"].isin(dropped)]
        kth0 = float(t0["score_ctrl"].iloc[-1]) if len(t0) else float("nan")
        kth1 = float(t1["score_cand"].iloc[-1]) if len(t1) else float("nan")

        q = pd.qcut(g["score_ctrl"].rank(method="first"), 5, labels=False, duplicates="drop")
        q_ics = []
        for qi in range(5):
            sub = g.loc[q == qi].dropna(subset=[FEATURE])
            q_ics.append(_spearman(sub[FEATURE], sub["label"]) if len(sub) >= 4 else float("nan"))
        g_rank = g.copy()
        g_rank["rnk"] = g_rank["score_ctrl"].rank(method="first", ascending=False)
        head = g_rank[g_rank["rnk"] <= max(100, TOPK)].dropna(subset=[FEATURE])
        rest = g_rank[g_rank["rnk"] > max(100, TOPK)].dropna(subset=[FEATURE])

        for inst in sorted(added):
            r = g.loc[g["instrument"] == inst].iloc[0]
            swap_rows.append(
                {
                    "datetime": pd.Timestamp(dt),
                    "instrument": inst,
                    "direction": "in",
                    FEATURE: float(r[FEATURE]) if pd.notna(r[FEATURE]) else float("nan"),
                    "feat_pct": float(r["feat_pct"]) if pd.notna(r["feat_pct"]) else float("nan"),
                    "label": float(r["label"]),
                    "score_ctrl": float(r["score_ctrl"]),
                    "score_cand": float(r["score_cand"]),
                }
            )
        for inst in sorted(dropped):
            r = g.loc[g["instrument"] == inst].iloc[0]
            swap_rows.append(
                {
                    "datetime": pd.Timestamp(dt),
                    "instrument": inst,
                    "direction": "out",
                    FEATURE: float(r[FEATURE]) if pd.notna(r[FEATURE]) else float("nan"),
                    "feat_pct": float(r["feat_pct"]) if pd.notna(r["feat_pct"]) else float("nan"),
                    "label": float(r["label"]),
                    "score_ctrl": float(r["score_ctrl"]),
                    "score_cand": float(r["score_cand"]),
                }
            )

        rows.append(
            {
                "datetime": pd.Timestamp(dt),
                "n": n,
                "rankic_ctrl": ric0,
                "rankic_cand": ric1,
                "d_rankic": ric1 - ric0,
                "top10_univ_ctrl": sp0_univ,
                "top10_univ_cand": sp1_univ,
                "d_top10_univ": sp1_univ - sp0_univ,
                "top10_tb_ctrl": sp0_tb,
                "top10_tb_cand": sp1_tb,
                "d_top10_tb": sp1_tb - sp0_tb,
                "top_mean_ctrl": top0,
                "top_mean_cand": top1,
                "bot_mean_ctrl": bot0,
                "bot_mean_cand": bot1,
                "d_top_mean": top1 - top0,
                "d_bot_mean": bot1 - bot0,
                "univ_label": univ,
                "overlap": overlap,
                "jaccard": jaccard,
                "turnover": turnover,
                "n_swapped": len(added),
                "n_at_kth_ctrl": int((g["score_ctrl"] == kth0).sum()),
                "n_at_kth_cand": int((g["score_cand"] == kth1).sum()),
                "feat_coverage": feat_cov,
                "feat_rankic": ric_feat,
                "rho_ctrl_feat": rho_ctrl_feat,
                "rho_cand_feat": rho_cand_feat,
                "rho_scores": rho_scores,
                "top10_feat_ctrl": float(t0f[FEATURE].mean()) if len(t0f) else float("nan"),
                "top10_feat_cand": float(t1f[FEATURE].mean()) if len(t1f) else float("nan"),
                "univ_feat": univ_feat,
                "top10_feat_pct_ctrl": float(g.loc[g["instrument"].isin(s0), "feat_pct"].mean()) if overlap or s0 else float("nan"),
                "top10_feat_pct_cand": float(g.loc[g["instrument"].isin(s1), "feat_pct"].mean()) if s1 else float("nan"),
                "added_feat": float(add_g[FEATURE].mean()) if add_g[FEATURE].notna().any() else float("nan"),
                "dropped_feat": float(drop_g[FEATURE].mean()) if drop_g[FEATURE].notna().any() else float("nan"),
                "added_feat_pct": float(add_g["feat_pct"].mean()) if len(add_g) else float("nan"),
                "dropped_feat_pct": float(drop_g["feat_pct"].mean()) if len(drop_g) else float("nan"),
                "added_label": float(add_g["label"].mean()) if len(add_g) else float("nan"),
                "dropped_label": float(drop_g["label"].mean()) if len(drop_g) else float("nan"),
                "swap_label_gap": (
                    float(add_g["label"].mean() - drop_g["label"].mean()) if len(add_g) and len(drop_g) else float("nan")
                ),
                "swap_feat_gap": (
                    float(add_g[FEATURE].mean() - drop_g[FEATURE].mean())
                    if add_g[FEATURE].notna().any() and drop_g[FEATURE].notna().any()
                    else float("nan")
                ),
                "swap_feat_pct_gap": (
                    float(add_g["feat_pct"].mean() - drop_g["feat_pct"].mean())
                    if len(add_g) and len(drop_g)
                    else float("nan")
                ),
                "added_share_feat_below_med": float((add_g["feat_pct"] < 0.5).mean()) if len(add_g) else float("nan"),
                "feat_ic_q1_low": q_ics[0] if len(q_ics) > 0 else float("nan"),
                "feat_ic_q2": q_ics[1] if len(q_ics) > 1 else float("nan"),
                "feat_ic_q3": q_ics[2] if len(q_ics) > 2 else float("nan"),
                "feat_ic_q4": q_ics[3] if len(q_ics) > 3 else float("nan"),
                "feat_ic_q5_high": q_ics[4] if len(q_ics) > 4 else float("nan"),
                "feat_ic_ctrl_top100": _spearman(head[FEATURE], head["label"]) if len(head) >= 4 else float("nan"),
                "feat_ic_ctrl_rest": _spearman(rest[FEATURE], rest["label"]) if len(rest) >= 4 else float("nan"),
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(swap_rows)


def window_of(ts: pd.Series) -> pd.Series:
    out = pd.Series(index=ts.index, dtype="object")
    for name, a, b in WINDOWS:
        m = (ts >= pd.Timestamp(a)) & (ts <= pd.Timestamp(b))
        out.loc[m] = name
    return out


def _mean(s: pd.Series) -> float:
    return float(s.mean()) if len(s) else float("nan")


def summarize(daily: pd.DataFrame, swaps: pd.DataFrame) -> dict:
    daily = daily.copy()
    daily["window"] = window_of(daily["datetime"])
    daily["month"] = daily["datetime"].dt.to_period("M").astype(str)
    daily["quarter"] = daily["datetime"].dt.to_period("Q").astype(str)
    if len(swaps):
        swaps = swaps.copy()
        swaps["window"] = window_of(swaps["datetime"])
    payload: dict = {"windows": {}, "months": [], "quarters": [], "swaps": {}}
    for name, a, b in WINDOWS:
        d = daily[daily["window"] == name]
        if d.empty:
            continue
        has_swap = d["n_swapped"] > 0
        payload["windows"][name] = {
            "start": a,
            "end": b,
            "n_days": int(len(d)),
            "n_rows_mean": float(d["n"].mean()),
            "rankic_ctrl": float(d["rankic_ctrl"].mean()),
            "rankic_cand": float(d["rankic_cand"].mean()),
            "d_rankic": float(d["d_rankic"].mean()),
            "top10_univ_ctrl": float(d["top10_univ_ctrl"].mean()),
            "top10_univ_cand": float(d["top10_univ_cand"].mean()),
            "d_top10_univ": float(d["d_top10_univ"].mean()),
            "top10_tb_ctrl": float(d["top10_tb_ctrl"].mean()),
            "top10_tb_cand": float(d["top10_tb_cand"].mean()),
            "d_top10_tb": float(d["d_top10_tb"].mean()),
            "d_top_mean": float(d["d_top_mean"].mean()),
            "d_bot_mean": float(d["d_bot_mean"].mean()),
            "jaccard_mean": float(d["jaccard"].mean()),
            "jaccard_median": float(d["jaccard"].median()),
            "turnover_mean": float(d["turnover"].mean()),
            "overlap_mean": float(d["overlap"].mean()),
            "n_swapped_mean": float(d["n_swapped"].mean()),
            "share_days_identical_top10": float((d["overlap"] == TOPK).mean()),
            "share_days_jaccard_ge_0_8": float((d["jaccard"] >= 0.8).mean()),
            "share_days_kth_tied_ctrl": float((d["n_at_kth_ctrl"] > 1).mean()),
            "mean_n_at_kth_ctrl": float(d["n_at_kth_ctrl"].mean()),
            "top10_feat_ctrl": float(d["top10_feat_ctrl"].mean()),
            "top10_feat_cand": float(d["top10_feat_cand"].mean()),
            "d_top10_feat": float((d["top10_feat_cand"] - d["top10_feat_ctrl"]).mean()),
            "univ_feat": float(d["univ_feat"].mean()),
            "top10_feat_pct_ctrl": float(d["top10_feat_pct_ctrl"].mean()),
            "top10_feat_pct_cand": float(d["top10_feat_pct_cand"].mean()),
            "rho_scores": float(d["rho_scores"].mean()),
            "rho_ctrl_feat": float(d["rho_ctrl_feat"].mean()),
            "rho_cand_feat": float(d["rho_cand_feat"].mean()),
            "d_rho_feat": float((d["rho_cand_feat"] - d["rho_ctrl_feat"]).mean()),
            "feat_rankic": float(d["feat_rankic"].mean()),
            "feat_coverage": float(d["feat_coverage"].mean()),
            "feat_ic_q1_low": float(d["feat_ic_q1_low"].mean()),
            "feat_ic_q2": float(d["feat_ic_q2"].mean()),
            "feat_ic_q3": float(d["feat_ic_q3"].mean()),
            "feat_ic_q4": float(d["feat_ic_q4"].mean()),
            "feat_ic_q5_high": float(d["feat_ic_q5_high"].mean()),
            "feat_ic_ctrl_top100": float(d["feat_ic_ctrl_top100"].mean()),
            "feat_ic_ctrl_rest": float(d["feat_ic_ctrl_rest"].mean()),
            "added_feat": _mean(d.loc[has_swap, "added_feat"]),
            "dropped_feat": _mean(d.loc[has_swap, "dropped_feat"]),
            "added_feat_pct": _mean(d.loc[has_swap, "added_feat_pct"]),
            "dropped_feat_pct": _mean(d.loc[has_swap, "dropped_feat_pct"]),
            "added_label": _mean(d.loc[has_swap, "added_label"]),
            "dropped_label": _mean(d.loc[has_swap, "dropped_label"]),
            "swap_label_gap": _mean(d.loc[has_swap, "swap_label_gap"]),
            "swap_feat_gap": _mean(d.loc[has_swap, "swap_feat_gap"]),
            "swap_feat_pct_gap": _mean(d.loc[has_swap, "swap_feat_pct_gap"]),
            "added_share_feat_below_med": _mean(d.loc[has_swap, "added_share_feat_below_med"]),
            "d_top10_univ_share_neg": float((d["d_top10_univ"] < 0).mean()),
            "d_top10_tb_share_neg": float((d["d_top10_tb"] < 0).mean()),
            "d_rankic_share_pos": float((d["d_rankic"] > 0).mean()),
        }
        if len(swaps):
            sw = swaps[swaps["window"] == name]
            inn = sw[sw["direction"] == "in"]
            outt = sw[sw["direction"] == "out"]
            payload["swaps"][name] = {
                "n_in": int(len(inn)),
                "n_out": int(len(outt)),
                "in_feat_mean": _mean(inn[FEATURE]),
                "out_feat_mean": _mean(outt[FEATURE]),
                "in_feat_pct_mean": _mean(inn["feat_pct"]),
                "out_feat_pct_mean": _mean(outt["feat_pct"]),
                "in_feat_pct_median": float(inn["feat_pct"].median()) if len(inn) else float("nan"),
                "out_feat_pct_median": float(outt["feat_pct"].median()) if len(outt) else float("nan"),
                "in_label_mean": _mean(inn["label"]),
                "out_label_mean": _mean(outt["label"]),
                "in_share_feat_below_med": float((inn["feat_pct"] < 0.5).mean()) if len(inn) else float("nan"),
                "in_share_label_neg": float((inn["label"] < 0).mean()) if len(inn) else float("nan"),
                "out_share_label_neg": float((outt["label"] < 0).mean()) if len(outt) else float("nan"),
            }
    for month, g in daily.groupby("month", sort=True):
        payload["months"].append(
            {
                "month": month,
                "window": str(g["window"].iloc[0]),
                "n_days": int(len(g)),
                "d_rankic": float(g["d_rankic"].mean()),
                "d_top10_univ": float(g["d_top10_univ"].mean()),
                "d_top10_univ_sum": float(g["d_top10_univ"].sum()),
                "d_top10_tb": float(g["d_top10_tb"].mean()),
                "d_top10_tb_sum": float(g["d_top10_tb"].sum()),
                "jaccard": float(g["jaccard"].mean()),
                "turnover": float(g["turnover"].mean()),
                "swap_label_gap": _mean(g.loc[g["n_swapped"] > 0, "swap_label_gap"]),
                "swap_feat_pct_gap": _mean(g.loc[g["n_swapped"] > 0, "swap_feat_pct_gap"]),
                "d_top10_univ_share_neg": float((g["d_top10_univ"] < 0).mean()),
                "d_top10_tb_share_neg": float((g["d_top10_tb"] < 0).mean()),
            }
        )
    for q, g in daily.groupby("quarter", sort=True):
        payload["quarters"].append(
            {
                "quarter": q,
                "window": str(g["window"].iloc[0]),
                "n_days": int(len(g)),
                "d_rankic": float(g["d_rankic"].mean()),
                "d_top10_univ": float(g["d_top10_univ"].mean()),
                "d_top10_tb": float(g["d_top10_tb"].mean()),
                "jaccard": float(g["jaccard"].mean()),
                "swap_label_gap": _mean(g.loc[g["n_swapped"] > 0, "swap_label_gap"]),
            }
        )
    y26 = daily[daily["window"] == "2026_oos"]
    if len(y26):
        by_sum = y26.groupby(y26["datetime"].dt.to_period("M"))["d_top10_univ"].sum().sort_values()
        payload["top10_drag_2026_months"] = [
            {
                "month": str(k),
                "d_top10_univ_sum": float(v),
                "d_top10_univ_mean": float(y26.loc[y26["datetime"].dt.to_period("M") == k, "d_top10_univ"].mean()),
            }
            for k, v in by_sum.items()
        ]
    y25 = daily[daily["window"] == "2025_valid"]
    if len(y25):
        by_sum = y25.groupby(y25["datetime"].dt.to_period("M"))["d_top10_univ"].sum().sort_values()
        payload["top10_drag_2025_months"] = [
            {
                "month": str(k),
                "d_top10_univ_sum": float(v),
                "d_top10_univ_mean": float(y25.loc[y25["datetime"].dt.to_period("M") == k, "d_top10_univ"].mean()),
            }
            for k, v in by_sum.items()
        ]
    return payload


def make_plots(daily: pd.DataFrame, out: Path) -> list[str]:
    daily = daily.copy()
    daily["window"] = window_of(daily["datetime"])
    paths = []

    def _two_panel(ycol, title, fname, hline=0.0):
        fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=False)
        for ax, name in zip(axes, ("2025_valid", "2026_oos")):
            d = daily[daily["window"] == name]
            ax.plot(d["datetime"], d[ycol], lw=0.9, color="#1f4e79")
            ax.axhline(hline, color="0.4", lw=0.8)
            ax.set_title(f"{title} · {name}")
            ax.grid(True, alpha=0.3)
        fig.tight_layout()
        p = out / fname
        fig.savefig(p, dpi=140)
        plt.close(fig)
        paths.append(str(p))

    _two_panel("d_rankic", "Daily ΔRankIC (cand-ctrl)", "daily_delta_rankic.png")
    _two_panel("d_top10_univ", "Daily ΔTop10Spread vs universe EW (cand-ctrl)", "daily_delta_top10.png")
    _two_panel("d_top10_tb", "Daily ΔTop10Spread Top-Bottom (frozen B-gate)", "daily_delta_top10_tb.png")
    _two_panel("jaccard", "Daily Top10 Jaccard (cand vs ctrl)", "daily_top10_jaccard.png", hline=1.0)
    _two_panel("turnover", "Daily Top10 turnover vs ctrl (1 - overlap/10)", "daily_top10_turnover.png")

    fig, axes = plt.subplots(2, 1, figsize=(12, 7))
    for ax, name in zip(axes, ("2025_valid", "2026_oos")):
        d = daily[daily["window"] == name]
        ax.plot(d["datetime"], d["top10_feat_pct_ctrl"], lw=0.8, label="ctrl Top10 feat pct")
        ax.plot(d["datetime"], d["top10_feat_pct_cand"], lw=0.8, label="cand Top10 feat pct")
        ax.axhline(0.5, color="0.5", lw=0.7, label="cross-section median")
        ax.set_title(f"Top10 BROKER_WR_GAP cross-section percentile · {name}")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
    fig.tight_layout()
    p = out / "daily_top10_feature_exposure.png"
    fig.savefig(p, dpi=140)
    plt.close(fig)
    paths.append(str(p))

    daily["month"] = daily["datetime"].dt.to_period("M").astype(str)
    for name, fname in (("2025_valid", "monthly_2025.png"), ("2026_oos", "monthly_2026.png")):
        m = (
            daily[daily["window"] == name]
            .groupby("month", sort=True)
            .agg(d_rankic=("d_rankic", "mean"), d_top10=("d_top10_univ", "mean"))
            .reset_index()
        )
        fig, ax = plt.subplots(figsize=(11, 4.5))
        x = np.arange(len(m))
        w = 0.38
        ax.bar(x - w / 2, m["d_rankic"], w, label="mean ΔRankIC", color="#2a6f97")
        ax.bar(x + w / 2, m["d_top10"], w, label="mean ΔTop10 univ-EW", color="#c44536")
        ax.axhline(0, color="0.3", lw=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels(m["month"], rotation=45, ha="right")
        ax.set_title(f"Monthly mean deltas · {name}")
        ax.legend()
        ax.grid(True, axis="y", alpha=0.3)
        fig.tight_layout()
        p = out / fname
        fig.savefig(p, dpi=140)
        plt.close(fig)
        paths.append(str(p))
    return paths


def json_safe(v):
    if isinstance(v, dict):
        return {str(k): json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [json_safe(x) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return float(v) if math.isfinite(float(v)) else None
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (pd.Timestamp, datetime)):
        return str(v)
    return v


def main() -> int:
    preferred = REPO / "exports" / "analysis" / "t5_wrd1_20260918" / "b_diag_20260919"
    out = pick_out_dir(preferred)
    print(f"[out] {out}", flush=True)

    sidecar = REPO / "exports" / "analysis" / "t5_wrd1_20260918" / "sidecar" / "BROKER_WR_GAP.parquet"
    got = sha256_file(sidecar)
    if got.lower() != SIDECAR_SHA.lower():
        raise RuntimeError(f"sidecar sha mismatch {got}")
    print(f"[sidecar] sha ok {got}", flush=True)

    ctrl25 = load_pred(SCRIPT_DIR / "预测结果_8a061ea4_2025valid.csv")
    cand25 = load_pred(REPO / "exports" / "analysis" / "t5_wrd1_20260918" / "model" / "pred_2025.csv")
    ctrl26 = load_pred(REPO / "exports" / "analysis" / "t5_wrd1_20260918" / "control_pred_2026_8a061ea4.csv")
    cand26 = load_pred(REPO / "exports" / "analysis" / "t5_wrd1_20260918" / "model" / "pred_2026.csv")
    ctrl = pd.concat([ctrl25, ctrl26], ignore_index=True)
    cand = pd.concat([cand25, cand26], ignore_index=True)
    print(f"[pred] ctrl={len(ctrl)} cand={len(cand)}", flush=True)

    import qlib
    from qlib.constant import REG_CN

    print("[init] qlib", flush=True)
    qlib.init(provider_uri=PROVIDER, region=REG_CN, kernels=1)
    inst = sorted(set(ctrl["instrument"]) | set(cand["instrument"]))
    print(f"[labels] n_inst={len(inst)} 2025-01-03..2026-09-14", flush=True)
    labels = load_labels(inst, "2025-01-03", "2026-09-14")
    print(f"[labels] rows={len(labels)} finite={int(labels['label'].notna().sum())}", flush=True)

    print("[sidecar] load 2025+", flush=True)
    side = pd.read_parquet(sidecar, columns=["datetime", "instrument", FEATURE])
    side["datetime"] = pd.to_datetime(side["datetime"]).dt.normalize()
    side["instrument"] = side["instrument"].astype(str)
    side = side[side["datetime"] >= pd.Timestamp("2025-01-01")]

    merged = ctrl.merge(cand, on=["datetime", "instrument"], how="inner", suffixes=("_ctrl", "_cand"))
    merged = merged.merge(labels, on=["datetime", "instrument"], how="inner")
    merged = merged.merge(side, on=["datetime", "instrument"], how="left")
    lo, hi = pd.Timestamp(WINDOWS[0][1]), pd.Timestamp(WINDOWS[1][2])
    merged = merged[(merged["datetime"] >= lo) & (merged["datetime"] <= hi)]
    print(f"[merged] {len(merged)}", flush=True)

    print("[daily] compute", flush=True)
    daily, swaps = analyze_days(merged)
    daily.to_csv(out / "daily_metrics.csv", index=False, encoding="utf-8")
    if len(swaps):
        swaps.to_csv(out / "swaps_long.csv", index=False, encoding="utf-8")
    print(f"[daily] {len(daily)} days; swaps={len(swaps)}", flush=True)

    summary = summarize(daily, swaps)
    frozen = json.loads(
        (REPO / "exports" / "analysis" / "t5_wrd1_20260918" / "pred_pair" / "verdict.json").read_text(encoding="utf-8")
    )
    a_daily = pd.read_csv(REPO / "exports" / "analysis" / "t5_wrd1_20260918" / "information" / "daily_partial_rankic.csv")
    a_daily["datetime"] = pd.to_datetime(a_daily["datetime"]).dt.normalize()
    joined = daily.merge(a_daily[["datetime", "partial_rankic"]], on="datetime", how="left")
    corr_a_b = {}
    for name, _, _ in WINDOWS:
        j = joined[window_of(joined["datetime"]) == name]
        corr_a_b[name] = {
            "corr_partial_vs_d_rankic": float(j["partial_rankic"].corr(j["d_rankic"])),
            "corr_partial_vs_d_top10_univ": float(j["partial_rankic"].corr(j["d_top10_univ"])),
            "corr_partial_vs_d_top10_tb": float(j["partial_rankic"].corr(j["d_top10_tb"])),
            "n": int(j["partial_rankic"].notna().sum()),
            "partial_mean": float(j["partial_rankic"].mean()),
            "d_rankic_mean": float(j["d_rankic"].mean()),
            "decay_partial_over_d_rankic": float(j["partial_rankic"].mean() / j["d_rankic"].mean())
            if j["d_rankic"].mean()
            else None,
        }
    joined[
        [
            "datetime",
            "d_rankic",
            "d_top10_univ",
            "d_top10_tb",
            "partial_rankic",
            "feat_rankic",
            "rho_scores",
            "jaccard",
            "swap_label_gap",
            "swap_feat_pct_gap",
        ]
    ].to_csv(out / "daily_a_vs_b.csv", index=False, encoding="utf-8")

    pd.DataFrame(summary["months"]).to_csv(out / "monthly_summary.csv", index=False, encoding="utf-8")
    pd.DataFrame(summary["quarters"]).to_csv(out / "quarterly_summary.csv", index=False, encoding="utf-8")
    daily[["datetime", "overlap", "jaccard", "turnover", "n_swapped", "added_feat_pct", "dropped_feat_pct", "added_label", "dropped_label", "swap_label_gap", "d_top10_univ", "d_top10_tb"]].to_csv(
        out / "daily_top10_sets.csv", index=False, encoding="utf-8"
    )

    print("[bootstrap] diagnostic seed 20260919", flush=True)
    boot = {}
    daily_w = daily.assign(window=window_of(daily["datetime"]))
    for name, _, _ in WINDOWS:
        d = daily_w[daily_w["window"] == name]
        boot[name] = {}
        for col in ("d_rankic", "d_top10_univ", "d_top10_tb", "swap_label_gap"):
            pe, lo, hi = moving_block_bootstrap_ci(d[col].to_numpy(), BOOT_BLOCK, BOOT_REPS, BOOT_SEED)
            boot[name][col] = {"point": pe, "lo": lo, "hi": hi, "block": BOOT_BLOCK, "reps": BOOT_REPS, "seed": BOOT_SEED}

    plots = make_plots(daily, out)
    fi = try_feature_importance()
    print(f"[importance] {json.dumps(json_safe(fi), ensure_ascii=False)[:500]}", flush=True)

    mxr_summary = {}
    mxr_path = Path(r"D:\PycharmProjects\wt-myquant-pr80-t5-mxr1\exports\analysis\t5_mxr1_20260918\b_diag_20260919\REPORT.md")
    mxr_json = Path(r"D:\PycharmProjects\wt-myquant-pr80-t5-mxr1\exports\analysis\t5_mxr1_20260918\pred_pair\verdict.json")
    mxr_bdiag = Path(r"D:\PycharmProjects\wt-myquant-pr80-t5-mxr1\exports\analysis\t5_mxr1_20260918\b_diag_20260919\top10_sets_summary.json")
    if mxr_json.is_file():
        mxr_summary["frozen_b"] = json.loads(mxr_json.read_text(encoding="utf-8"))
    if mxr_bdiag.is_file():
        mxr_summary["top10_sets"] = json.loads(mxr_bdiag.read_text(encoding="utf-8"))
    mxr_summary["report_exists"] = mxr_path.is_file()

    recompute = {}
    for w in frozen["windows"]:
        name = w["window"]
        s = summary["windows"][name]
        recompute[name] = {
            "d_rankic_recomputed": s["d_rankic"],
            "d_rankic_frozen": w["rankic_delta"],
            "d_rankic_abs_err": abs(s["d_rankic"] - w["rankic_delta"]),
            "d_top10_tb_recomputed": s["d_top10_tb"],
            "d_top10_tb_frozen": w["top10_delta"],
            "d_top10_tb_abs_err": abs(s["d_top10_tb"] - w["top10_delta"]),
            "rankic_ctrl_recomputed": s["rankic_ctrl"],
            "rankic_ctrl_frozen": w["rankic_control"],
            "top10_tb_ctrl_recomputed": s["top10_tb_ctrl"],
            "top10_tb_ctrl_frozen": w["top10_control"],
            "d_top10_univ_diagnostic": s["d_top10_univ"],
        }

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "out_dir": str(out),
        "git_head": GIT_HEAD,
        "sidecar_sha256": got,
        "label": LABEL,
        "top10_spread_diagnostic": "common-universe-equal-weight",
        "top10_spread_frozen_b_gate": "top-minus-bottom",
        "control_recorder": CTRL_RECORDER,
        "candidate_recorder": CAND_RECORDER,
        "online_untouched": True,
        "no_retrain": True,
        "no_portana": True,
        "no_pseudo_run": True,
        "summary": summary,
        "a_vs_b": corr_a_b,
        "frozen_b": frozen,
        "feature_importance": fi,
        "diagnostic_bootstrap": boot,
        "plots": plots,
        "recompute_vs_frozen": recompute,
        "maxret_reference": mxr_summary,
        "verdict_unchanged": "WINRATIO_GAP_MODEL_NO_TRANSFER",
    }
    (out / "summary.json").write_text(json.dumps(json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "feature_importance.json").write_text(json.dumps(json_safe(fi), ensure_ascii=False, indent=2), encoding="utf-8")
    swap_out = {"windows": json_safe(summary.get("swaps", {})), "n_rows": int(len(swaps))}
    (out / "swap_summary.json").write_text(json.dumps(swap_out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out), "windows": json_safe(summary["windows"]), "recompute": json_safe(recompute)}, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
