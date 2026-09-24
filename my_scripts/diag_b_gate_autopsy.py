# -*- coding: utf-8 -*-
"""T5-MXR1 B-gate autopsy: read-only daily / Top10 / feature diagnostics. No retrain, no PortAna."""
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
FEATURE = "MAXRET20_ANTI_RANK"
TOPK = 10
SIDECAR_SHA = "27320f8b7f6de3854802f97325f682039732470ce387f21bc9cd6c3083b7b348"
PROVIDER = r"C:/Users/wangc/.qlib/qlib_data/my_data"
WINDOWS = (("2025_valid", "2025-01-03", "2025-12-31"), ("2026_oos", "2026-01-01", "2026-09-14"))
CAND_RECORDER = "d03e8ffcb6d14668b4d6fc2b192bc8c7"
CTRL_RECORDER = "8a061ea428e04bb3a199a485ade49d0e"
PARAMS_PKL = REPO / "mlruns" / "241534998488247147" / CAND_RECORDER / "artifacts" / "params.pkl"


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
    if not preferred.exists():
        preferred.mkdir(parents=True, exist_ok=False)
        return preferred
    stamp = datetime.now().strftime("%H%M%S")
    alt = preferred.parent / f"{preferred.name}_{stamp}"
    alt.mkdir(parents=True, exist_ok=False)
    return alt


def try_feature_importance() -> dict:
    out: dict = {"loaded": False}
    if not PARAMS_PKL.is_file():
        out["reason"] = f"missing {PARAMS_PKL}"
        return out
    try:
        import pickle

        with PARAMS_PKL.open("rb") as f:
            model = pickle.load(f)
        names = None
        gains = None
        booster = getattr(model, "model", model)
        if hasattr(model, "get_feature_importance"):
            try:
                ser = model.get_feature_importance()
                if ser is not None and len(ser):
                    names = [str(x) for x in ser.index]
                    gains = [float(x) for x in ser.values]
            except Exception:
                pass
        if gains is None and hasattr(booster, "feature_importance"):
            raw = booster.feature_importance(importance_type="gain")
            gains = [float(x) for x in np.asarray(raw).ravel()]
            if hasattr(booster, "feature_name"):
                names = [str(x) for x in booster.feature_name()]
        if gains is None:
            out["reason"] = f"no importance API on {type(model)}"
            return out
        if names is None:
            names = [f"f{i}" for i in range(len(gains))]
        pairs = sorted(zip(names, gains), key=lambda z: -z[1])
        total = float(sum(gains)) or 1.0
        mxr = [(n, g, g / total) for n, g in pairs if FEATURE.lower() in n.lower() or "maxret" in n.lower()]
        rank = None
        for i, (n, g) in enumerate(pairs, start=1):
            if FEATURE.lower() in n.lower() or "maxret" in n.lower():
                rank = i
                break
        out.update(
            {
                "loaded": True,
                "n_features": len(gains),
                "total_gain": total,
                "maxret_matches": [{"name": n, "gain": g, "share": s} for n, g, s in mxr],
                "maxret_rank": rank,
                "top10": [{"name": n, "gain": g, "share": g / total} for n, g in pairs[:10]],
            }
        )
        return out
    except Exception as exc:
        out["reason"] = f"{type(exc).__name__}: {exc}"
        return out


def analyze_days(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dt, g in df.groupby("datetime", sort=True):
        g = g.dropna(subset=["score_ctrl", "score_cand", "label"])
        n = len(g)
        if n < TOPK:
            continue
        ric0 = _spearman(g["score_ctrl"], g["label"])
        ric1 = _spearman(g["score_cand"], g["label"])
        g0 = g.sort_values("score_ctrl", ascending=False)
        g1 = g.sort_values("score_cand", ascending=False)
        t0 = g0.head(TOPK)
        t1 = g1.head(TOPK)
        univ = float(g["label"].mean())
        sp0 = float(t0["label"].mean() - univ)
        sp1 = float(t1["label"].mean() - univ)
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

        q = pd.qcut(g["score_ctrl"].rank(method="first"), 5, labels=False, duplicates="drop")
        q_ics = []
        for qi in range(5):
            sub = g.loc[q == qi].dropna(subset=[FEATURE])
            q_ics.append(_spearman(sub[FEATURE], sub["label"]) if len(sub) >= 4 else float("nan"))
        g_rank = g.copy()
        g_rank["rnk"] = g_rank["score_ctrl"].rank(method="first", ascending=False)
        head = g_rank[g_rank["rnk"] <= max(100, TOPK)].dropna(subset=[FEATURE])
        rest = g_rank[g_rank["rnk"] > max(100, TOPK)].dropna(subset=[FEATURE])
        rows.append(
            {
                "datetime": pd.Timestamp(dt),
                "n": n,
                "rankic_ctrl": ric0,
                "rankic_cand": ric1,
                "d_rankic": ric1 - ric0,
                "top10_ctrl": sp0,
                "top10_cand": sp1,
                "d_top10": sp1 - sp0,
                "overlap": overlap,
                "jaccard": jaccard,
                "turnover": turnover,
                "n_swapped": len(added),
                "feat_coverage": feat_cov,
                "feat_rankic": ric_feat,
                "rho_ctrl_feat": rho_ctrl_feat,
                "rho_cand_feat": rho_cand_feat,
                "rho_scores": rho_scores,
                "top10_feat_ctrl": float(t0f[FEATURE].mean()) if len(t0f) else float("nan"),
                "top10_feat_cand": float(t1f[FEATURE].mean()) if len(t1f) else float("nan"),
                "univ_feat": univ_feat,
                "added_feat": float(add_g[FEATURE].mean()) if add_g[FEATURE].notna().any() else float("nan"),
                "dropped_feat": float(drop_g[FEATURE].mean()) if drop_g[FEATURE].notna().any() else float("nan"),
                "added_label": float(add_g["label"].mean()) if len(add_g) else float("nan"),
                "dropped_label": float(drop_g["label"].mean()) if len(drop_g) else float("nan"),
                "feat_ic_q1_low": q_ics[0] if len(q_ics) > 0 else float("nan"),
                "feat_ic_q2": q_ics[1] if len(q_ics) > 1 else float("nan"),
                "feat_ic_q3": q_ics[2] if len(q_ics) > 2 else float("nan"),
                "feat_ic_q4": q_ics[3] if len(q_ics) > 3 else float("nan"),
                "feat_ic_q5_high": q_ics[4] if len(q_ics) > 4 else float("nan"),
                "feat_ic_ctrl_top100": _spearman(head[FEATURE], head["label"]) if len(head) >= 4 else float("nan"),
                "feat_ic_ctrl_rest": _spearman(rest[FEATURE], rest["label"]) if len(rest) >= 4 else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def window_of(ts: pd.Series) -> pd.Series:
    out = pd.Series(index=ts.index, dtype="object")
    for name, a, b in WINDOWS:
        m = (ts >= pd.Timestamp(a)) & (ts <= pd.Timestamp(b))
        out.loc[m] = name
    return out


def summarize(daily: pd.DataFrame) -> dict:
    daily = daily.copy()
    daily["window"] = window_of(daily["datetime"])
    daily["month"] = daily["datetime"].dt.to_period("M").astype(str)
    daily["quarter"] = daily["datetime"].dt.to_period("Q").astype(str)
    payload: dict = {"windows": {}, "months": [], "quarters": []}
    for name, a, b in WINDOWS:
        d = daily[daily["window"] == name]
        if d.empty:
            continue
        payload["windows"][name] = {
            "start": a,
            "end": b,
            "n_days": int(len(d)),
            "n_rows_mean": float(d["n"].mean()),
            "rankic_ctrl": float(d["rankic_ctrl"].mean()),
            "rankic_cand": float(d["rankic_cand"].mean()),
            "d_rankic": float(d["d_rankic"].mean()),
            "top10_ctrl": float(d["top10_ctrl"].mean()),
            "top10_cand": float(d["top10_cand"].mean()),
            "d_top10": float(d["d_top10"].mean()),
            "jaccard_mean": float(d["jaccard"].mean()),
            "jaccard_median": float(d["jaccard"].median()),
            "turnover_mean": float(d["turnover"].mean()),
            "overlap_mean": float(d["overlap"].mean()),
            "share_days_identical_top10": float((d["overlap"] == TOPK).mean()),
            "share_days_jaccard_ge_0_8": float((d["jaccard"] >= 0.8).mean()),
            "top10_feat_ctrl": float(d["top10_feat_ctrl"].mean()),
            "top10_feat_cand": float(d["top10_feat_cand"].mean()),
            "d_top10_feat": float((d["top10_feat_cand"] - d["top10_feat_ctrl"]).mean()),
            "univ_feat": float(d["univ_feat"].mean()),
            "rho_scores": float(d["rho_scores"].mean()),
            "rho_ctrl_feat": float(d["rho_ctrl_feat"].mean()),
            "rho_cand_feat": float(d["rho_cand_feat"].mean()),
            "d_rho_feat": float((d["rho_cand_feat"] - d["rho_ctrl_feat"]).mean()),
            "feat_rankic": float(d["feat_rankic"].mean()),
            "feat_ic_q1_low": float(d["feat_ic_q1_low"].mean()),
            "feat_ic_q2": float(d["feat_ic_q2"].mean()),
            "feat_ic_q3": float(d["feat_ic_q3"].mean()),
            "feat_ic_q4": float(d["feat_ic_q4"].mean()),
            "feat_ic_q5_high": float(d["feat_ic_q5_high"].mean()),
            "feat_ic_ctrl_top100": float(d["feat_ic_ctrl_top100"].mean()),
            "feat_ic_ctrl_rest": float(d["feat_ic_ctrl_rest"].mean()),
            "added_feat": float(d["added_feat"].mean()),
            "dropped_feat": float(d["dropped_feat"].mean()),
            "added_label": float(d["added_label"].mean()),
            "dropped_label": float(d["dropped_label"].mean()),
            "swap_label_gap": float((d["added_label"] - d["dropped_label"]).mean()),
            "d_top10_share_neg": float((d["d_top10"] < 0).mean()),
            "d_rankic_share_pos": float((d["d_rankic"] > 0).mean()),
        }
    for month, g in daily.groupby("month", sort=True):
        payload["months"].append(
            {
                "month": month,
                "window": str(g["window"].iloc[0]),
                "n_days": int(len(g)),
                "d_rankic": float(g["d_rankic"].mean()),
                "d_top10": float(g["d_top10"].mean()),
                "d_top10_sum": float(g["d_top10"].sum()),
                "jaccard": float(g["jaccard"].mean()),
                "turnover": float(g["turnover"].mean()),
                "d_top10_feat": float((g["top10_feat_cand"] - g["top10_feat_ctrl"]).mean()),
                "d_top10_share_neg": float((g["d_top10"] < 0).mean()),
            }
        )
    for q, g in daily.groupby("quarter", sort=True):
        payload["quarters"].append(
            {
                "quarter": q,
                "window": str(g["window"].iloc[0]),
                "n_days": int(len(g)),
                "d_rankic": float(g["d_rankic"].mean()),
                "d_top10": float(g["d_top10"].mean()),
                "jaccard": float(g["jaccard"].mean()),
            }
        )
    y25 = daily[daily["window"] == "2025_valid"]
    if len(y25):
        by_sum = y25.groupby(y25["datetime"].dt.to_period("M"))["d_top10"].sum().sort_values()
        payload["top10_drag_2025_months"] = [
            {"month": str(k), "d_top10_sum": float(v), "d_top10_mean": float(y25.loc[y25["datetime"].dt.to_period("M") == k, "d_top10"].mean())}
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
    _two_panel("d_top10", "Daily ΔTop10Spread vs universe EW (cand-ctrl)", "daily_delta_top10.png")
    _two_panel("jaccard", "Daily Top10 Jaccard (cand vs ctrl)", "daily_top10_jaccard.png", hline=1.0)
    _two_panel("turnover", "Daily Top10 turnover vs ctrl (1 - overlap/10)", "daily_top10_turnover.png")

    feat_delta = daily["top10_feat_cand"] - daily["top10_feat_ctrl"]
    tmp = daily.assign(d_top10_feat=feat_delta)
    fig, axes = plt.subplots(2, 1, figsize=(12, 7))
    for ax, name in zip(axes, ("2025_valid", "2026_oos")):
        d = tmp[window_of(tmp["datetime"]) == name]
        ax.plot(d["datetime"], d["top10_feat_ctrl"], lw=0.8, label="ctrl Top10 MAXRET")
        ax.plot(d["datetime"], d["top10_feat_cand"], lw=0.8, label="cand Top10 MAXRET")
        ax.plot(d["datetime"], d["univ_feat"], lw=0.7, color="0.5", label="universe mean")
        ax.set_title(f"Top10 MAXRET20_ANTI_RANK exposure · {name}")
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
            .agg(d_rankic=("d_rankic", "mean"), d_top10=("d_top10", "mean"))
            .reset_index()
        )
        fig, ax = plt.subplots(figsize=(11, 4.5))
        x = np.arange(len(m))
        w = 0.38
        ax.bar(x - w / 2, m["d_rankic"], w, label="mean ΔRankIC", color="#2a6f97")
        ax.bar(x + w / 2, m["d_top10"], w, label="mean ΔTop10Spread", color="#c44536")
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
    preferred = REPO / "exports" / "analysis" / "t5_mxr1_20260918" / "b_diag_20260919"
    out = pick_out_dir(preferred)
    print(f"[out] {out}", flush=True)

    sidecar = REPO / "exports" / "analysis" / "t5_mxr1_20260918" / "sidecar" / "MAXRET20_ANTI_RANK.parquet"
    got = sha256_file(sidecar)
    if got.lower() != SIDECAR_SHA.lower():
        raise RuntimeError(f"sidecar sha mismatch {got}")

    ctrl25 = load_pred(SCRIPT_DIR / "预测结果_8a061ea4_2025valid.csv")
    cand25 = load_pred(REPO / "exports" / "analysis" / "t5_mxr1_20260918" / "model" / "pred_2025.csv")
    ctrl26 = load_pred(REPO / "exports" / "analysis" / "t5_mxr1_20260918" / "control_pred_2026_8a061ea4.csv")
    cand26 = load_pred(REPO / "exports" / "analysis" / "t5_mxr1_20260918" / "model" / "pred_2026.csv")
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
    print(f"[labels] rows={len(labels)}", flush=True)

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
    daily = analyze_days(merged)
    daily.to_csv(out / "daily_metrics.csv", index=False, encoding="utf-8")
    print(f"[daily] {len(daily)} days", flush=True)

    summary = summarize(daily)
    frozen = json.loads((REPO / "exports" / "analysis" / "t5_mxr1_20260918" / "pred_pair" / "verdict.json").read_text(encoding="utf-8"))
    wrd1 = json.loads(
        Path(r"D:\PycharmProjects\wt-myquant-pr78-t5-wrd1\exports\analysis\t5_wrd1_20260918\pred_pair\verdict.json").read_text(
            encoding="utf-8"
        )
    )
    a_daily = pd.read_csv(REPO / "exports" / "analysis" / "t5_mxr1_20260918" / "information" / "daily_partial_rankic.csv")
    a_daily["datetime"] = pd.to_datetime(a_daily["datetime"]).dt.normalize()
    joined = daily.merge(a_daily[["datetime", "partial_rankic"]], on="datetime", how="left")
    corr_a_b = {}
    for name, _, _ in WINDOWS:
        j = joined[window_of(joined["datetime"]) == name]
        corr_a_b[name] = {
            "corr_partial_vs_d_rankic": float(j["partial_rankic"].corr(j["d_rankic"])),
            "corr_partial_vs_d_top10": float(j["partial_rankic"].corr(j["d_top10"])),
            "n": int(j["partial_rankic"].notna().sum()),
            "partial_mean": float(j["partial_rankic"].mean()),
        }
    joined[["datetime", "d_rankic", "d_top10", "partial_rankic", "feat_rankic", "rho_scores"]].to_csv(
        out / "daily_a_vs_b.csv", index=False, encoding="utf-8"
    )

    pd.DataFrame(summary["months"]).to_csv(out / "monthly_summary.csv", index=False, encoding="utf-8")
    pd.DataFrame(summary["quarters"]).to_csv(out / "quarterly_summary.csv", index=False, encoding="utf-8")

    plots = make_plots(daily, out)
    fi = try_feature_importance()
    print(f"[importance] {json.dumps(json_safe(fi), ensure_ascii=False)[:400]}", flush=True)

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "out_dir": str(out),
        "git_head": "112faf4a67663239e1059e4974cf43b087b106f8",
        "sidecar_sha256": got,
        "label": LABEL,
        "top10_spread_vs": "common-universe-equal-weight",
        "control_recorder": CTRL_RECORDER,
        "candidate_recorder": CAND_RECORDER,
        "online_untouched": True,
        "no_retrain": True,
        "no_portana": True,
        "summary": summary,
        "a_vs_b": corr_a_b,
        "frozen_b": frozen,
        "wrd1_b": wrd1,
        "feature_importance": fi,
        "plots": plots,
        "recompute_vs_frozen": {
            name: {
                "d_rankic_recomputed": summary["windows"][name]["d_rankic"],
                "d_rankic_frozen": next(w["rankic_delta"] for w in frozen["windows"] if w["window"] == name),
                "d_top10_recomputed": summary["windows"][name]["d_top10"],
                "d_top10_frozen": next(w["top10_delta"] for w in frozen["windows"] if w["window"] == name),
            }
            for name in summary["windows"]
        },
    }
    (out / "summary.json").write_text(json.dumps(json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out), "windows": json_safe(summary["windows"])}, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
