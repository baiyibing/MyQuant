"""MEGA_MA20_BREAK 冻结阈值跨年打分（仿 validate_cross_year.py，gen2 池版）。

池（用户两核心指标）：(bov-sov)/freeFloatCapital>0.02 × MA20 首站当日(cross_age=0)。
阈值完全冻结自 2026-H1（ma20_mega_break_2026.meta.json），其余年份只打分不拟合。

诚实性声明：A0（cross_age=0 变体）的选择过程参考过 2023-2025 跨年诊断
（见 docs/l2_signals/2026-11-05-ma20-mega-gen2-search.md 第四节），因此本验证
对 2023-2025 不是严格样本外——严格样本外只有未来数据。本脚本的角色是把
"冻结后的可复算口径"固定下来，供未来样本续验。

用法：
    D:/anaconda3/envs/vanna312/python.exe l2_signals/validate_ma20_mega_break.py            # 2023-2026 全打
    D:/anaconda3/envs/vanna312/python.exe l2_signals/validate_ma20_mega_break.py --year 2025
"""
import argparse
import json
import math
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from search_ma20_mega import load_year  # noqa: E402

META = "E:/stock_data/l2_research/signals/ma20_mega_break_2026.meta.json"
OUT_DIR = "E:/stock_data/l2_research/signals"
DISCOVERY_YEAR = 2026  # 发现年：冻结 meta 与明细 CSV 归 export_signal.py 所有，验证器只打分不写
COST = 0.0012
EPS = 1e-6  # float32 边界容差（因子 parquet 为 float32，阈值 6 位圆整）


def binom_p_ge(wins: int, n: int) -> float:
    """P(X >= wins | Binomial(n, 0.5))，胜率>50% 的单侧二项检验。"""
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(wins, n + 1))
    return tail / 2 ** n


def frozen_mask(df: pd.DataFrame, th: dict) -> np.ndarray:
    return (
        (df["MAX5"].to_numpy() <= th["MAX5__le__q20"] + EPS)
        & (df["SUMP20"].to_numpy() >= th["SUMP20__ge__q80"] - EPS)
        & (df["VSUMP20"].to_numpy() > th["VSUMP20__gt__q40"] - EPS)
        & (df["VSUMP20"].to_numpy() < th["VSUMP20__lt__q60"] + EPS)
        & (df["cross_age"].to_numpy() == 0)
    )


def economics(sub: pd.DataFrame, label: str):
    """口径 B：每日等权篮子复利全仓（对照用）。"""
    for gate in (0, 2):
        cnt = sub.groupby("d").size()
        days = cnt[cnt >= gate].index if gate > 0 else cnt.index
        daily = sub[sub["d"].isin(days)].groupby("d")["ret1"].mean()
        if not len(daily):
            continue
        gross = (1 + daily).prod() - 1
        net = (1 + daily - COST).prod() - 1
        dd = (1 + daily).cumprod()
        mdd = float((dd / dd.cummax() - 1).min())
        tag = f"N>={gate}" if gate else "全量日"
        print(f"  [{label}] {tag}: {len(daily)} 日 毛{gross*100:+.1f}% 净{net*100:+.1f}% 最大回撤{mdd*100:.1f}%")


def score_year(year: int, th: dict, meta_signal: str) -> pd.DataFrame | None:
    df = load_year(year)
    base_wr = df["win"].mean()
    m = frozen_mask(df, th)
    sub = df[m].copy()
    n = len(sub)
    if n == 0:
        print(f"\n[{year}] 0 触发")
        return None
    wins = int(sub["win"].sum())
    p = binom_p_ge(wins, n)
    h1, h2 = sub[~sub["h2"]], sub[sub["h2"]]
    print(f"\n[{year}] 池 {len(df):,}(基线 {base_wr*100:.1f}%) → 触发 {n}  wr={sub.win.mean()*100:.1f}%  "
          f"avg={sub.ret1.mean()*100:+.2f}%  二项p={p:.2g}  α={(sub.win.mean()-base_wr)*100:+.1f}pp")
    print(f"  H1 {len(h1):3d} {h1.win.mean()*100:5.1f}%  |  H2 {len(h2):3d} {h2.win.mean()*100:5.1f}%"
          if len(h1) and len(h2) else "  （单半场）")
    print("  --- 分月 ---")
    for mth, g in sub.groupby(sub["d"].dt.to_period("M")):
        print(f"  {mth}  n={len(g):3d}  wr={g.win.mean()*100:5.1f}%  avg={g.ret1.mean()*100:+5.2f}%")
    economics(sub, str(year))

    if year == DISCOVERY_YEAR:
        print("  （发现年：明细/阈值文件归 export_signal.py，此处不覆写）")
        return sub
    out = sub[["d", "stock_code", "close_px", "t1_close", "ret1", "win",
               "MAX5", "SUMP20", "VSUMP20", "nfr_vol", "nfr", "bs", "ddxr", "c1x",
               "ma20_dist", "cross_age"]].copy()
    out["d"] = out["d"].dt.date
    out = out.sort_values("d")
    csv_path = os.path.join(OUT_DIR, f"ma20_mega_break_{year}.csv")
    out.to_csv(csv_path, index=False, encoding="utf-8-sig")
    stats = {
        "signal": f"{meta_signal}_{year}_validation",
        "frozen_thresholds_from": "ma20_mega_break_2026.meta.json",
        "n": int(n), "win_rate": round(float(sub.win.mean()), 4),
        "avg_ret": round(float(sub.ret1.mean()), 5),
        "binom_p": round(p, 6),
        "alpha_vs_pool_pp": round(float(sub.win.mean() - base_wr) * 100, 1),
        "n_h1": int(len(h1)), "wr_h1": round(float(h1.win.mean()), 4) if len(h1) else None,
        "n_h2": int(len(h2)), "wr_h2": round(float(h2.win.mean()), 4) if len(h2) else None,
        "note": "选择过程参考过跨年诊断，非严格样本外（见脚本头声明）",
    }
    json.dump(stats, open(csv_path.replace(".csv", ".meta.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"  → {csv_path}")
    return sub


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=None, help="单年打分；缺省 2023-2026 全打")
    args = ap.parse_args()

    meta = json.load(open(META, encoding="utf-8"))
    th = meta["thresholds_h1_quantiles"]
    print(f"[frozen] 2026-H1 阈值: {th}")

    years = [args.year] if args.year else [2023, 2024, 2025, 2026]
    allsub = {}
    for y in years:
        s = score_year(y, th, meta["signal"])
        if s is not None:
            allsub[y] = s

    if len(allsub) >= 2:
        merged = pd.concat(allsub.values())
        wins, n = int(merged["win"].sum()), len(merged)
        print(f"\n[合计 {min(allsub)}-{max(allsub)}] n={n}  wr={merged.win.mean()*100:.1f}%  "
              f"avg={merged.ret1.mean()*100:+.2f}%  二项p={binom_p_ge(wins, n):.2g}")


if __name__ == "__main__":
    main()
