# -*- coding: utf-8 -*-
"""T5-MXR1 pseudo-experiment 1: constrain control Top10 by MAXRET20_ANTI_RANK.

Read-only. No retrain, no PortAna, no pred write-back. Fail-closed if out-dir exists.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import host_env  # noqa: F401
import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
REPO = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from diag_pred_pair import load_labels, load_pred, moving_block_bootstrap_ci  # noqa: E402

LABEL = "Ref($close,-2)/Ref($close,-1)-1"
FEATURE = "MAXRET20_ANTI_RANK"
TOPK = 10
SIDECAR_SHA = "27320f8b7f6de3854802f97325f682039732470ce387f21bc9cd6c3083b7b348"
PROVIDER = r"C:/Users/wangc/.qlib/qlib_data/my_data"
SEED = 20260919
BLOCK = 5
BOOT = 10000
WINDOWS = (("2025_valid", "2025-01-03", "2025-12-31"), ("2026_oos", "2026-01-01", "2026-09-14"))
FROZEN_LGB = {
    "2025_valid": {"d_top10": -5.260264777101273e-5, "top10_ctrl": 0.005374208280541511},
    "2026_oos": {"d_top10": 4.921033324056564e-4, "top10_ctrl": 0.0004734034490215002},
}
OUT = REPO / "exports" / "analysis" / "t5_mxr1_20260918" / "pseudo1_top10_constrain_20260919"
INBOX = Path(r"D:\PycharmProjects\_agent_inbox\t5-mxr1-pseudo1")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def json_safe(v):
    if isinstance(v, dict):
        return {str(k): json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [json_safe(x) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        x = float(v)
        return x if math.isfinite(x) else None
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (pd.Timestamp, datetime)):
        return str(v)
    return v


def common_pair(ctrl: pd.DataFrame, cand: pd.DataFrame, labels: pd.DataFrame, start: str, end: str):
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    lab = labels[(labels["datetime"] >= s) & (labels["datetime"] <= e)]
    c0 = ctrl[(ctrl["datetime"] >= s) & (ctrl["datetime"] <= e)]
    c1 = cand[(cand["datetime"] >= s) & (cand["datetime"] <= e)]
    m0 = c0.merge(lab, on=["datetime", "instrument"], how="inner")
    m1 = c1.merge(lab, on=["datetime", "instrument"], how="inner")
    keys = set(zip(m0["datetime"], m0["instrument"])) & set(zip(m1["datetime"], m1["instrument"]))
    key_df = pd.DataFrame(list(keys), columns=["datetime", "instrument"])
    m0 = m0.merge(key_df, on=["datetime", "instrument"])
    return m0


def pick_t1_indices(feat: np.ndarray, median_anti: float, topk: int) -> tuple[np.ndarray, int]:
    """feat is already in control-score rank order (score desc, instrument asc).

    Phase 1: take names whose anti-rank is not strictly below the T0 median.
    Phase 2: if short, backfill remaining in score order preferring anti-rank >= median.
    Phase 3: if still short, relax and take the rest in score order.
    Returns (positional indices into the ranked array, n_relax).
    """
    n = int(feat.shape[0])
    if n < topk:
        return np.arange(n, dtype=np.int64), 0
    if not np.isfinite(median_anti):
        return np.arange(topk, dtype=np.int64), 0

    below = np.isfinite(feat) & (feat < median_anti)
    keep = np.flatnonzero(~below)
    if keep.size >= topk:
        return keep[:topk].astype(np.int64), 0

    selected = keep.tolist()
    remaining = np.flatnonzero(below)
    # Phase 2: prefer anti-rank >= median among leftovers (none of `below` qualify).
    prefer = [int(i) for i in remaining if np.isfinite(feat[i]) and feat[i] >= median_anti]
    rest = [int(i) for i in remaining if i not in prefer]
    n_relax = 0
    for i in prefer:
        selected.append(i)
        if len(selected) == topk:
            return np.asarray(selected, dtype=np.int64), n_relax
    for i in rest:
        selected.append(i)
        n_relax += 1
        if len(selected) == topk:
            break
    return np.asarray(selected, dtype=np.int64), n_relax


def analyze_days(df: pd.DataFrame, window: str) -> pd.DataFrame:
    rows = []
    for dt, g in df.groupby("datetime", sort=True):
        n = len(g)
        if n < TOPK:
            continue
        g = g.sort_values(["score", "instrument"], ascending=[False, True], kind="mergesort")
        inst = g["instrument"].to_numpy()
        feat = g[FEATURE].to_numpy(dtype=float)
        lab = g["label"].to_numpy(dtype=float)
        score = g["score"].to_numpy(dtype=float)

        t0_pos = np.arange(TOPK, dtype=np.int64)
        t0_feat = feat[t0_pos]
        median_anti = float(np.nanmedian(t0_feat))
        t1_pos, n_relax = pick_t1_indices(feat, median_anti, TOPK)

        univ = float(np.nanmean(lab))
        t0_lab = lab[t0_pos]
        t1_lab = lab[t1_pos]
        sp0 = float(np.nanmean(t0_lab) - univ)
        sp1 = float(np.nanmean(t1_lab) - univ)
        d_top10 = float(sp1 - sp0)

        s0 = set(inst[t0_pos])
        s1 = set(inst[t1_pos])
        inter = s0 & s1
        union = s0 | s1
        overlap = len(inter)
        added = s1 - s0
        dropped = s0 - s1
        add_mask = np.array([x in added for x in inst], dtype=bool)
        drop_mask = np.array([x in dropped for x in inst], dtype=bool)

        finite_lab = np.isfinite(lab)
        finite_score = np.isfinite(score)
        if int((finite_lab & finite_score).sum()) >= 4:
            ric = float(pd.Series(score).corr(pd.Series(lab), method="spearman"))
        else:
            ric = float("nan")

        n_t0_below = int(np.sum(np.isfinite(t0_feat) & (t0_feat < median_anti))) if np.isfinite(median_anti) else 0
        t1_feat = feat[t1_pos]
        n_t1_below = int(np.sum(np.isfinite(t1_feat) & (t1_feat < median_anti))) if np.isfinite(median_anti) else 0

        rows.append(
            {
                "datetime": pd.Timestamp(dt),
                "window": window,
                "n": int(n),
                "n_label": int(np.isfinite(lab).sum()),
                "rankic_ctrl": ric,
                "top10_t0": sp0,
                "top10_t1": sp1,
                "d_top10": d_top10,
                "median_anti": median_anti if np.isfinite(median_anti) else float("nan"),
                "n_relax": int(n_relax),
                "relaxed": int(n_relax > 0),
                "overlap": int(overlap),
                "jaccard": float(overlap / len(union)) if union else float("nan"),
                "turnover": float((TOPK - overlap) / TOPK),
                "n_swapped": int(len(added)),
                "n_t0_below_median": n_t0_below,
                "n_t1_below_median": n_t1_below,
                "t0_feat": float(np.nanmean(t0_feat)),
                "t1_feat": float(np.nanmean(t1_feat)),
                "univ_feat": float(np.nanmean(feat)),
                "added_feat": float(np.nanmean(feat[add_mask])) if added else float("nan"),
                "dropped_feat": float(np.nanmean(feat[drop_mask])) if dropped else float("nan"),
                "added_label": float(np.nanmean(lab[add_mask])) if added else float("nan"),
                "dropped_label": float(np.nanmean(lab[drop_mask])) if dropped else float("nan"),
                "kth_score": float(score[TOPK - 1]),
                "n_at_kth": int(np.sum(score == score[TOPK - 1])),
            }
        )
    return pd.DataFrame(rows)


def summarize_window(d: pd.DataFrame, name: str, start: str, end: str) -> dict:
    d_fin = d[np.isfinite(d["d_top10"])]
    ric = d[np.isfinite(d["rankic_ctrl"])]
    pe, lo, hi = moving_block_bootstrap_ci(
        d_fin["d_top10"].to_numpy(), block_days=BLOCK, reps=BOOT, seed=SEED
    )
    months = []
    if len(d_fin):
        tmp = d_fin.copy()
        tmp["month"] = tmp["datetime"].dt.to_period("M").astype(str)
        for month, g in tmp.groupby("month", sort=True):
            months.append(
                {
                    "month": month,
                    "n_days": int(len(g)),
                    "d_top10": float(g["d_top10"].mean()),
                    "d_top10_sum": float(g["d_top10"].sum()),
                    "d_top10_share_neg": float((g["d_top10"] < 0).mean()),
                    "turnover": float(g["turnover"].mean()),
                    "n_relax_mean": float(g["n_relax"].mean()),
                    "share_relaxed": float(g["relaxed"].mean()),
                }
            )
    qmap = {}
    if len(d_fin):
        q = d_fin.groupby(d_fin["datetime"].dt.to_period("Q"))["d_top10"].mean()
        qmap = {str(k): float(v) for k, v in q.items()}
    frozen = FROZEN_LGB[name]
    mean_d = float(d_fin["d_top10"].mean()) if len(d_fin) else float("nan")
    return {
        "start": start,
        "end": end,
        "n_days_calendar": int(len(d)),
        "n_days_top10": int(len(d_fin)),
        "n_days_rankic": int(len(ric)),
        "n_rows_mean": float(d["n"].mean()) if len(d) else float("nan"),
        "rankic_ctrl": float(ric["rankic_ctrl"].mean()) if len(ric) else float("nan"),
        "top10_t0": float(d_fin["top10_t0"].mean()) if len(d_fin) else float("nan"),
        "top10_t1": float(d_fin["top10_t1"].mean()) if len(d_fin) else float("nan"),
        "d_top10": mean_d,
        "d_top10_share_pos": float((d_fin["d_top10"] > 0).mean()) if len(d_fin) else float("nan"),
        "d_top10_share_neg": float((d_fin["d_top10"] < 0).mean()) if len(d_fin) else float("nan"),
        "d_top10_share_zero": float((d_fin["d_top10"] == 0).mean()) if len(d_fin) else float("nan"),
        "bootstrap": {"point": pe, "lo": lo, "hi": hi, "block": BLOCK, "reps": BOOT, "seed": SEED},
        "jaccard_mean": float(d_fin["jaccard"].mean()) if len(d_fin) else float("nan"),
        "turnover_mean": float(d_fin["turnover"].mean()) if len(d_fin) else float("nan"),
        "overlap_mean": float(d_fin["overlap"].mean()) if len(d_fin) else float("nan"),
        "share_identical": float((d_fin["overlap"] == TOPK).mean()) if len(d_fin) else float("nan"),
        "n_relax_sum": int(d["n_relax"].sum()) if len(d) else 0,
        "n_relax_days": int(d["relaxed"].sum()) if len(d) else 0,
        "share_relaxed": float(d["relaxed"].mean()) if len(d) else float("nan"),
        "n_t0_below_median_mean": float(d_fin["n_t0_below_median"].mean()) if len(d_fin) else float("nan"),
        "t0_feat": float(d_fin["t0_feat"].mean()) if len(d_fin) else float("nan"),
        "t1_feat": float(d_fin["t1_feat"].mean()) if len(d_fin) else float("nan"),
        "univ_feat": float(d_fin["univ_feat"].mean()) if len(d_fin) else float("nan"),
        "added_feat": float(d_fin["added_feat"].mean()) if len(d_fin) else float("nan"),
        "dropped_feat": float(d_fin["dropped_feat"].mean()) if len(d_fin) else float("nan"),
        "added_label": float(d_fin["added_label"].mean()) if len(d_fin) else float("nan"),
        "dropped_label": float(d_fin["dropped_label"].mean()) if len(d_fin) else float("nan"),
        "swap_label_gap": float((d_fin["added_label"] - d_fin["dropped_label"]).mean()) if len(d_fin) else float("nan"),
        "mean_n_at_kth": float(d["n_at_kth"].mean()) if len(d) else float("nan"),
        "share_kth_tied": float((d["n_at_kth"] > 1).mean()) if len(d) else float("nan"),
        "t0_vs_frozen_ctrl": {
            "top10_t0": float(d_fin["top10_t0"].mean()) if len(d_fin) else float("nan"),
            "frozen_top10_ctrl": frozen["top10_ctrl"],
            "abs_diff": abs(float(d_fin["top10_t0"].mean()) - frozen["top10_ctrl"]) if len(d_fin) else float("nan"),
        },
        "lgb_frozen_d_top10": frozen["d_top10"],
        "quarters": qmap,
        "months": months,
    }


def fmt(x, nd=6):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "NA"
    ax = abs(float(x))
    if ax != 0 and (ax < 1e-3 or ax >= 1e3):
        return f"{x:.3e}"
    return f"{x:.{nd}f}"


def write_report(out: Path, payload: dict) -> None:
    w25 = payload["windows"]["2025_valid"]
    w26 = payload["windows"]["2026_oos"]
    d25 = w25["d_top10"]
    supported = bool(d25 > 0)
    if supported:
        verdict = "支持「头部换入大涨股是 2025 否决主因」"
        verdict_why = (
            f"2025 mean(ΔTop10Spread of T1 vs T0) = {d25:.6e} > 0，"
            f"相对冻结候选 LGB 的 {FROZEN_LGB['2025_valid']['d_top10']:.3e} 已翻到非负。"
        )
    else:
        verdict = "削弱该假设"
        verdict_why = (
            f"2025 mean(ΔTop10Spread of T1 vs T0) = {d25:.6e} ≤ 0，"
            "不满足预注册的支持门槛。"
        )

    lines = []
    a = lines.append
    a("# T5-MXR1 伪实验1：Top10 换入约束")
    a("")
    a(f"**结论先行：** {verdict}。{verdict_why}")
    a("")
    a("2026 ΔTop10 与 CI 只报告、**不**改 2025 结论。本实验**不能**推翻 `MAXRET_MODEL_NO_TRANSFER`（那是 LGB 重训 B 门）；它只回答头部约束伪实验。未重训、未改 sidecar / 特征 / 10/3、未写回 pred、未跑 PortAna/BT、未开伪实验 2。")
    a("")
    a("---")
    a("")
    a("## 0. 范围与冻结")
    a("")
    a("| 项 | 值 |")
    a("|---|---|")
    a(f"| 输出目录 | `{out}` |")
    a(f"| sidecar SHA-256 | `{payload['sidecar_sha256']}` |")
    a("| 对照 / 候选（宇宙对齐，候选分数不参与 T1） | `8a061ea4` / `d03e8ffc`（只读） |")
    a("| 标签 | `Ref($close,-2)/Ref($close,-1)-1` |")
    a("| Top10Spread | 等权 Top10 − 共同宇宙等权；**禁止 Top-Bottom** |")
    a("| T0 | 对照 score 降序，ties 用 instrument 字典序、mergesort |")
    a("| T1 | 跳过 anti-rank **严格低于**当日 T0 中位数的票；凑不满则按 score 回填，优先 ≥ 中位数，仍不够再放宽 |")
    a(f"| bootstrap | moving-block，block={BLOCK}，reps={BOOT}，seed=`{SEED}` |")
    a("| 窗 | 2025-01-03～12-31；2026-01-01～09-14 |")
    a("")
    a(f"T0 Top10Spread 与冻结 B 门对照：2025 abs_diff={w25['t0_vs_frozen_ctrl']['abs_diff']:.3e}；2026 abs_diff={w26['t0_vs_frozen_ctrl']['abs_diff']:.3e}（第 10 名 score 无并列，det 排序与 B 门 quicksort 一致）。")
    a("")
    a("## 1. 主结果")
    a("")
    a("| 窗 | 日数 Top10 | RankIC 对照 | Top10 T0 | Top10 T1 | **ΔTop10 T1−T0** | 95% CI | 日为正比例 | 冻结 LGB ΔTop10 |")
    a("|---|---:|---:|---:|---:|---:|---|---:|---:|")
    for name, w in (("2025_valid", w25), ("2026_oos", w26)):
        ci = w["bootstrap"]
        a(
            f"| {name} | {w['n_days_top10']} | {fmt(w['rankic_ctrl'])} | {fmt(w['top10_t0'])} | {fmt(w['top10_t1'])} | **{fmt(w['d_top10'])}** | [{fmt(ci['lo'])}, {fmt(ci['hi'])}] | {w['d_top10_share_pos']:.1%} | {fmt(w['lgb_frozen_d_top10'])} |"
        )
    a("")
    a("Δ 的分母是对照共同宇宙等权次日 label，与 B 门同一套。RankIC 仍是对照全截面 Spearman，本实验主要看 Top10。")
    a("")
    a("## 2. 头部约束做了什么")
    a("")
    a("| 窗 | Jaccard(T0,T1) | 重叠只数 | 换手 | T0 低于中位数只数 | 放宽日占比 | 放宽只数合计 | T0 特征均值 | T1 特征均值 | 换入特征 | 换出特征 | 换入−换出 label |")
    a("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name, w in (("2025_valid", w25), ("2026_oos", w26)):
        a(
            f"| {name} | {w['jaccard_mean']:.3f} | {w['overlap_mean']:.2f} | {w['turnover_mean']:.3f} | {w['n_t0_below_median_mean']:.2f} | {w['share_relaxed']:.1%} | {w['n_relax_sum']} | {fmt(w['t0_feat'], 3)} | {fmt(w['t1_feat'], 3)} | {fmt(w['added_feat'], 3)} | {fmt(w['dropped_feat'], 3)} | {fmt(w['swap_label_gap'])} |"
        )
    a("")
    a("`MAXRET20_ANTI_RANK` 高 = 近 20 日没有大涨。T1 把 T0 里低于当日中位数的低 anti-rank 票换成分数稍低、anti-rank 不低于中位数的票。")
    a("")
    a("## 3. 2025 月度 ΔTop10Spread（T1−T0）")
    a("")
    a("| 月 | 日数 | mean Δ | sum Δ | 日为负比例 | 换手 |")
    a("|---|---:|---:|---:|---:|---:|")
    months_sorted = sorted(w25["months"], key=lambda r: r["d_top10_sum"])
    for r in months_sorted:
        a(
            f"| {r['month']} | {r['n_days']} | {fmt(r['d_top10'])} | {fmt(r['d_top10_sum'])} | {r['d_top10_share_neg']:.0%} | {r['turnover']:.3f} |"
        )
    a("")
    a("季度 mean ΔTop10：")
    a("")
    a("| 季 | mean ΔTop10 |")
    a("|---|---:|")
    for q, v in w25["quarters"].items():
        a(f"| {q} | {fmt(v)} |")
    for q, v in w26["quarters"].items():
        a(f"| {q} | {fmt(v)} |")
    a("")
    a("## 4. 判决（预注册门槛，未改）")
    a("")
    a(f"- **{verdict}**")
    a(f"- {verdict_why}")
    a(
        f"- 2026 mean Δ = {fmt(w26['d_top10'])}，CI [{fmt(w26['bootstrap']['lo'])}, {fmt(w26['bootstrap']['hi'])}]；不据此改 2025 结论。"
    )
    a("- 终态标签仍是 `MAXRET_MODEL_NO_TRANSFER`。本伪实验没有重训 LGB，不能推翻 B 门。")
    a("")
    a("## 5. 未做")
    a("")
    a("- 未重训、未改 sidecar / 特征定义 / 方向 / 列、未扫 seed/阈值/窗。")
    a("- 未跑 PortAna / BT，未改 10/3，未写回 pred。")
    a("- **未开伪实验 2**（残差直接合成）。")
    a("")
    a("## 产物")
    a("")
    a(f"- `{out / 'REPORT.md'}`")
    a(f"- `{out / 'daily_metrics.csv'}`")
    a(f"- `{out / 'summary.json'}`")
    a("")
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_result_md(payload: dict, out: Path) -> None:
    w25 = payload["windows"]["2025_valid"]
    w26 = payload["windows"]["2026_oos"]
    d25 = w25["d_top10"]
    supported = bool(d25 > 0)
    word = "支持" if supported else "削弱"
    INBOX.mkdir(parents=True, exist_ok=True)
    text = (
        "# T5-MXR1 伪实验1 RESULT\n\n"
        f"- **report**: `{out / 'REPORT.md'}`\n"
        f"- **daily / summary**: `{out / 'daily_metrics.csv'}` ； `{out / 'summary.json'}`\n"
        f"- sidecar SHA-256 `{payload['sidecar_sha256']}`；线上 pred `8a061ea4` / 10/3 未动；未开伪实验 2\n\n"
        f"头部 anti-rank 中位数约束的 T1 相对对照 Top10 T0：2025 mean ΔTop10Spread={d25:.6e}（{' > 0，支持' if supported else ' ≤ 0，削弱'}「换入大涨股是 2025 否决主因」），"
        f"bootstrap 95% CI [{w25['bootstrap']['lo']:.3e}, {w25['bootstrap']['hi']:.3e}]；"
        f"对比冻结 LGB 2025 ΔTop10={FROZEN_LGB['2025_valid']['d_top10']:.3e}。"
        f"2026 mean Δ={w26['d_top10']:.6e}，CI [{w26['bootstrap']['lo']:.3e}, {w26['bootstrap']['hi']:.3e}]，不改 2025 结论。"
        f"本实验不能推翻 `MAXRET_MODEL_NO_TRANSFER`。判决：**{word}该假设**。\n"
    )
    (INBOX / "RESULT.md").write_text(text, encoding="utf-8")


def main() -> int:
    if OUT.exists():
        msg = f"fail-closed: out-dir already exists: {OUT}"
        print(f"[FAIL] {msg}", flush=True)
        INBOX.mkdir(parents=True, exist_ok=True)
        (INBOX / "RESULT.md").write_text(
            "# T5-MXR1 伪实验1 RESULT\n\n"
            f"BLOCKED: {msg}\n\n"
            "未改线上 pred / sidecar / 10/3；未开伪实验 2。\n",
            encoding="utf-8",
        )
        return 2
    OUT.mkdir(parents=True, exist_ok=False)
    print(f"[out] {OUT}", flush=True)

    sidecar = REPO / "exports" / "analysis" / "t5_mxr1_20260918" / "sidecar" / "MAXRET20_ANTI_RANK.parquet"
    got = sha256_file(sidecar)
    if got.lower() != SIDECAR_SHA.lower():
        raise RuntimeError(f"sidecar sha mismatch {got}")
    print(f"[sidecar] sha ok {got}", flush=True)

    ctrl25 = load_pred(SCRIPT_DIR / "预测结果_8a061ea4_2025valid.csv")
    cand25 = load_pred(REPO / "exports" / "analysis" / "t5_mxr1_20260918" / "model" / "pred_2025.csv")
    ctrl26_path = REPO / "exports" / "analysis" / "t5_mxr1_20260918" / "control_pred_2026_8a061ea4.csv"
    if not ctrl26_path.is_file():
        raise RuntimeError("control 2026 csv missing; refused to export from recorder in this run")
    ctrl26 = load_pred(ctrl26_path)
    cand26 = load_pred(REPO / "exports" / "analysis" / "t5_mxr1_20260918" / "model" / "pred_2026.csv")
    print(f"[pred] ctrl25={len(ctrl25)} cand25={len(cand25)} ctrl26={len(ctrl26)} cand26={len(cand26)}", flush=True)

    import qlib
    from qlib.constant import REG_CN

    print("[init] qlib", flush=True)
    qlib.init(provider_uri=PROVIDER, region=REG_CN, kernels=1)
    inst = sorted(set(ctrl25["instrument"]) | set(cand25["instrument"]) | set(ctrl26["instrument"]) | set(cand26["instrument"]))
    print(f"[labels] n_inst={len(inst)} 2025-01-03..2026-09-14", flush=True)
    labels = load_labels(inst, "2025-01-03", "2026-09-14", LABEL)
    print(f"[labels] rows={len(labels)}", flush=True)

    side = pd.read_parquet(sidecar, columns=["datetime", "instrument", FEATURE])
    side["datetime"] = pd.to_datetime(side["datetime"]).dt.normalize()
    side["instrument"] = side["instrument"].astype(str)
    side = side[side["datetime"] >= pd.Timestamp("2025-01-01")]

    frames = []
    window_payload = {}
    for name, a, b in WINDOWS:
        ctrl = ctrl25 if name.startswith("2025") else ctrl26
        cand = cand25 if name.startswith("2025") else cand26
        pair = common_pair(ctrl, cand, labels, a, b)
        pair = pair.merge(side, on=["datetime", "instrument"], how="left")
        print(f"[window] {name} rows={len(pair)} days={pair['datetime'].nunique()}", flush=True)
        daily = analyze_days(pair, name)
        print(f"[daily] {name} n={len(daily)}", flush=True)
        window_payload[name] = summarize_window(daily, name, a, b)
        frames.append(daily)

    daily_all = pd.concat(frames, ignore_index=True)
    daily_all.to_csv(OUT / "daily_metrics.csv", index=False, encoding="utf-8")

    d25 = window_payload["2025_valid"]["d_top10"]
    supported = bool(d25 > 0)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "out_dir": str(OUT),
        "sidecar_sha256": got,
        "label": LABEL,
        "feature": FEATURE,
        "top10_spread_vs": "common-universe-equal-weight",
        "t0_sort": "score desc, instrument asc, mergesort",
        "t1_rule": "skip MAXRET20_ANTI_RANK strictly below T0 median; backfill by score preferring >= median; else relax",
        "bootstrap": {"block": BLOCK, "reps": BOOT, "seed": SEED},
        "control_recorder": "8a061ea428e04bb3a199a485ade49d0e",
        "candidate_recorder": "d03e8ffcb6d14668b4d6fc2b192bc8c7",
        "online_untouched": True,
        "no_retrain": True,
        "no_portana": True,
        "no_pseudo2": True,
        "hypothesis_supported": supported,
        "verdict_2025": "支持「头部换入大涨股是 2025 否决主因」" if supported else "削弱该假设",
        "cannot_overturn": "MAXRET_MODEL_NO_TRANSFER",
        "windows": window_payload,
    }
    (OUT / "summary.json").write_text(json.dumps(json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(OUT, payload)
    write_result_md(payload, OUT)
    print(json.dumps({"verdict": payload["verdict_2025"], "windows": json_safe(window_payload)}, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
