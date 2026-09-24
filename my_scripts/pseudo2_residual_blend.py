# -*- coding: utf-8 -*-
"""T5-MXR1 pseudo-experiment 2: A-gate residual linearly blended onto control score.

Read-only. No retrain, no PortAna, no pred write-back. Fail-closed if out-dir exists.
Pre-registered lambdas only: {0.25, 0.5, 1.0}. Primary report λ=0.5.
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
MIN_N = 30
SIDECAR_SHA = "27320f8b7f6de3854802f97325f682039732470ce387f21bc9cd6c3083b7b348"
PROVIDER = r"C:/Users/wangc/.qlib/qlib_data/my_data"
SEED = 20260919
BLOCK = 5
BOOT = 10000
LAMBDAS = (0.25, 0.5, 1.0)
PRIMARY_LAMBDA = 0.5
WINDOWS = (("2025_valid", "2025-01-03", "2025-12-31"), ("2026_oos", "2026-01-01", "2026-09-14"))
FROZEN_LGB = {
    "2025_valid": {
        "d_top10": -5.260264777101273e-5,
        "top10_ctrl": 0.005374208280541511,
        "d_rankic": 5.0768410642020034e-5,
    },
    "2026_oos": {
        "d_top10": 4.921033324056564e-4,
        "top10_ctrl": 0.0004734034490215002,
        "d_rankic": 0.00046281734652085446,
        "d_rankic_ci_lo": -0.0005562195993456413,
    },
}
OUT = REPO / "exports" / "analysis" / "t5_mxr1_20260918" / "pseudo2_residual_blend_20260919"
INBOX = Path(r"D:\PycharmProjects\_agent_inbox\t5-mxr1-pseudo2")


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


def zscore(x: np.ndarray) -> tuple[np.ndarray | None, float]:
    x = np.asarray(x, dtype=float)
    sd = float(np.std(x, ddof=0))
    if not np.isfinite(sd) or sd == 0.0:
        return None, sd
    return (x - float(np.mean(x))) / sd, sd


def ols_resid(y: np.ndarray, x: np.ndarray) -> np.ndarray | None:
    yv = np.asarray(y, dtype=float)
    xv = np.asarray(x, dtype=float)
    design = np.column_stack([np.ones(len(yv)), xv])
    beta, _, rank, _ = np.linalg.lstsq(design, yv, rcond=None)
    if int(rank) < design.shape[1]:
        return None
    return yv - design @ beta


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    mask = np.isfinite(a) & np.isfinite(b)
    if int(mask.sum()) < 4:
        return float("nan")
    return float(pd.Series(a[mask]).corr(pd.Series(b[mask]), method="spearman"))


def top10_spread(score: np.ndarray, lab: np.ndarray, inst: np.ndarray) -> float:
    n = int(score.shape[0])
    if n < TOPK:
        return float("nan")
    order = np.lexsort((inst, -score))
    top_lab = lab[order[:TOPK]]
    if not np.isfinite(top_lab).any() or not np.isfinite(lab).any():
        return float("nan")
    return float(np.nanmean(top_lab) - np.nanmean(lab))


def top10_set(score: np.ndarray, inst: np.ndarray) -> set[str]:
    order = np.lexsort((inst, -score))
    return set(inst[order[:TOPK]].tolist())


def merge_universe(ctrl: pd.DataFrame, side: pd.DataFrame, labels: pd.DataFrame, start: str, end: str):
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    c0 = ctrl[(ctrl["datetime"] >= s) & (ctrl["datetime"] <= e)].copy()
    lab = labels[(labels["datetime"] >= s) & (labels["datetime"] <= e)]
    feat = side[(side["datetime"] >= s) & (side["datetime"] <= e)]
    m = c0.merge(feat, on=["datetime", "instrument"], how="inner")
    m = m.merge(lab, on=["datetime", "instrument"], how="left")
    return m


def analyze_days(df: pd.DataFrame, window: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    metric_rows = []
    skip_rows = []
    for dt, g in df.groupby("datetime", sort=True):
        score = g["score"].to_numpy(dtype=float)
        feat = g[FEATURE].to_numpy(dtype=float)
        lab = g["label"].to_numpy(dtype=float)
        inst = g["instrument"].to_numpy()
        ok = np.isfinite(score) & np.isfinite(feat)
        n_ok = int(ok.sum())
        n_label = int((ok & np.isfinite(lab)).sum())
        base = {
            "datetime": pd.Timestamp(dt),
            "window": window,
            "n": n_ok,
            "n_label": n_label,
            "n_raw": int(len(g)),
        }
        if n_ok < MIN_N:
            skip_rows.append({**base, "skip_reason": "n_lt_30"})
            continue
        s0 = score[ok]
        f = feat[ok]
        y = lab[ok]
        names = inst[ok]
        s0z, s0_sd = zscore(s0)
        if s0z is None:
            skip_rows.append({**base, "skip_reason": "s0_std0"})
            continue
        resid = ols_resid(f, s0)
        if resid is None:
            skip_rows.append({**base, "skip_reason": "ols_rank_deficient"})
            continue
        rz, r_sd = zscore(resid)
        if rz is None:
            skip_rows.append({**base, "skip_reason": "resid_std0"})
            continue
        ric0 = spearman(s0, y)
        sp0 = top10_spread(s0, y, names)
        set0 = top10_set(s0, names) if n_ok >= TOPK else set()
        ss_xy = float(np.dot(s0 - s0.mean(), f - f.mean()))
        ss_xx = float(np.dot(s0 - s0.mean(), s0 - s0.mean()))
        ss_yy = float(np.dot(f - f.mean(), f - f.mean()))
        r2 = float((ss_xy * ss_xy) / (ss_xx * ss_yy)) if ss_xx > 0 and ss_yy > 0 else float("nan")
        for lam in LAMBDAS:
            s1 = s0z + float(lam) * rz
            ric1 = spearman(s1, y)
            sp1 = top10_spread(s1, y, names)
            set1 = top10_set(s1, names) if n_ok >= TOPK else set()
            overlap = len(set0 & set1) if set0 and set1 else float("nan")
            metric_rows.append(
                {
                    **base,
                    "lambda": float(lam),
                    "skip_reason": "",
                    "s0_sd": s0_sd,
                    "resid_sd": r_sd,
                    "ols_r2": r2,
                    "rankic_s0": ric0,
                    "rankic_s1": ric1,
                    "d_rankic": float(ric1 - ric0) if np.isfinite(ric0) and np.isfinite(ric1) else float("nan"),
                    "top10_s0": sp0,
                    "top10_s1": sp1,
                    "d_top10": float(sp1 - sp0) if np.isfinite(sp0) and np.isfinite(sp1) else float("nan"),
                    "top10_overlap": float(overlap) if np.isfinite(overlap) else float("nan"),
                    "top10_turnover": float((TOPK - overlap) / TOPK) if np.isfinite(overlap) else float("nan"),
                }
            )
    metrics = pd.DataFrame(metric_rows)
    skipped = pd.DataFrame(skip_rows)
    return metrics, skipped


def _boot(series: pd.Series) -> dict:
    pe, lo, hi = moving_block_bootstrap_ci(series.to_numpy(), block_days=BLOCK, reps=BOOT, seed=SEED)
    return {"point": pe, "lo": lo, "hi": hi, "block": BLOCK, "reps": BOOT, "seed": SEED}


def summarize_slice(d: pd.DataFrame, skipped: pd.DataFrame, name: str, start: str, end: str, lam: float) -> dict:
    sub = d[np.isclose(d["lambda"], lam)].copy() if len(d) else d
    ric = sub[np.isfinite(sub["d_rankic"])] if len(sub) else sub
    top = sub[np.isfinite(sub["d_top10"])] if len(sub) else sub
    skip_counts = {}
    if len(skipped):
        skip_counts = {str(k): int(v) for k, v in skipped["skip_reason"].value_counts().items()}
    months = []
    if len(top):
        tmp = top.copy()
        tmp["month"] = tmp["datetime"].dt.to_period("M").astype(str)
        for month, g in tmp.groupby("month", sort=True):
            months.append(
                {
                    "month": month,
                    "n_days": int(len(g)),
                    "d_rankic": float(g["d_rankic"].mean()) if np.isfinite(g["d_rankic"]).any() else float("nan"),
                    "d_top10": float(g["d_top10"].mean()),
                    "d_top10_sum": float(g["d_top10"].sum()),
                    "d_top10_share_neg": float((g["d_top10"] < 0).mean()),
                    "d_rankic_share_pos": float((g["d_rankic"] > 0).mean()) if np.isfinite(g["d_rankic"]).any() else float("nan"),
                }
            )
    q_ric, q_top = {}, {}
    if len(ric):
        q_ric = {str(k): float(v) for k, v in ric.groupby(ric["datetime"].dt.to_period("Q"))["d_rankic"].mean().items()}
    if len(top):
        q_top = {str(k): float(v) for k, v in top.groupby(top["datetime"].dt.to_period("Q"))["d_top10"].mean().items()}
    frozen = FROZEN_LGB[name]
    return {
        "lambda": float(lam),
        "start": start,
        "end": end,
        "n_days_metrics": int(len(sub)),
        "n_days_rankic": int(len(ric)),
        "n_days_top10": int(len(top)),
        "n_days_skipped": int(len(skipped)),
        "skip_counts": skip_counts,
        "n_rows_mean": float(sub["n"].mean()) if len(sub) else float("nan"),
        "n_label_mean": float(sub["n_label"].mean()) if len(sub) else float("nan"),
        "ols_r2_mean": float(sub["ols_r2"].mean()) if len(sub) else float("nan"),
        "rankic_s0": float(ric["rankic_s0"].mean()) if len(ric) else float("nan"),
        "rankic_s1": float(ric["rankic_s1"].mean()) if len(ric) else float("nan"),
        "d_rankic": float(ric["d_rankic"].mean()) if len(ric) else float("nan"),
        "d_rankic_share_pos": float((ric["d_rankic"] > 0).mean()) if len(ric) else float("nan"),
        "d_rankic_share_neg": float((ric["d_rankic"] < 0).mean()) if len(ric) else float("nan"),
        "top10_s0": float(top["top10_s0"].mean()) if len(top) else float("nan"),
        "top10_s1": float(top["top10_s1"].mean()) if len(top) else float("nan"),
        "d_top10": float(top["d_top10"].mean()) if len(top) else float("nan"),
        "d_top10_share_pos": float((top["d_top10"] > 0).mean()) if len(top) else float("nan"),
        "d_top10_share_neg": float((top["d_top10"] < 0).mean()) if len(top) else float("nan"),
        "bootstrap_d_rankic": _boot(ric["d_rankic"]) if len(ric) else {"point": None, "lo": None, "hi": None},
        "bootstrap_d_top10": _boot(top["d_top10"]) if len(top) else {"point": None, "lo": None, "hi": None},
        "top10_overlap_mean": float(sub["top10_overlap"].mean()) if len(sub) else float("nan"),
        "top10_turnover_mean": float(sub["top10_turnover"].mean()) if len(sub) else float("nan"),
        "lgb_frozen_d_top10": frozen["d_top10"],
        "lgb_frozen_d_rankic": frozen["d_rankic"],
        "lgb_frozen_d_rankic_ci_lo": frozen.get("d_rankic_ci_lo"),
        "quarters_d_rankic": q_ric,
        "quarters_d_top10": q_top,
        "months": months,
    }


def decide_verdict(primary: dict) -> dict:
    w25 = primary["2025_valid"]
    w26 = primary["2026_oos"]
    d_ric_26 = w26["d_rankic"]
    ci_lo_26 = w26["bootstrap_d_rankic"]["lo"]
    d_top_25 = w25["d_top10"]
    weaken = (not np.isfinite(d_ric_26) or d_ric_26 <= 0) or (not np.isfinite(d_top_25) or d_top_25 < 0)
    support = (
        np.isfinite(d_ric_26)
        and d_ric_26 > 0
        and np.isfinite(ci_lo_26)
        and ci_lo_26 > 0
        and np.isfinite(d_top_25)
        and d_top_25 >= 0
    )
    if weaken:
        tag = "WEAKEN"
        label = "削弱"
        why = (
            f"主档 λ=0.5：2026 mean(ΔRankIC)={d_ric_26:.6e}"
            f"{' ≤ 0' if (not np.isfinite(d_ric_26) or d_ric_26 <= 0) else ''}，"
            f"2025 mean(ΔTop10Spread)={d_top_25:.6e}"
            f"{' < 0' if (not np.isfinite(d_top_25) or d_top_25 < 0) else ''}。"
        )
    elif support:
        tag = "SUPPORT_DIRECT_LIFT"
        label = "支持「条件信息可直接抬升排序」"
        why = (
            f"主档 λ=0.5：2026 mean(ΔRankIC)={d_ric_26:.6e} > 0 且 bootstrap 95% CI 下沿 "
            f"{ci_lo_26:.6e} > 0；同时 2025 mean(ΔTop10Spread)={d_top_25:.6e} ≥ 0"
            f"（相对 LGB 的 {FROZEN_LGB['2025_valid']['d_top10']:.3e} 至少非负）。"
        )
    else:
        tag = "PARTIAL_SUPPORT"
        label = "部分支持"
        why = (
            f"主档 λ=0.5：2026 mean(ΔRankIC)={d_ric_26:.6e} > 0 但 CI 下沿 "
            f"{ci_lo_26:.6e} ≤ 0，或 2025 ΔTop10 非负但 2026 CI 不过线。"
            f"2025 mean(ΔTop10Spread)={d_top_25:.6e}。"
        )
    return {
        "hypothesis_tag": tag,
        "verdict": label,
        "why": why,
        "cannot_overturn": "MAXRET_MODEL_NO_TRANSFER",
        "primary_lambda": PRIMARY_LAMBDA,
        "d_rankic_2026": d_ric_26,
        "d_rankic_2026_ci_lo": ci_lo_26,
        "d_top10_2025": d_top_25,
    }


def fmt(x, nd=6):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "NA"
    ax = abs(float(x))
    if ax != 0 and (ax < 1e-3 or ax >= 1e3):
        return f"{x:.3e}"
    return f"{x:.{nd}f}"


def write_report(out: Path, payload: dict) -> None:
    decision = payload["decision"]
    primary = payload["by_lambda"][str(PRIMARY_LAMBDA)]
    w25 = primary["2025_valid"]
    w26 = primary["2026_oos"]
    lines = []
    a = lines.append
    a("# T5-MXR1 伪实验2：A-gate residual 直接合成叠回")
    a("")
    a(f"**结论先行：** {decision['verdict']}。{decision['why']}")
    a("")
    a(
        "本实验**仍不能**推翻 `MAXRET_MODEL_NO_TRANSFER`（那是 LGB 重训 B 门）；"
        "它只回答「绕过 LGB、把 A-gate residual 线性叠回能否抬升」。"
        "未重训、未改 sidecar / 特征 / 方向 / 10/3、未写回 pred、未跑 PortAna/BT、未扫其它 λ/seed/窗。"
        "附录 λ∈{0.25,1.0} **不得**改主结论门槛。"
    )
    a("")
    a("---")
    a("")
    a("## 0. 范围与冻结")
    a("")
    a("| 项 | 值 |")
    a("|---|---|")
    a(f"| 输出目录 | `{out}` |")
    a(f"| sidecar SHA-256 | `{payload['sidecar_sha256']}` |")
    a("| 对照 pred | `8a061ea4` 2025 CSV + 2026 `control_pred_2026_8a061ea4.csv`（只读） |")
    a("| 宇宙 | 对照 score ∩ sidecar `MAXRET20_ANTI_RANK`（有限值）；label 左连接 |")
    a("| 标签 | `Ref($close,-2)/Ref($close,-1)-1` |")
    a("| Top10Spread | 等权 Top10 − 共同宇宙等权；**禁止 Top-Bottom** |")
    a("| 合成 | `s0_z` = 当日截面 z-score(s0, ddof=0)；`r = f-(a+b*s0)` OLS 含截距；`rz` 再 z-score；`s1=s0_z+λ·rz` |")
    a("| 跳过 | 当日有效样本 < 30，或 s0 / 残差截面 std=0（ddof=0），或 OLS 秩亏 |")
    a(f"| 主档 λ | `{PRIMARY_LAMBDA}`；敏感性 `{list(LAMBDAS)}`（禁止扫其它 λ） |")
    a(f"| bootstrap | moving-block，block={BLOCK}，reps={BOOT}，seed=`{SEED}` |")
    a("| 窗 | 2025-01-03～12-31；2026-01-01～09-14 |")
    a("| 冻结 LGB B 门 | 2025 ΔTop10≈−5.26e-5；2026 ΔRankIC CI lower≈−5.56e-4 |")
    a("")
    a(
        f"跳过日数：2025 {w25['n_days_skipped']}（{w25['skip_counts']}）；"
        f"2026 {w26['n_days_skipped']}（{w26['skip_counts']}）。"
        f"OLS R² 均值 2025={fmt(w25['ols_r2_mean'], 3)}，2026={fmt(w26['ols_r2_mean'], 3)}。"
    )
    a("")
    a("## 1. 主档 λ=0.5")
    a("")
    a("| 窗 | 日数 RankIC | 日数 Top10 | RankIC s0 | RankIC s1 | **ΔRankIC** | ΔRankIC 95% CI | Top10 s0 | Top10 s1 | **ΔTop10** | ΔTop10 95% CI |")
    a("|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---|")
    for name, w in (("2025_valid", w25), ("2026_oos", w26)):
        cr = w["bootstrap_d_rankic"]
        ct = w["bootstrap_d_top10"]
        a(
            f"| {name} | {w['n_days_rankic']} | {w['n_days_top10']} | {fmt(w['rankic_s0'])} | {fmt(w['rankic_s1'])} | "
            f"**{fmt(w['d_rankic'])}** | [{fmt(cr['lo'])}, {fmt(cr['hi'])}] | {fmt(w['top10_s0'])} | {fmt(w['top10_s1'])} | "
            f"**{fmt(w['d_top10'])}** | [{fmt(ct['lo'])}, {fmt(ct['hi'])}] |"
        )
    a("")
    a(
        f"Δ 的分母是对照∩sidecar 共同宇宙等权次日 label。Top10 重叠（s0 vs s1）均值："
        f"2025 {fmt(w25['top10_overlap_mean'], 2)} / 换手 {fmt(w25['top10_turnover_mean'], 3)}；"
        f"2026 {fmt(w26['top10_overlap_mean'], 2)} / 换手 {fmt(w26['top10_turnover_mean'], 3)}。"
        f"日度为正比例 ΔRankIC：2025 {w25['d_rankic_share_pos']:.1%}，2026 {w26['d_rankic_share_pos']:.1%}；"
        f"ΔTop10：2025 {w25['d_top10_share_pos']:.1%}，2026 {w26['d_top10_share_pos']:.1%}。"
    )
    a("")
    a("对照冻结 LGB B 门：本实验没有重训，数字只作锚，不改门槛。")
    a("")
    a("| 窗 | 本实验 ΔRankIC | 冻结 LGB ΔRankIC | 本实验 ΔTop10 | 冻结 LGB ΔTop10 |")
    a("|---|---:|---:|---:|---:|")
    a(
        f"| 2025_valid | {fmt(w25['d_rankic'])} | {fmt(w25['lgb_frozen_d_rankic'])} | {fmt(w25['d_top10'])} | {fmt(w25['lgb_frozen_d_top10'])} |"
    )
    a(
        f"| 2026_oos | {fmt(w26['d_rankic'])} | {fmt(w26['lgb_frozen_d_rankic'])} | {fmt(w26['d_top10'])} | {fmt(w26['lgb_frozen_d_top10'])} |"
    )
    a("")
    a("## 2. 2025 月度（主档 λ=0.5）")
    a("")
    a("| 月 | 日数 | mean ΔRankIC | mean ΔTop10 | sum ΔTop10 | ΔTop10 日为负比例 |")
    a("|---|---:|---:|---:|---:|---:|")
    months_sorted = sorted(w25["months"], key=lambda r: r["d_top10_sum"])
    for r in months_sorted:
        a(
            f"| {r['month']} | {r['n_days']} | {fmt(r['d_rankic'])} | {fmt(r['d_top10'])} | {fmt(r['d_top10_sum'])} | {r['d_top10_share_neg']:.0%} |"
        )
    a("")
    a("季度 mean：")
    a("")
    a("| 季 | ΔRankIC | ΔTop10 |")
    a("|---|---:|---:|")
    quarters = sorted(set(w25["quarters_d_rankic"]) | set(w25["quarters_d_top10"]) | set(w26["quarters_d_rankic"]) | set(w26["quarters_d_top10"]))
    for q in quarters:
        ric = w25["quarters_d_rankic"].get(q, w26["quarters_d_rankic"].get(q))
        top = w25["quarters_d_top10"].get(q, w26["quarters_d_top10"].get(q))
        a(f"| {q} | {fmt(ric)} | {fmt(top)} |")
    a("")
    a("## 3. 判决（预注册门槛，未改）")
    a("")
    a(f"- **{decision['verdict']}**")
    a(f"- {decision['why']}")
    a(
        f"- 2026 ΔRankIC CI = [{fmt(w26['bootstrap_d_rankic']['lo'])}, {fmt(w26['bootstrap_d_rankic']['hi'])}]；"
        f"2025 ΔTop10 CI = [{fmt(w25['bootstrap_d_top10']['lo'])}, {fmt(w25['bootstrap_d_top10']['hi'])}]。"
    )
    a("- 支持门槛：主档 λ=0.5 下 2026 mean(ΔRankIC)>0 且 CI 下沿>0，同时 2025 mean(ΔTop10Spread)≥0。")
    a("- 终态标签仍是 `MAXRET_MODEL_NO_TRANSFER`。线性叠回不是 LGB 重训，不能推翻 B 门。")
    a("")
    a("## 4. 附录：λ 敏感性（不改主结论）")
    a("")
    a("| λ | 窗 | ΔRankIC | ΔRankIC 95% CI | ΔTop10 | ΔTop10 95% CI | Top10 换手 |")
    a("|---:|---|---:|---|---:|---|---:|")
    for lam in LAMBDAS:
        block = payload["by_lambda"][str(lam)]
        note = " **主档**" if lam == PRIMARY_LAMBDA else ""
        for name in ("2025_valid", "2026_oos"):
            w = block[name]
            cr = w["bootstrap_d_rankic"]
            ct = w["bootstrap_d_top10"]
            a(
                f"| {lam}{note} | {name} | {fmt(w['d_rankic'])} | [{fmt(cr['lo'])}, {fmt(cr['hi'])}] | "
                f"{fmt(w['d_top10'])} | [{fmt(ct['lo'])}, {fmt(ct['hi'])}] | {fmt(w['top10_turnover_mean'], 3)} |"
            )
    a("")
    a("附录只作敏感性。主判决只看 λ=0.5，不因 0.25 / 1.0 改门槛。")
    a("")
    a("## 5. 未做")
    a("")
    a("- 未重训 LGB、未改 sidecar / 特征定义 / 方向 / 列、未扫其它 λ / seed / 窗。")
    a("- 未跑 PortAna / BT，未改 10/3，未写回 pred，未开新刀。")
    a("")
    a("## 产物")
    a("")
    a(f"- `{out / 'REPORT.md'}`")
    a(f"- `{out / 'daily_metrics.csv'}`")
    a(f"- `{out / 'summary.json'}`")
    a("")
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_result_md(payload: dict, out: Path) -> None:
    d = payload["decision"]
    w25 = payload["by_lambda"][str(PRIMARY_LAMBDA)]["2025_valid"]
    w26 = payload["by_lambda"][str(PRIMARY_LAMBDA)]["2026_oos"]
    INBOX.mkdir(parents=True, exist_ok=True)
    text = (
        "# T5-MXR1 伪实验2 RESULT\n\n"
        f"- **report**: `{out / 'REPORT.md'}`\n"
        f"- **daily / summary**: `{out / 'daily_metrics.csv'}` ； `{out / 'summary.json'}`\n"
        f"- sidecar SHA-256 `{payload['sidecar_sha256']}`；线上 pred `8a061ea4` / 10/3 未动；未开 PortAna / 新刀\n\n"
        f"主档 λ=0.5：2026 mean(ΔRankIC)={w26['d_rankic']:.6e}，"
        f"bootstrap 95% CI [{w26['bootstrap_d_rankic']['lo']:.3e}, {w26['bootstrap_d_rankic']['hi']:.3e}]；"
        f"2025 mean(ΔTop10Spread)={w25['d_top10']:.6e}（冻结 LGB 2025 ΔTop10={FROZEN_LGB['2025_valid']['d_top10']:.3e}）。"
        f"本实验不能推翻 `MAXRET_MODEL_NO_TRANSFER`。"
        f"判决：**{d['verdict']}**（`{d['hypothesis_tag']}`）。\n"
    )
    (INBOX / "RESULT.md").write_text(text, encoding="utf-8")


def write_blocker(msg: str) -> int:
    print(f"[FAIL] {msg}", flush=True)
    INBOX.mkdir(parents=True, exist_ok=True)
    (INBOX / "RESULT.md").write_text(
        "# T5-MXR1 伪实验2 RESULT\n\n"
        f"BLOCKED: {msg}\n\n"
        "未改线上 pred / sidecar / 10/3；未开 PortAna / 新刀。\n",
        encoding="utf-8",
    )
    return 2


def main() -> int:
    sidecar = REPO / "exports" / "analysis" / "t5_mxr1_20260918" / "sidecar" / "MAXRET20_ANTI_RANK.parquet"
    ctrl25_path = SCRIPT_DIR / "预测结果_8a061ea4_2025valid.csv"
    ctrl26_path = REPO / "exports" / "analysis" / "t5_mxr1_20260918" / "control_pred_2026_8a061ea4.csv"
    if not sidecar.is_file():
        return write_blocker(f"sidecar missing: {sidecar}")
    if not ctrl25_path.is_file():
        return write_blocker(f"control 2025 csv missing: {ctrl25_path}")
    if not ctrl26_path.is_file():
        return write_blocker(
            f"control 2026 csv missing: {ctrl26_path}; refused to export from recorder in this run"
        )
    got = sha256_file(sidecar)
    if got.lower() != SIDECAR_SHA.lower():
        return write_blocker(f"sidecar sha mismatch {got}")
    print(f"[sidecar] sha ok {got}", flush=True)

    if OUT.exists():
        return write_blocker(f"fail-closed: out-dir already exists: {OUT}")
    OUT.mkdir(parents=True, exist_ok=False)
    print(f"[out] {OUT}", flush=True)
    ctrl25 = load_pred(ctrl25_path)
    ctrl26 = load_pred(ctrl26_path)
    print(f"[pred] ctrl25={len(ctrl25)} ctrl26={len(ctrl26)}", flush=True)

    import qlib
    from qlib.constant import REG_CN

    print("[init] qlib", flush=True)
    qlib.init(provider_uri=PROVIDER, region=REG_CN, kernels=1)
    inst = sorted(set(ctrl25["instrument"]) | set(ctrl26["instrument"]))
    print(f"[labels] n_inst={len(inst)} 2025-01-03..2026-09-14", flush=True)
    labels = load_labels(inst, "2025-01-03", "2026-09-14", LABEL)
    print(f"[labels] rows={len(labels)}", flush=True)

    side = pd.read_parquet(sidecar, columns=["datetime", "instrument", FEATURE])
    side["datetime"] = pd.to_datetime(side["datetime"]).dt.normalize()
    side["instrument"] = side["instrument"].astype(str)
    side = side[side["datetime"] >= pd.Timestamp("2025-01-01")]
    side = side[np.isfinite(side[FEATURE])]

    frames = []
    skipped_frames = []
    window_days = {}
    for name, a, b in WINDOWS:
        ctrl = ctrl25 if name.startswith("2025") else ctrl26
        pair = merge_universe(ctrl, side, labels, a, b)
        print(f"[window] {name} rows={len(pair)} days={pair['datetime'].nunique()}", flush=True)
        daily, skipped = analyze_days(pair, name)
        print(f"[daily] {name} n={len(daily)} skipped_days={len(skipped)}", flush=True)
        window_days[name] = (daily, skipped, a, b)
        frames.append(daily)
        if len(skipped):
            skipped_frames.append(skipped)

    daily_all = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    daily_all.to_csv(OUT / "daily_metrics.csv", index=False, encoding="utf-8")
    if skipped_frames:
        pd.concat(skipped_frames, ignore_index=True).to_csv(OUT / "skipped_days.csv", index=False, encoding="utf-8")

    by_lambda = {}
    for lam in LAMBDAS:
        block = {}
        for name, (daily, skipped, a, b) in window_days.items():
            print(f"[summarize] λ={lam} {name}", flush=True)
            block[name] = summarize_slice(daily, skipped, name, a, b, lam)
        by_lambda[str(lam)] = block

    decision = decide_verdict(by_lambda[str(PRIMARY_LAMBDA)])
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "out_dir": str(OUT),
        "sidecar_sha256": got,
        "label": LABEL,
        "feature": FEATURE,
        "top10_spread_vs": "common-universe-equal-weight",
        "blend": "s1 = zscore(s0, ddof=0) + lambda * zscore(OLS residual f~s0 with intercept, ddof=0)",
        "lambdas": list(LAMBDAS),
        "primary_lambda": PRIMARY_LAMBDA,
        "min_n": MIN_N,
        "bootstrap": {"block": BLOCK, "reps": BOOT, "seed": SEED},
        "control_recorder": "8a061ea428e04bb3a199a485ade49d0e",
        "online_untouched": True,
        "no_retrain": True,
        "no_portana": True,
        "no_new_knives": True,
        "decision": decision,
        "hypothesis_tag": decision["hypothesis_tag"],
        "verdict": decision["verdict"],
        "cannot_overturn": "MAXRET_MODEL_NO_TRANSFER",
        "frozen_lgb": FROZEN_LGB,
        "by_lambda": by_lambda,
    }
    (OUT / "summary.json").write_text(json.dumps(json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(OUT, payload)
    write_result_md(payload, OUT)
    print(json.dumps({"verdict": decision["verdict"], "tag": decision["hypothesis_tag"]}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        write_blocker(f"{type(exc).__name__}: {exc}")
        raise
