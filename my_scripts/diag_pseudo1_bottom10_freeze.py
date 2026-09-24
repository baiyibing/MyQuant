# -*- coding: utf-8 -*-
"""T5-WRD1 伪实验1：Bottom10 冻结（只读）。

每日保留候选 Top10，把 Bottom10 强制换成对照 Bottom10，重算冻结口径 Top−Bottom。
禁止重训 / PortAna / 写回 pred / 改 sidecar / 动 10/3。
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

LABEL = "Ref($close,-2)/Ref($close,-1)-1"
TOPK = 10
SIDECAR_SHA = "34453f4679ded0ba8233c16eee33c916e87d5eecca16fee15c7e5173424a6d65"
PROVIDER = r"C:/Users/wangc/.qlib/qlib_data/my_data"
WINDOWS = (("2025_valid", "2025-01-03", "2025-12-31"), ("2026_oos", "2026-01-01", "2026-09-14"))
CAND_RECORDER = "5ef339db2fdc4f56815edf78d17e3017"
CTRL_RECORDER = "8a061ea428e04bb3a199a485ade49d0e"
BOOT_BLOCK = 5
BOOT_REPS = 10_000
BOOT_SEED = 20260919
GIT_HEAD = "397c904"
FROZEN_D_TB_2026 = -3.401074e-4
FROZEN_D_UNIV_2026 = 5.90e-5
FROZEN_D_BOT_2026 = 4.0e-4
OUT_DIR = REPO / "exports" / "analysis" / "t5_wrd1_20260918" / "pseudo1_bottom10_freeze_20260919"
SIDECAR = REPO / "exports" / "analysis" / "t5_wrd1_20260918" / "sidecar" / "BROKER_WR_GAP.parquet"
FROZEN_VERDICT = REPO / "exports" / "analysis" / "t5_wrd1_20260918" / "pred_pair" / "verdict.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_pred(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    dt = cols.get("datetime") or cols.get("date")
    inst = cols.get("instrument") or cols.get("asset") or cols.get("symbol")
    score = cols.get("score") or cols.get("pred") or cols.get("prediction")
    if not (dt and inst and score):
        raise ValueError(f"pred columns missing in {path}: {df.columns.tolist()}")
    out = df[[dt, inst, score]].copy()
    out.columns = ["datetime", "instrument", "score"]
    out["datetime"] = pd.to_datetime(out["datetime"]).dt.normalize()
    out["instrument"] = out["instrument"].astype(str)
    out["score"] = pd.to_numeric(out["score"], errors="coerce")
    return out.dropna(subset=["score"])


def load_labels(instruments, start: str, end: str) -> pd.DataFrame:
    from qlib.data import D

    raw = D.features(list(instruments), [LABEL], start_time=start, end_time=end)
    if raw is None or raw.empty:
        raise RuntimeError(f"D.features empty for {start}:{end}")
    frame = raw.reset_index() if isinstance(raw.index, pd.MultiIndex) else raw.copy()
    if LABEL not in frame.columns:
        vals = [c for c in frame.columns if c not in {"datetime", "instrument"}]
        if len(vals) != 1:
            raise ValueError(f"unexpected label columns: {list(frame.columns)}")
        frame = frame.rename(columns={vals[0]: LABEL})
    out = frame.loc[:, ["datetime", "instrument", LABEL]].copy()
    out = out.rename(columns={LABEL: "label"})
    out["datetime"] = pd.to_datetime(out["datetime"]).dt.normalize()
    out["instrument"] = out["instrument"].astype(str)
    out["label"] = pd.to_numeric(out["label"], errors="coerce")
    return out


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


def pick_top_bot(g: pd.DataFrame, score_col: str, k: int = TOPK):
    """Top/Bottom k with instrument lexicographic tie-break (stable mergesort)."""
    ordered = g.sort_values([score_col, "instrument"], ascending=[False, True], kind="mergesort")
    return ordered.head(k), ordered.tail(k)


def common_pair(ctrl, cand, labels, start, end):
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    lab = labels[(labels["datetime"] >= s) & (labels["datetime"] <= e)]
    c0 = ctrl[(ctrl["datetime"] >= s) & (ctrl["datetime"] <= e)]
    c1 = cand[(cand["datetime"] >= s) & (cand["datetime"] <= e)]
    m0 = c0.merge(lab, on=["datetime", "instrument"], how="inner")
    m1 = c1.merge(lab, on=["datetime", "instrument"], how="inner")
    keys = set(zip(m0["datetime"], m0["instrument"])) & set(zip(m1["datetime"], m1["instrument"]))
    if not keys:
        raise RuntimeError(f"{start}:{end}: empty common sample")
    key_df = pd.DataFrame(list(keys), columns=["datetime", "instrument"])
    m0 = m0.merge(key_df, on=["datetime", "instrument"])
    m1 = m1.merge(key_df, on=["datetime", "instrument"])
    return m0, m1


def analyze_window(name: str, m0: pd.DataFrame, m1: pd.DataFrame) -> pd.DataFrame:
    pair = m0.merge(
        m1[["datetime", "instrument", "score"]].rename(columns={"score": "score_cand"}),
        on=["datetime", "instrument"],
    ).rename(columns={"score": "score_ctrl"})
    m0g = {dt: g for dt, g in m0.groupby("datetime", sort=True)}
    m1g = {dt: g for dt, g in m1.groupby("datetime", sort=True)}
    rows = []
    for dt, g in pair.groupby("datetime", sort=True):
        g = g.dropna(subset=["score_ctrl", "score_cand"]).copy()
        n = len(g)
        if n < TOPK * 2:
            continue
        # Rank each arm on the B-gate common sample (do not drop NaN labels before ranking).
        t0, b0 = pick_top_bot(m0g[dt], "score")
        t1, b1 = pick_top_bot(m1g[dt], "score")
        top0 = float(t0["label"].mean())
        top1 = float(t1["label"].mean())
        bot0 = float(b0["label"].mean())
        bot1 = float(b1["label"].mean())
        univ = float(g["label"].mean())
        spread_ctrl = top0 - bot0
        spread_cand = top1 - bot1
        spread_freeze = top1 - bot0  # keep T_cand, force B_ctrl
        s_b0 = set(b0["instrument"])
        s_b1 = set(b1["instrument"])
        s_t0 = set(t0["instrument"])
        s_t1 = set(t1["instrument"])
        kth_top0 = float(t0["score"].iloc[-1])
        kth_top1 = float(t1["score"].iloc[-1])
        kth_bot0 = float(b0["score"].iloc[0])
        kth_bot1 = float(b1["score"].iloc[0])
        row = {
            "datetime": pd.Timestamp(dt),
            "window": name,
            "n": n,
            "spread_ctrl": spread_ctrl,
            "spread_cand": spread_cand,
            "spread_freeze": spread_freeze,
            "d_spread_cand": spread_cand - spread_ctrl,
            "d_spread_freeze": spread_freeze - spread_ctrl,
            "top_mean_ctrl": top0,
            "top_mean_cand": top1,
            "bot_mean_ctrl": bot0,
            "bot_mean_cand": bot1,
            "d_top_mean": top1 - top0,
            "d_bot_mean": bot1 - bot0,
            "univ_label": univ,
            "top10_univ_ctrl": top0 - univ,
            "top10_univ_cand": top1 - univ,
            "d_top10_univ": (top1 - univ) - (top0 - univ),
            "bot_overlap": len(s_b0 & s_b1),
            "bot_jaccard": len(s_b0 & s_b1) / len(s_b0 | s_b1) if (s_b0 | s_b1) else float("nan"),
            "top_overlap": len(s_t0 & s_t1),
            "top_jaccard": len(s_t0 & s_t1) / len(s_t0 | s_t1) if (s_t0 | s_t1) else float("nan"),
            "n_at_kth_top_ctrl": int((g["score_ctrl"] == kth_top0).sum()),
            "n_at_kth_top_cand": int((g["score_cand"] == kth_top1).sum()),
            "n_at_kth_bot_ctrl": int((g["score_ctrl"] == kth_bot0).sum()),
            "n_at_kth_bot_cand": int((g["score_cand"] == kth_bot1).sum()),
        }
        if not np.isfinite(row["spread_ctrl"]) or not np.isfinite(row["spread_cand"]) or not np.isfinite(row["spread_freeze"]):
            continue
        rows.append(row)
    return pd.DataFrame(rows)


def jsonable(v):
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, (np.integer, int)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return float(v) if math.isfinite(float(v)) else None
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (pd.Timestamp, datetime)):
        return str(v)
    if v is None:
        return None
    return v


def quarter_means(daily: pd.Series) -> dict:
    s = daily.dropna()
    if s.empty:
        return {}
    q = s.groupby(s.index.to_period("Q")).mean()
    return {str(k): float(v) for k, v in q.items()}


def month_means(daily: pd.Series) -> dict:
    s = daily.dropna()
    if s.empty:
        return {}
    m = s.groupby(s.index.to_period("M")).mean()
    return {str(k): float(v) for k, v in m.items()}


def decide_verdict(w25: dict, w26: dict) -> dict:
    freeze26 = w26["d_spread_freeze"]["mean"]
    cand26 = w26["d_spread_cand"]["mean"]
    freeze25 = w25["d_spread_freeze"]["mean"]
    cand25 = w25["d_spread_cand"]["mean"]
    ci_lo26 = w26["d_spread_freeze"]["ci_lo"]
    ci_hi26 = w26["d_spread_freeze"]["ci_hi"]
    flipped = freeze26 > 0
    better_than_cand = freeze26 > cand26
    y25_ok = (freeze25 >= 0) or (freeze25 >= cand25)
    still_sig_neg = (freeze26 < 0) and (ci_hi26 < 0)
    weaken = (freeze26 <= cand26) or still_sig_neg or (freeze26 <= 0 and not flipped)
    limited = abs(freeze26 - cand26) < abs(cand26) * 0.25 if cand26 != 0 else abs(freeze26 - cand26) < 1e-5
    if weaken:
        verdict = "削弱"
        reason = (
            "2026 mean(ΔSpread_freeze)≤mean(ΔSpread_cand)"
            if freeze26 <= cand26
            else "2026 ΔSpread_freeze 仍显著为负或未翻非负"
        )
    elif flipped and better_than_cand and y25_ok and (ci_lo26 > 0) and not limited:
        verdict = "支持「否决来自底部而非头部」"
        reason = "2026 mean(ΔSpread_freeze)>0 且 CI 下沿>0，明显好于冻结 ΔSpread_cand；2025 同步不差"
    elif flipped and better_than_cand and y25_ok:
        verdict = "部分支持"
        reason = (
            "2026 ΔSpread_freeze 均值翻非负且好于冻结 ΔSpread_cand，但 CI 下沿≤0"
            if ci_lo26 <= 0
            else "2026 点估计翻非负，但相对 ΔSpread_cand 改善有限或 CI 不稳"
        )
    else:
        verdict = "部分支持"
        reason = "未落入削弱，也未满足全额支持门槛"
    return {
        "verdict": verdict,
        "reason": reason,
        "flipped_nonneg_2026": flipped,
        "better_than_cand_2026": better_than_cand,
        "y2025_ok": y25_ok,
        "ci_lo_positive_2026": bool(ci_lo26 > 0),
        "still_significantly_negative_2026": still_sig_neg,
        "limited_improvement": limited,
        "cannot_overturn": "WINRATIO_GAP_MODEL_NO_TRANSFER",
    }


def fmt_sci(x: float) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "NA"
    return f"{x:+.3e}"


def write_report(out: Path, summary: dict, daily: pd.DataFrame) -> None:
    w25 = summary["windows"]["2025_valid"]
    w26 = summary["windows"]["2026_oos"]
    v = summary["decision"]
    lines = []
    lines.append("# T5-WRD1 伪实验1：Bottom10 冻结")
    lines.append("")
    lines.append(f"**结论先行：** 判决 **{v['verdict']}**。{v['reason']}。")
    lines.append(
        f"2026 mean(ΔSpread_freeze)={fmt_sci(w26['d_spread_freeze']['mean'])}"
        f"（CI [{fmt_sci(w26['d_spread_freeze']['ci_lo'])}, {fmt_sci(w26['d_spread_freeze']['ci_hi'])}]），"
        f"冻结候选 ΔSpread_cand={fmt_sci(w26['d_spread_cand']['mean'])}"
        f"（应对齐冻结 B 门 ≈{fmt_sci(FROZEN_D_TB_2026)}）。"
        f"恒等式 ΔSpread_freeze = ΔTop，与 univ-EW ΔTop10={fmt_sci(w26['d_top10_univ']['mean'])} 同值。"
        f"2025 mean(ΔSpread_freeze)={fmt_sci(w25['d_spread_freeze']['mean'])}。"
        f"本实验**不能推翻** `{v['cannot_overturn']}`（未重训）。"
    )
    lines.append("")
    lines.append("未改线上 pred `8a061ea4` / 10/3，未跑 C，未开伪实验2。")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 0. 范围与对齐")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| worktree / tip | `wt-myquant-pr78-t5-wrd1` @ `{summary['git_head']}` |")
    lines.append(f"| 对照 / 候选 | `{summary['control_recorder'][:8]}` / `{summary['candidate_recorder'][:8]}`（只读） |")
    lines.append(f"| sidecar SHA-256 | `{summary['sidecar_sha256']}` |")
    lines.append(f"| 标签 | `{LABEL}` |")
    lines.append("| 冻结口径 | Top−Bottom（`mean(T)−mean(B)`，与 B 门 pred_pair 一致） |")
    lines.append("| 伪实验组合 | 每日 `T_cand` 保留，`B` 强制换成 `B_ctrl` |")
    lines.append("| ties | score 降序 + instrument 字典序，`kind=mergesort`；禁止随机 |")
    lines.append(f"| 窗 | 2025-01-03～12-31（{w25['n_days']} 日）；2026-01-01～09-14（{w26['n_days']} 日；标签全空日不进） |")
    lines.append(f"| bootstrap | block={BOOT_BLOCK}，reps={BOOT_REPS}，seed=`{BOOT_SEED}` |")
    lines.append("")
    lines.append(
        f"对齐检查：2026 mean(ΔSpread_cand)={fmt_sci(w26['d_spread_cand']['mean'])}，"
        f"冻结 B 门 Top−Bottom Δ={fmt_sci(FROZEN_D_TB_2026)}，"
        f"绝对差={abs(w26['d_spread_cand']['mean'] - FROZEN_D_TB_2026):.3e}"
        f"（阈值 1e-8 视为复现）。"
        f"univ-EW ΔTop10={fmt_sci(w26['d_top10_univ']['mean'])} vs 冻结诊断 ≈{fmt_sci(FROZEN_D_UNIV_2026)}；"
        f"ΔBottom={fmt_sci(w26['d_bot_mean']['mean'])} vs ≈{fmt_sci(FROZEN_D_BOT_2026)}。"
    )
    lines.append("")
    lines.append(f"第 k 名并列：2025/2026 Top `n_at_kth` 日均 "
                 f"{w25['mean_n_at_kth_top_ctrl']:.3f}/{w26['mean_n_at_kth_top_ctrl']:.3f}（对照）、"
                 f"{w25['mean_n_at_kth_top_cand']:.3f}/{w26['mean_n_at_kth_top_cand']:.3f}（候选）；"
                 f"Bottom 对照 {w25['mean_n_at_kth_bot_ctrl']:.3f}/{w26['mean_n_at_kth_bot_ctrl']:.3f}。")
    lines.append("")
    lines.append("## 1. 预注册定义")
    lines.append("")
    lines.append("共同宇宙 = 对照 score ∩ 候选 score ∩ 标签非空。每日：")
    lines.append("")
    lines.append("- `Spread_ctrl = mean(label|T_ctrl) − mean(label|B_ctrl)`")
    lines.append("- `Spread_cand = mean(label|T_cand) − mean(label|B_cand)`")
    lines.append("- `Spread_freeze = mean(label|T_cand) − mean(label|B_ctrl)`")
    lines.append("- `ΔSpread_cand = Spread_cand − Spread_ctrl`（应复现冻结 B 门）")
    lines.append("- `ΔSpread_freeze = Spread_freeze − Spread_ctrl = mean(T_cand) − mean(T_ctrl)`")
    lines.append("- 诊断：`Top10_univ = mean(T) − mean(universe)`，不改判决")
    lines.append("")
    lines.append("恒等式：`Δ(Top−Bottom) = ΔTop − ΔBottom`。冻结底部后 `ΔSpread_freeze = ΔTop`，"
                 "与 univ-EW ΔTop10 同值（宇宙项相消）。")
    lines.append("")
    lines.append("## 2. 窗口结果")
    lines.append("")
    lines.append("| 窗 | n日 | Spread_ctrl | Spread_cand | Spread_freeze | ΔSpread_cand | ΔSpread_freeze | univ-EW ΔTop10 | ΔBottom |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for key, w in (("2025", w25), ("2026", w26)):
        lines.append(
            f"| {key} | {w['n_days']} | {fmt_sci(w['spread_ctrl']['mean'])} | {fmt_sci(w['spread_cand']['mean'])} | "
            f"{fmt_sci(w['spread_freeze']['mean'])} | {fmt_sci(w['d_spread_cand']['mean'])} | "
            f"{fmt_sci(w['d_spread_freeze']['mean'])} | {fmt_sci(w['d_top10_univ']['mean'])} | "
            f"{fmt_sci(w['d_bot_mean']['mean'])} |"
        )
    lines.append("")
    lines.append("### Bootstrap（moving-block，block=5，reps=10000，seed=20260919）")
    lines.append("")
    lines.append("| 窗 | 序列 | 点估计 | CI 2.5% | CI 97.5% |")
    lines.append("|---|---|---:|---:|---:|")
    for key, w in (("2025", w25), ("2026", w26)):
        for col in ("d_spread_freeze", "d_spread_cand", "d_top10_univ", "d_bot_mean"):
            b = w[col]
            lines.append(
                f"| {key} | `{col}` | {fmt_sci(b['mean'])} | {fmt_sci(b['ci_lo'])} | {fmt_sci(b['ci_hi'])} |"
            )
    lines.append("")
    lines.append("### 底部重叠（对照 vs 候选 Bottom10）")
    lines.append("")
    lines.append(
        f"2025 日均 Jaccard={w25['bot_jaccard_mean']:.3f}、重叠={w25['bot_overlap_mean']:.2f}/10；"
        f"2026 Jaccard={w26['bot_jaccard_mean']:.3f}、重叠={w26['bot_overlap_mean']:.2f}/10。"
        f"底部并非几乎相同，强制替换会改 spread。"
    )
    lines.append("")
    lines.append("### 季度 mean(ΔSpread_freeze) / mean(ΔSpread_cand)")
    lines.append("")
    lines.append("| 季 | ΔSpread_freeze | ΔSpread_cand | ΔBottom |")
    lines.append("|---|---:|---:|---:|")
    qkeys = sorted(set(w25["quarters_freeze"]) | set(w25["quarters_cand"]) | set(w26["quarters_freeze"]) | set(w26["quarters_cand"]))
    qbot = {**w25["quarters_bot"], **w26["quarters_bot"]}
    qf = {**w25["quarters_freeze"], **w26["quarters_freeze"]}
    qc = {**w25["quarters_cand"], **w26["quarters_cand"]}
    for q in qkeys:
        lines.append(
            f"| {q} | {fmt_sci(qf.get(q, float('nan')))} | {fmt_sci(qc.get(q, float('nan')))} | {fmt_sci(qbot.get(q, float('nan')))} |"
        )
    lines.append("")
    d26 = daily[daily["window"] == "2026_oos"].copy()
    d26["month"] = d26["datetime"].dt.to_period("M")
    by_m = d26.groupby("month")[["d_spread_freeze", "d_spread_cand", "d_bot_mean"]].mean()
    lines.append("2026 月度 mean：")
    lines.append("")
    lines.append("| 月 | ΔSpread_freeze | ΔSpread_cand | ΔBottom |")
    lines.append("|---|---:|---:|---:|")
    for idx, r in by_m.iterrows():
        lines.append(
            f"| {idx} | {fmt_sci(float(r['d_spread_freeze']))} | {fmt_sci(float(r['d_spread_cand']))} | {fmt_sci(float(r['d_bot_mean']))} |"
        )
    lines.append("")
    lines.append("## 3. 判决（门槛未改）")
    lines.append("")
    lines.append("- **支持「否决来自底部而非头部」**：2026 mean(ΔSpread_freeze)>0，且明显好于冻结 ΔSpread_cand（至少翻到非负）；同时 2025 mean(ΔSpread_freeze)≥0 或不少于 ΔSpread_cand。")
    lines.append("- **部分支持**：2026 均值翻非负但 CI 下沿≤0，或相对 ΔSpread_cand 改善有限。")
    lines.append("- **削弱**：2026 mean(ΔSpread_freeze)≤mean(ΔSpread_cand) 或仍显著为负。")
    lines.append("")
    lines.append(f"**本刀：{v['verdict']}。** {v['reason']}。")
    lines.append("")
    lines.append(
        f"检查清单：2026 翻非负={v['flipped_nonneg_2026']}；好于候选={v['better_than_cand_2026']}；"
        f"2025 不差={v['y2025_ok']}；CI 下沿>0={v['ci_lo_positive_2026']}；"
        f"仍显著为负={v['still_significantly_negative_2026']}。"
    )
    lines.append("")
    lines.append("冻结终态不变：`WINRATIO_GAP_MODEL_NO_TRANSFER`。伪实验只解释 B 门 Top−Bottom 翻负的机制，不构成过 B / 进 C 的证据。")
    lines.append("")
    lines.append("## 4. 产物")
    lines.append("")
    lines.append(f"目录：`{out}`")
    lines.append("")
    lines.append("- `REPORT.md`（本文件）")
    lines.append("- `daily_metrics.csv`")
    lines.append("- `summary.json`")
    lines.append("")
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    if OUT_DIR.exists():
        print(f"[FAIL] out-dir exists (fail-closed): {OUT_DIR}", flush=True)
        return 2
    OUT_DIR.mkdir(parents=True, exist_ok=False)
    print(f"[out] {OUT_DIR}", flush=True)

    got = sha256_file(SIDECAR)
    if got.lower() != SIDECAR_SHA.lower():
        raise RuntimeError(f"sidecar sha mismatch {got}")
    print(f"[sidecar] sha ok {got}", flush=True)

    ctrl25 = load_pred(SCRIPT_DIR / "预测结果_8a061ea4_2025valid.csv")
    cand25 = load_pred(REPO / "exports" / "analysis" / "t5_wrd1_20260918" / "model" / "pred_2025.csv")
    ctrl26 = load_pred(REPO / "exports" / "analysis" / "t5_wrd1_20260918" / "control_pred_2026_8a061ea4.csv")
    cand26 = load_pred(REPO / "exports" / "analysis" / "t5_wrd1_20260918" / "model" / "pred_2026.csv")
    print(f"[pred] ctrl25={len(ctrl25)} cand25={len(cand25)} ctrl26={len(ctrl26)} cand26={len(cand26)}", flush=True)

    import qlib
    from qlib.constant import REG_CN

    print("[init] qlib", flush=True)
    qlib.init(provider_uri=PROVIDER, region=REG_CN, kernels=1)
    inst = sorted(
        set(ctrl25["instrument"]) | set(cand25["instrument"]) | set(ctrl26["instrument"]) | set(cand26["instrument"])
    )
    print(f"[labels] n_inst={len(inst)} 2025-01-03..2026-09-14", flush=True)
    labels = load_labels(inst, "2025-01-03", "2026-09-14")
    print(f"[labels] rows={len(labels)} finite={int(labels['label'].notna().sum())}", flush=True)

    frozen = json.loads(FROZEN_VERDICT.read_text(encoding="utf-8"))
    frames = []
    win_stats = {}
    for i, (name, start, end) in enumerate(WINDOWS):
        ctrl = ctrl25 if i == 0 else ctrl26
        cand = cand25 if i == 0 else cand26
        print(f"[eval] {name}", flush=True)
        m0, m1 = common_pair(ctrl, cand, labels, start, end)
        daily_w = analyze_window(name, m0, m1)
        frames.append(daily_w)
        from diag_pred_pair import daily_top10_spread

        fw = next(w for w in frozen["windows"] if w["window"] == name)
        d_cand = float(daily_w["d_spread_cand"].mean())
        align_err = abs(d_cand - float(fw["top10_delta"]))
        tb0 = daily_top10_spread(m0, 10)
        tb1 = daily_top10_spread(m1, 10)
        frozen_style_delta = float(tb1.mean() - tb0.mean())
        frozen_style_err = abs(frozen_style_delta - float(fw["top10_delta"]))
        print(
            f"[align] {name} ΔSpread_cand={d_cand:.12e} frozen={fw['top10_delta']:.12e} "
            f"absdiff={align_err:.3e} frozen_style={frozen_style_delta:.12e} style_err={frozen_style_err:.3e}",
            flush=True,
        )
        if frozen_style_err > 1e-15:
            raise RuntimeError(f"{name}: frozen-style Top-Bottom did not reproduce pred_pair")

        def boot(col: str):
            x = daily_w[col].to_numpy()
            pe, lo, hi = moving_block_bootstrap_ci(x, BOOT_BLOCK, BOOT_REPS, BOOT_SEED)
            return {"mean": pe, "ci_lo": lo, "ci_hi": hi, "n": int(np.isfinite(x).sum())}

        idx = pd.DatetimeIndex(daily_w["datetime"])
        freeze_s = pd.Series(daily_w["d_spread_freeze"].to_numpy(), index=idx)
        cand_s = pd.Series(daily_w["d_spread_cand"].to_numpy(), index=idx)
        bot_s = pd.Series(daily_w["d_bot_mean"].to_numpy(), index=idx)
        win_stats[name] = {
            "start": start,
            "end": end,
            "n_days": int(len(daily_w)),
            "n_common_rows": int(len(m0)),
            "n_rows_mean": float(daily_w["n"].mean()) if len(daily_w) else None,
            "spread_ctrl": {"mean": float(daily_w["spread_ctrl"].mean())},
            "spread_cand": {"mean": float(daily_w["spread_cand"].mean())},
            "spread_freeze": {"mean": float(daily_w["spread_freeze"].mean())},
            "d_spread_cand": boot("d_spread_cand"),
            "d_spread_freeze": boot("d_spread_freeze"),
            "d_top10_univ": boot("d_top10_univ"),
            "d_bot_mean": boot("d_bot_mean"),
            "d_top_mean": {"mean": float(daily_w["d_top_mean"].mean())},
            "identity_freeze_eq_dtop_maxabs": float((daily_w["d_spread_freeze"] - daily_w["d_top_mean"]).abs().max()),
            "identity_freeze_eq_univ_maxabs": float((daily_w["d_spread_freeze"] - daily_w["d_top10_univ"]).abs().max()),
            "bot_jaccard_mean": float(daily_w["bot_jaccard"].mean()),
            "bot_overlap_mean": float(daily_w["bot_overlap"].mean()),
            "top_jaccard_mean": float(daily_w["top_jaccard"].mean()),
            "top_overlap_mean": float(daily_w["top_overlap"].mean()),
            "mean_n_at_kth_top_ctrl": float(daily_w["n_at_kth_top_ctrl"].mean()),
            "mean_n_at_kth_top_cand": float(daily_w["n_at_kth_top_cand"].mean()),
            "mean_n_at_kth_bot_ctrl": float(daily_w["n_at_kth_bot_ctrl"].mean()),
            "mean_n_at_kth_bot_cand": float(daily_w["n_at_kth_bot_cand"].mean()),
            "share_days_kth_tied_top_ctrl": float((daily_w["n_at_kth_top_ctrl"] > 1).mean()),
            "share_days_kth_tied_bot_ctrl": float((daily_w["n_at_kth_bot_ctrl"] > 1).mean()),
            "frozen_top10_delta": float(fw["top10_delta"]),
            "align_abs_err_vs_frozen_tb": align_err,
            "frozen_style_delta": frozen_style_delta,
            "frozen_style_abs_err": frozen_style_err,
            "quarters_freeze": quarter_means(freeze_s),
            "quarters_cand": quarter_means(cand_s),
            "quarters_bot": quarter_means(bot_s),
            "months_freeze": month_means(freeze_s),
            "months_cand": month_means(cand_s),
        }

    daily = pd.concat(frames, ignore_index=True)
    daily.to_csv(OUT_DIR / "daily_metrics.csv", index=False, encoding="utf-8")
    print(f"[daily] {len(daily)} days", flush=True)

    decision = decide_verdict(win_stats["2025_valid"], win_stats["2026_oos"])
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "out_dir": str(OUT_DIR),
        "git_head": GIT_HEAD,
        "sidecar_sha256": got,
        "label": LABEL,
        "topk": TOPK,
        "tie_break": "score desc, instrument lex asc, mergesort",
        "control_recorder": CTRL_RECORDER,
        "candidate_recorder": CAND_RECORDER,
        "online_untouched": True,
        "no_retrain": True,
        "no_portana": True,
        "no_pseudo2": True,
        "bootstrap": {"block": BOOT_BLOCK, "reps": BOOT_REPS, "seed": BOOT_SEED},
        "windows": win_stats,
        "decision": decision,
        "frozen_b_gate_2026_tb_delta": FROZEN_D_TB_2026,
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(jsonable(summary), indent=2, ensure_ascii=False), encoding="utf-8")
    write_report(OUT_DIR, summary, daily)
    print(json.dumps({"verdict": decision["verdict"], "reason": decision["reason"]}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
