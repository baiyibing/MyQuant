# -*- coding: utf-8 -*-
"""Recompute Top10 sets on the exact B-gate common sample (do not recreate out-dir)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import host_env  # noqa: F401
import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
REPO = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
from diag_pred_pair import LABEL, daily_rankic, daily_top10_spread, load_labels, load_pred  # noqa: E402

OUT = REPO / "exports" / "analysis" / "t5_wrd1_20260918" / "b_diag_20260919"
FEATURE = "BROKER_WR_GAP"
WINDOWS = (("2025_valid", "2025-01-03", "2025-12-31"), ("2026_oos", "2026-01-01", "2026-09-14"))
PROVIDER = r"C:/Users/wangc/.qlib/qlib_data/my_data"
SIDECAR = REPO / "exports" / "analysis" / "t5_wrd1_20260918" / "sidecar" / "BROKER_WR_GAP.parquet"


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


def main() -> int:
    import qlib
    from qlib.constant import REG_CN

    ctrl25 = load_pred(SCRIPT_DIR / "预测结果_8a061ea4_2025valid.csv")
    cand25 = load_pred(REPO / "exports" / "analysis" / "t5_wrd1_20260918" / "model" / "pred_2025.csv")
    ctrl26 = load_pred(REPO / "exports" / "analysis" / "t5_wrd1_20260918" / "control_pred_2026_8a061ea4.csv")
    cand26 = load_pred(REPO / "exports" / "analysis" / "t5_wrd1_20260918" / "model" / "pred_2026.csv")
    qlib.init(provider_uri=PROVIDER, region=REG_CN, kernels=1)
    inst = sorted(set(ctrl25["instrument"]) | set(cand25["instrument"]) | set(ctrl26["instrument"]) | set(cand26["instrument"]))
    labels = load_labels(inst, "2025-01-03", "2026-09-14", LABEL)
    side = pd.read_parquet(SIDECAR, columns=["datetime", "instrument", FEATURE])
    side["datetime"] = pd.to_datetime(side["datetime"]).dt.normalize()
    side["instrument"] = side["instrument"].astype(str)

    frozen = json.loads((REPO / "exports" / "analysis" / "t5_wrd1_20260918" / "pred_pair" / "verdict.json").read_text(encoding="utf-8"))
    rows = []
    swap_rows = []
    win_stats = {}
    for i, (name, start, end) in enumerate(WINDOWS):
        ctrl = ctrl25 if i == 0 else ctrl26
        cand = cand25 if i == 0 else cand26
        m0, m1 = common_pair(ctrl, cand, labels, start, end)
        m0 = m0.merge(side, on=["datetime", "instrument"], how="left")
        m1 = m1.merge(side, on=["datetime", "instrument"], how="left")
        ric0 = daily_rankic(m0)
        ric1 = daily_rankic(m1)
        tb0 = daily_top10_spread(m0, 10)
        tb1 = daily_top10_spread(m1, 10)
        fw = next(w for w in frozen["windows"] if w["window"] == name)
        if abs(float(tb1.mean() - tb0.mean()) - fw["top10_delta"]) > 1e-18:
            raise RuntimeError(f"{name} Top-Bottom mismatch vs frozen")
        pair = m0.merge(
            m1[["datetime", "instrument", "score"]].rename(columns={"score": "score_cand"}),
            on=["datetime", "instrument"],
        ).rename(columns={"score": "score_ctrl"})
        pair["feat_pct"] = pair.groupby("datetime")[FEATURE].rank(method="average", pct=True)
        m0g = {dt: g for dt, g in m0.groupby("datetime", sort=True)}
        m1g = {dt: g for dt, g in m1.groupby("datetime", sort=True)}
        for dt, g in pair.groupby("datetime", sort=True):
            if len(g) < 20:
                continue
            # Rank each arm independently — same sort as frozen B-gate daily_top10_spread.
            a0 = m0g[dt].sort_values("score", ascending=False)
            a1 = m1g[dt].sort_values("score", ascending=False)
            t0, t1 = a0.head(10), a1.head(10)
            b0, b1 = a0.tail(10), a1.tail(10)
            univ = float(g["label"].mean())
            s0, s1 = set(t0["instrument"]), set(t1["instrument"])
            inter = s0 & s1
            added, dropped = s1 - s0, s0 - s1
            add_g = g[g["instrument"].isin(added)]
            drop_g = g[g["instrument"].isin(dropped)]
            kth0 = float(t0["score"].iloc[-1])
            kth1 = float(t1["score"].iloc[-1])
            rows.append(
                {
                    "datetime": pd.Timestamp(dt),
                    "window": name,
                    "n": int(len(g)),
                    "rankic_ctrl": float(g["score_ctrl"].corr(g["label"], method="spearman")),
                    "rankic_cand": float(g["score_cand"].corr(g["label"], method="spearman")),
                    "d_rankic": float(g["score_cand"].corr(g["label"], method="spearman") - g["score_ctrl"].corr(g["label"], method="spearman")),
                    "top10_univ_ctrl": float(t0["label"].mean() - univ),
                    "top10_univ_cand": float(t1["label"].mean() - univ),
                    "d_top10_univ": float(t1["label"].mean() - t0["label"].mean()),
                    "top10_tb_ctrl": float(t0["label"].mean() - b0["label"].mean()),
                    "top10_tb_cand": float(t1["label"].mean() - b1["label"].mean()),
                    "d_top10_tb": float((t1["label"].mean() - b1["label"].mean()) - (t0["label"].mean() - b0["label"].mean())),
                    "d_top_mean": float(t1["label"].mean() - t0["label"].mean()),
                    "d_bot_mean": float(b1["label"].mean() - b0["label"].mean()),
                    "overlap": len(inter),
                    "jaccard": len(inter) / len(s0 | s1),
                    "turnover": (10 - len(inter)) / 10,
                    "n_swapped": len(added),
                    "n_at_kth_ctrl": int((g["score_ctrl"] == kth0).sum()),
                    "n_at_kth_cand": int((g["score_cand"] == kth1).sum()),
                    "top10_feat_ctrl": float(t0[FEATURE].mean()),
                    "top10_feat_cand": float(t1[FEATURE].mean()),
                    "univ_feat": float(g[FEATURE].mean()),
                    "top10_feat_pct_ctrl": float(g.loc[g["instrument"].isin(s0), "feat_pct"].mean()),
                    "top10_feat_pct_cand": float(g.loc[g["instrument"].isin(s1), "feat_pct"].mean()),
                    "added_feat": float(add_g[FEATURE].mean()) if len(add_g) else np.nan,
                    "dropped_feat": float(drop_g[FEATURE].mean()) if len(drop_g) else np.nan,
                    "added_feat_pct": float(add_g["feat_pct"].mean()) if len(add_g) else np.nan,
                    "dropped_feat_pct": float(drop_g["feat_pct"].mean()) if len(drop_g) else np.nan,
                    "added_label": float(add_g["label"].mean()) if len(add_g) else np.nan,
                    "dropped_label": float(drop_g["label"].mean()) if len(drop_g) else np.nan,
                    "swap_label_gap": float(add_g["label"].mean() - drop_g["label"].mean()) if len(add_g) and len(drop_g) else np.nan,
                    "swap_feat_pct_gap": float(add_g["feat_pct"].mean() - drop_g["feat_pct"].mean()) if len(add_g) and len(drop_g) else np.nan,
                    "added_share_feat_below_med": float((add_g["feat_pct"] < 0.5).mean()) if len(add_g) else np.nan,
                }
            )
            for inst_i in sorted(added):
                r = g.loc[g["instrument"] == inst_i].iloc[0]
                swap_rows.append({"datetime": pd.Timestamp(dt), "window": name, "instrument": inst_i, "direction": "in", FEATURE: r[FEATURE], "feat_pct": r["feat_pct"], "label": r["label"]})
            for inst_i in sorted(dropped):
                r = g.loc[g["instrument"] == inst_i].iloc[0]
                swap_rows.append({"datetime": pd.Timestamp(dt), "window": name, "instrument": inst_i, "direction": "out", FEATURE: r[FEATURE], "feat_pct": r["feat_pct"], "label": r["label"]})

        d = pd.DataFrame([r for r in rows if r["window"] == name])
        has = d["n_swapped"] > 0
        win_stats[name] = {
            "n_days": int(len(d)),
            "n_common_rows": int(len(m0)),
            "rankic_ctrl": float(ric0.mean()),
            "rankic_cand": float(ric1.mean()),
            "d_rankic": float(ric1.mean() - ric0.mean()),
            "top10_tb_ctrl": float(tb0.mean()),
            "top10_tb_cand": float(tb1.mean()),
            "d_top10_tb": float(tb1.mean() - tb0.mean()),
            "d_top10_tb_frozen": fw["top10_delta"],
            "tb_match_frozen": bool(abs(float(tb1.mean() - tb0.mean()) - fw["top10_delta"]) < 1e-15),
            "top10_univ_ctrl": float(d["top10_univ_ctrl"].mean()),
            "top10_univ_cand": float(d["top10_univ_cand"].mean()),
            "d_top10_univ": float(d["d_top10_univ"].mean()),
            "d_top_mean": float(d["d_top_mean"].mean()),
            "d_bot_mean": float(d["d_bot_mean"].mean()),
            "jaccard_mean": float(d["jaccard"].mean()),
            "jaccard_median": float(d["jaccard"].median()),
            "turnover_mean": float(d["turnover"].mean()),
            "overlap_mean": float(d["overlap"].mean()),
            "share_identical": float((d["overlap"] == 10).mean()),
            "share_jaccard_ge_0_8": float((d["jaccard"] >= 0.8).mean()),
            "share_kth_tied_ctrl": float((d["n_at_kth_ctrl"] > 1).mean()),
            "mean_n_at_kth_ctrl": float(d["n_at_kth_ctrl"].mean()),
            "top10_feat_ctrl": float(d["top10_feat_ctrl"].mean()),
            "top10_feat_cand": float(d["top10_feat_cand"].mean()),
            "d_top10_feat": float((d["top10_feat_cand"] - d["top10_feat_ctrl"]).mean()),
            "top10_feat_pct_ctrl": float(d["top10_feat_pct_ctrl"].mean()),
            "top10_feat_pct_cand": float(d["top10_feat_pct_cand"].mean()),
            "univ_feat": float(d["univ_feat"].mean()),
            "added_feat": float(d.loc[has, "added_feat"].mean()) if has.any() else None,
            "dropped_feat": float(d.loc[has, "dropped_feat"].mean()) if has.any() else None,
            "added_feat_pct": float(d.loc[has, "added_feat_pct"].mean()) if has.any() else None,
            "dropped_feat_pct": float(d.loc[has, "dropped_feat_pct"].mean()) if has.any() else None,
            "added_label": float(d.loc[has, "added_label"].mean()) if has.any() else None,
            "dropped_label": float(d.loc[has, "dropped_label"].mean()) if has.any() else None,
            "swap_label_gap": float(d.loc[has, "swap_label_gap"].mean()) if has.any() else None,
            "swap_feat_pct_gap": float(d.loc[has, "swap_feat_pct_gap"].mean()) if has.any() else None,
            "added_share_feat_below_med": float(d.loc[has, "added_share_feat_below_med"].mean()) if has.any() else None,
            "d_top10_univ_share_neg": float((d["d_top10_univ"] < 0).mean()),
            "d_top10_tb_share_neg": float((d["d_top10_tb"] < 0).mean()),
            "d_rankic_share_pos": float((d["d_rankic"] > 0).mean()),
        }

    daily = pd.DataFrame(rows)
    daily.to_csv(OUT / "daily_top10_gate.csv", index=False, encoding="utf-8")
    swaps = pd.DataFrame(swap_rows)
    swaps.to_csv(OUT / "swaps_long_gate.csv", index=False, encoding="utf-8")
    daily["month"] = daily["datetime"].dt.to_period("M").astype(str)
    daily["quarter"] = daily["datetime"].dt.to_period("Q").astype(str)
    monthly = (
        daily.groupby(["window", "month"], sort=True)
        .agg(
            n_days=("datetime", "count"),
            d_rankic=("d_rankic", "mean"),
            d_top10_univ=("d_top10_univ", "mean"),
            d_top10_univ_sum=("d_top10_univ", "sum"),
            d_top10_tb=("d_top10_tb", "mean"),
            d_bot_mean=("d_bot_mean", "mean"),
            jaccard=("jaccard", "mean"),
            swap_label_gap=("swap_label_gap", "mean"),
            swap_feat_pct_gap=("swap_feat_pct_gap", "mean"),
            d_top10_univ_share_neg=("d_top10_univ", lambda s: float((s < 0).mean())),
        )
        .reset_index()
    )
    monthly.to_csv(OUT / "monthly_top10_gate.csv", index=False, encoding="utf-8")
    quarterly = (
        daily.groupby(["window", "quarter"], sort=True)
        .agg(
            n_days=("datetime", "count"),
            d_rankic=("d_rankic", "mean"),
            d_top10_univ=("d_top10_univ", "mean"),
            d_top10_tb=("d_top10_tb", "mean"),
            d_bot_mean=("d_bot_mean", "mean"),
            jaccard=("jaccard", "mean"),
            swap_label_gap=("swap_label_gap", "mean"),
        )
        .reset_index()
    )
    quarterly.to_csv(OUT / "quarterly_top10_gate.csv", index=False, encoding="utf-8")

    swap_sum = {}
    for name, _, _ in WINDOWS:
        sw = swaps[swaps["window"] == name]
        inn, outt = sw[sw["direction"] == "in"], sw[sw["direction"] == "out"]
        swap_sum[name] = {
            "n_in": int(len(inn)),
            "n_out": int(len(outt)),
            "in_feat_mean": float(inn[FEATURE].mean()) if len(inn) else None,
            "out_feat_mean": float(outt[FEATURE].mean()) if len(outt) else None,
            "in_feat_pct_mean": float(inn["feat_pct"].mean()) if len(inn) else None,
            "out_feat_pct_mean": float(outt["feat_pct"].mean()) if len(outt) else None,
            "in_feat_pct_median": float(inn["feat_pct"].median()) if len(inn) else None,
            "out_feat_pct_median": float(outt["feat_pct"].median()) if len(outt) else None,
            "in_label_mean": float(inn["label"].mean()) if len(inn) else None,
            "out_label_mean": float(outt["label"].mean()) if len(outt) else None,
            "in_share_feat_below_med": float((inn["feat_pct"] < 0.5).mean()) if len(inn) else None,
        }

    y26 = daily[daily["window"] == "2026_oos"]
    drag26 = (
        y26.groupby(y26["datetime"].dt.to_period("M"))["d_top10_univ"].sum().sort_values()
    )
    payload = {
        "windows": win_stats,
        "swaps_pooled": swap_sum,
        "top10_drag_2026_univ": [{"month": str(k), "d_top10_univ_sum": float(v)} for k, v in drag26.items()],
        "note": "Top10 ranked on B-gate common sample after inner-joining labels; Top-Bottom matches frozen verdict bit-exactly. Diagnostic spread is Top10 EW minus universe EW.",
    }
    (OUT / "top10_sets_summary.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload["windows"], indent=2, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
