# -*- coding: utf-8 -*-
"""Align Top10Spread with frozen B-gate sort, plus deterministic tie-break + Column_183 map."""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import host_env  # noqa: F401
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from diag_pred_pair import daily_rankic, daily_top10_spread, load_pred, load_labels  # noqa: E402

OUT = Path(r"D:\PycharmProjects\wt-myquant-pr80-t5-mxr1\exports\analysis\t5_mxr1_20260918\b_diag_20260919")
REPO = SCRIPT_DIR.parent
LABEL = "Ref($close,-2)/Ref($close,-1)-1"
FEATURE = "MAXRET20_ANTI_RANK"
WINDOWS = (("2025_valid", "2025-01-03", "2025-12-31"), ("2026_oos", "2026-01-01", "2026-09-14"))
PROVIDER = r"C:/Users/wangc/.qlib/qlib_data/my_data"
PARAMS_PKL = REPO / "mlruns" / "241534998488247147" / "d03e8ffcb6d14668b4d6fc2b192bc8c7" / "artifacts" / "params.pkl"


def common_pair(ctrl, cand, labels, start, end):
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    lab = labels[(labels["datetime"] >= s) & (labels["datetime"] <= e)]
    c0 = ctrl[(ctrl["datetime"] >= s) & (ctrl["datetime"] <= e)]
    c1 = cand[(cand["datetime"] >= s) & (cand["datetime"] <= e)]
    m0 = c0.merge(lab, on=["datetime", "instrument"], how="inner")
    m1 = c1.merge(lab, on=["datetime", "instrument"], how="inner")
    keys = set(zip(m0["datetime"], m0["instrument"])) & set(zip(m1["datetime"], m1["instrument"]))
    key_df = pd.DataFrame(list(keys), columns=["datetime", "instrument"])
    m0 = m0.merge(key_df, on=["datetime", "instrument"])
    m1 = m1.merge(key_df, on=["datetime", "instrument"])
    return m0, m1


def top10_det(df, score_col):
    def _one(g):
        if len(g) < 10:
            return np.nan
        g = g.sort_values([score_col, "instrument"], ascending=[False, True], kind="mergesort")
        return float(g.head(10)["label"].mean() - g["label"].mean())

    return df.groupby("datetime", sort=True).apply(_one, include_groups=False)


def top10_names(df, score_col, how="gate"):
    rows = []
    for dt, g in df.groupby("datetime", sort=True):
        if how == "gate":
            g2 = g.sort_values("score", ascending=False)
        else:
            g2 = g.sort_values([score_col if score_col in g.columns else "score", "instrument"], ascending=[False, True], kind="mergesort")
        names = list(g2.head(10)["instrument"])
        scores = list(g2.head(10)["score"] if "score" in g2.columns else g2.head(10)[score_col])
        kth = scores[-1] if scores else np.nan
        n_tie = int((g["score"] == kth).sum()) if "score" in g.columns else int((g[score_col] == kth).sum())
        rows.append({"datetime": pd.Timestamp(dt), "names": tuple(names), "kth": float(kth), "n_at_kth": n_tie})
    return pd.DataFrame(rows)


def main() -> int:
    import qlib
    from qlib.constant import REG_CN

    ctrl25 = load_pred(SCRIPT_DIR / "预测结果_8a061ea4_2025valid.csv")
    cand25 = load_pred(REPO / "exports" / "analysis" / "t5_mxr1_20260918" / "model" / "pred_2025.csv")
    ctrl26 = load_pred(REPO / "exports" / "analysis" / "t5_mxr1_20260918" / "control_pred_2026_8a061ea4.csv")
    cand26 = load_pred(REPO / "exports" / "analysis" / "t5_mxr1_20260918" / "model" / "pred_2026.csv")
    print("[init] qlib", flush=True)
    qlib.init(provider_uri=PROVIDER, region=REG_CN, kernels=1)
    inst = sorted(set(ctrl25["instrument"]) | set(cand25["instrument"]) | set(ctrl26["instrument"]) | set(cand26["instrument"]))
    labels = load_labels(inst, "2025-01-03", "2026-09-14", LABEL)
    print(f"[labels] {len(labels)}", flush=True)

    daily_rows = []
    window_stats = {}
    for name, a, b in WINDOWS:
        ctrl = ctrl25 if name.startswith("2025") else ctrl26
        cand = cand25 if name.startswith("2025") else cand26
        m0, m1 = common_pair(ctrl, cand, labels, a, b)
        ric0 = daily_rankic(m0)
        ric1 = daily_rankic(m1)
        sp0 = daily_top10_spread(m0, topk=10)
        sp1 = daily_top10_spread(m1, topk=10)
        sp0d = top10_det(m0.rename(columns={"score": "score"}), "score")
        # rebuild det using m0/m1 score column
        sp0d = top10_det(m0, "score")
        sp1d = top10_det(m1, "score")
        n0 = top10_names(m0, "score", how="gate")
        n1 = top10_names(m1, "score", how="gate")
        nd0 = top10_names(m0, "score", how="det")
        nd1 = top10_names(m1, "score", how="det")
        aligned = pd.DataFrame(
            {
                "datetime": sp0.index,
                "window": name,
                "rankic_ctrl": ric0.reindex(sp0.index).to_numpy(),
                "rankic_cand": ric1.reindex(sp0.index).to_numpy(),
                "d_rankic": (ric1 - ric0).reindex(sp0.index).to_numpy(),
                "top10_ctrl_gate": sp0.to_numpy(),
                "top10_cand_gate": sp1.reindex(sp0.index).to_numpy(),
                "d_top10_gate": (sp1 - sp0).reindex(sp0.index).to_numpy(),
                "top10_ctrl_det": sp0d.reindex(sp0.index).to_numpy(),
                "top10_cand_det": sp1d.reindex(sp0.index).to_numpy(),
                "d_top10_det": (sp1d - sp0d).reindex(sp0.index).to_numpy(),
            }
        )
        n0 = n0.set_index("datetime")
        n1 = n1.set_index("datetime")
        aligned["overlap_gate"] = [
            len(set(n0.loc[dt, "names"]) & set(n1.loc[dt, "names"])) if dt in n0.index and dt in n1.index else np.nan
            for dt in aligned["datetime"]
        ]
        aligned["ctrl_n_at_kth"] = [n0.loc[dt, "n_at_kth"] if dt in n0.index else np.nan for dt in aligned["datetime"]]
        aligned["cand_n_at_kth"] = [n1.loc[dt, "n_at_kth"] if dt in n1.index else np.nan for dt in aligned["datetime"]]
        aligned["gate_vs_det_ctrl_same"] = [
            n0.loc[dt, "names"] == nd0.set_index("datetime").loc[dt, "names"] if dt in nd0.set_index("datetime").index else False
            for dt in aligned["datetime"]
        ]
        daily_rows.append(aligned)
        window_stats[name] = {
            "n_days": int(len(aligned)),
            "n_common_rows": int(len(m0)),
            "d_rankic": float(aligned["d_rankic"].mean()),
            "d_top10_gate": float(aligned["d_top10_gate"].mean()),
            "d_top10_det": float(aligned["d_top10_det"].mean()),
            "top10_ctrl_gate": float(aligned["top10_ctrl_gate"].mean()),
            "top10_cand_gate": float(aligned["top10_cand_gate"].mean()),
            "share_days_kth_tied_ctrl": float((aligned["ctrl_n_at_kth"] > 1).mean()),
            "share_days_kth_tied_cand": float((aligned["cand_n_at_kth"] > 1).mean()),
            "mean_n_at_kth_ctrl": float(aligned["ctrl_n_at_kth"].mean()),
        }
        print(name, window_stats[name], flush=True)

    daily = pd.concat(daily_rows, ignore_index=True)
    daily.to_csv(OUT / "daily_top10_gate_vs_det.csv", index=False, encoding="utf-8")
    daily["month"] = pd.to_datetime(daily["datetime"]).dt.to_period("M").astype(str)
    monthly = (
        daily.groupby(["window", "month"], sort=True)
        .agg(
            n_days=("d_top10_gate", "size"),
            d_rankic=("d_rankic", "mean"),
            d_top10_gate=("d_top10_gate", "mean"),
            d_top10_gate_sum=("d_top10_gate", "sum"),
            d_top10_det=("d_top10_det", "mean"),
            d_top10_det_sum=("d_top10_det", "sum"),
            d_top10_gate_share_neg=("d_top10_gate", lambda s: float((s < 0).mean())),
        )
        .reset_index()
    )
    monthly.to_csv(OUT / "monthly_top10_gate.csv", index=False, encoding="utf-8")

    y25 = daily[daily["window"] == "2025_valid"]
    drag = y25.groupby("month")["d_top10_gate"].agg(["sum", "mean", "count"]).sort_values("sum")
    drag_rows = [{"month": str(i), "d_top10_sum": float(r["sum"]), "d_top10_mean": float(r["mean"]), "n_days": int(r["count"])} for i, r in drag.iterrows()]

    fig, ax = plt.subplots(figsize=(11, 4.5))
    m25 = monthly[monthly["window"] == "2025_valid"]
    x = np.arange(len(m25))
    ax.bar(x, m25["d_top10_gate"], color="#c44536")
    ax.axhline(0, color="0.3", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(m25["month"], rotation=45, ha="right")
    ax.set_title("2025 monthly mean ΔTop10Spread (B-gate sort_values, universe EW)")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "monthly_2025_top10_gate.png", dpi=140)
    plt.close(fig)

    with PARAMS_PKL.open("rb") as f:
        model = pickle.load(f)
    booster = getattr(model, "model", model)
    gains = np.asarray(booster.feature_importance(importance_type="gain"), dtype=float)
    col183 = float(gains[183]) if len(gains) > 183 else float("nan")
    order = np.argsort(-gains)
    rank183 = int(np.where(order == 183)[0][0] + 1) if len(gains) > 183 else None
    fi = {
        "n_features": int(len(gains)),
        "column_183_gain": col183,
        "column_183_share": float(col183 / gains.sum()) if gains.sum() else None,
        "column_183_rank": rank183,
        "note": "inject_feature appends MAXRET20_ANTI_RANK as the last feature; LightGBM Column_183 is 0-based last of 184.",
        "median_gain": float(np.median(gains)),
        "mean_gain": float(np.mean(gains)),
    }
    payload = {
        "window_stats": window_stats,
        "top10_drag_2025_months_gate": drag_rows,
        "feature_importance_column_183": fi,
        "frozen_match_note": "d_top10_gate should match pred_pair verdict; d_top10_det uses score desc, instrument asc mergesort.",
    }
    (OUT / "top10_align.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(json.dumps(payload, indent=2, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
