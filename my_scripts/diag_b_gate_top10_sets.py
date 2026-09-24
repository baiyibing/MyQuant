# -*- coding: utf-8 -*-
"""B-gate Top10 sets (no label drop before ranking): Jaccard + MAXRET exposure."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import host_env  # noqa: F401
import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from diag_pred_pair import load_pred, load_labels  # noqa: E402

OUT = Path(r"D:\PycharmProjects\wt-myquant-pr80-t5-mxr1\exports\analysis\t5_mxr1_20260918\b_diag_20260919")
REPO = SCRIPT_DIR.parent
FEATURE = "MAXRET20_ANTI_RANK"
LABEL = "Ref($close,-2)/Ref($close,-1)-1"
WINDOWS = (("2025_valid", "2025-01-03", "2025-12-31"), ("2026_oos", "2026-01-01", "2026-09-14"))
PROVIDER = r"C:/Users/wangc/.qlib/qlib_data/my_data"


def main() -> int:
    import qlib
    from qlib.constant import REG_CN

    ctrl = pd.concat(
        [
            load_pred(SCRIPT_DIR / "预测结果_8a061ea4_2025valid.csv"),
            load_pred(REPO / "exports" / "analysis" / "t5_mxr1_20260918" / "control_pred_2026_8a061ea4.csv"),
        ],
        ignore_index=True,
    )
    cand = pd.concat(
        [
            load_pred(REPO / "exports" / "analysis" / "t5_mxr1_20260918" / "model" / "pred_2025.csv"),
            load_pred(REPO / "exports" / "analysis" / "t5_mxr1_20260918" / "model" / "pred_2026.csv"),
        ],
        ignore_index=True,
    )
    qlib.init(provider_uri=PROVIDER, region=REG_CN, kernels=1)
    inst = sorted(set(ctrl["instrument"]) | set(cand["instrument"]))
    labels = load_labels(inst, "2025-01-03", "2026-09-14", LABEL)
    side = pd.read_parquet(
        REPO / "exports" / "analysis" / "t5_mxr1_20260918" / "sidecar" / "MAXRET20_ANTI_RANK.parquet",
        columns=["datetime", "instrument", FEATURE],
    )
    side["datetime"] = pd.to_datetime(side["datetime"]).dt.normalize()
    side["instrument"] = side["instrument"].astype(str)
    side = side[side["datetime"] >= pd.Timestamp("2025-01-01")]

    pair = ctrl.merge(cand, on=["datetime", "instrument"], how="inner", suffixes=("_ctrl", "_cand"))
    pair = pair.merge(labels, on=["datetime", "instrument"], how="left")
    pair = pair.merge(side, on=["datetime", "instrument"], how="left")
    pair = pair[(pair["datetime"] >= pd.Timestamp("2025-01-03")) & (pair["datetime"] <= pd.Timestamp("2026-09-14"))]

    rows = []
    for dt, g in pair.groupby("datetime", sort=True):
        if len(g) < 10:
            continue
        t0 = g.nlargest(10, "score_ctrl", keep="first")
        t1 = g.nlargest(10, "score_cand", keep="first")
        s0, s1 = set(t0["instrument"]), set(t1["instrument"])
        inter = s0 & s1
        union = s0 | s1
        added = s1 - s0
        dropped = s0 - s1
        univ = float(g["label"].mean())
        sp0 = float(t0["label"].mean() - univ)
        sp1 = float(t1["label"].mean() - univ)
        ric0 = float(g["score_ctrl"].corr(g["label"], method="spearman"))
        ric1 = float(g["score_cand"].corr(g["label"], method="spearman"))
        add_g = g[g["instrument"].isin(added)]
        drop_g = g[g["instrument"].isin(dropped)]
        rows.append(
            {
                "datetime": pd.Timestamp(dt),
                "n": int(len(g)),
                "n_label": int(g["label"].notna().sum()),
                "rankic_ctrl": ric0,
                "rankic_cand": ric1,
                "d_rankic": ric1 - ric0,
                "d_top10": sp1 - sp0,
                "overlap": len(inter),
                "jaccard": len(inter) / len(union) if union else np.nan,
                "turnover": (10 - len(inter)) / 10,
                "top10_feat_ctrl": float(t0[FEATURE].mean()),
                "top10_feat_cand": float(t1[FEATURE].mean()),
                "univ_feat": float(g[FEATURE].mean()),
                "added_feat": float(add_g[FEATURE].mean()) if len(add_g) else np.nan,
                "dropped_feat": float(drop_g[FEATURE].mean()) if len(drop_g) else np.nan,
                "added_label": float(add_g["label"].mean()) if len(add_g) else np.nan,
                "dropped_label": float(drop_g["label"].mean()) if len(drop_g) else np.nan,
            }
        )
    daily = pd.DataFrame(rows)
    daily.to_csv(OUT / "daily_top10_sets.csv", index=False, encoding="utf-8")

    def win(ts):
        s = pd.Series(index=ts.index, dtype="object")
        for name, a, b in WINDOWS:
            s.loc[(ts >= pd.Timestamp(a)) & (ts <= pd.Timestamp(b))] = name
        return s

    daily["window"] = win(daily["datetime"])
    out = {"windows": {}, "nan_rankic_days": daily.loc[~np.isfinite(daily["d_rankic"]), ["datetime", "window", "n", "n_label"]].to_dict("records")}
    for name, _, _ in WINDOWS:
        d = daily[daily["window"] == name]
        out["windows"][name] = {
            "n_days": int(len(d)),
            "n_days_rankic_finite": int(np.isfinite(d["d_rankic"]).sum()),
            "jaccard_mean": float(d["jaccard"].mean()),
            "jaccard_median": float(d["jaccard"].median()),
            "turnover_mean": float(d["turnover"].mean()),
            "overlap_mean": float(d["overlap"].mean()),
            "share_identical": float((d["overlap"] == 10).mean()),
            "share_jaccard_ge_0_8": float((d["jaccard"] >= 0.8).mean()),
            "top10_feat_ctrl": float(d["top10_feat_ctrl"].mean()),
            "top10_feat_cand": float(d["top10_feat_cand"].mean()),
            "d_top10_feat": float((d["top10_feat_cand"] - d["top10_feat_ctrl"]).mean()),
            "univ_feat": float(d["univ_feat"].mean()),
            "added_feat": float(d["added_feat"].mean()),
            "dropped_feat": float(d["dropped_feat"].mean()),
            "added_label": float(d["added_label"].mean()),
            "dropped_label": float(d["dropped_label"].mean()),
            "swap_label_gap": float((d["added_label"] - d["dropped_label"]).mean()),
            "d_top10": float(d["d_top10"].mean()),
            "d_rankic": float(d["d_rankic"].mean()),
        }
    (OUT / "top10_sets_summary.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps(out, indent=2, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
