"""STAB_LOW_TREND 跨年样本外验证：冻结 2026-H1 阈值 → 2025 池打分。

阈值与池定义完全冻结自 2026（meta.json），2025 只做打分，不重新拟合——
这是多重检验问题的最终裁判。输出 2025 信号明细 CSV + 分半/分月稳定性。

用法：
    D:/anaconda3/envs/vanna312/python.exe l2_signals/validate_cross_year.py
"""
import argparse
import json
import os
import sys

import duckdb
import numpy as np
import pandas as pd

A158 = "E:/stock_data/l2_research/alpha158_daily.parquet"
FF = "E:/stock_data/free_float_shares.parquet"
ROLLUP = "J:/l2_lake/rollup/daily_stock/version=l2-daily-v3/params=a2e3a427af892982d0ce/date=*/part.parquet"
META = "E:/stock_data/l2_research/signals/stab_low_trend_2026.meta.json"

YEAR = 2025
BLAYER = "J:/l2_lake/rollup/bigorder_daily_{YEAR}.parquet"
GAP = "{YEAR}-01-02"
MID = "{YEAR}-07-01"
OUT_CSV = "E:/stock_data/l2_research/signals/stab_low_trend_{YEAR}.csv"
COST = 0.0012


def load_pool(year_gap: str, blayer: str = None) -> pd.DataFrame:
    blayer = blayer or BLAYER.format(YEAR=YEAR)
    con = duckdb.connect()
    big = con.execute(f"""
        SELECT CAST(d AS DATE) d, stock_code,
               buyord10w_vol bov, saleord10w_vol sov,
               buyord10w_amt bam, saleord10w_amt sam,
               buyord10w_active_amt baam, saleord10w_active_amt saam,
               bov / lag(bov) OVER (PARTITION BY stock_code ORDER BY d) c1x,
               CASE WHEN lag(bov) OVER (PARTITION BY stock_code ORDER BY d) > 0 THEN 1 ELSE 0 END prev_bov_pos
        FROM read_parquet('{blayer}') ORDER BY stock_code, d""").fetchdf()
    pool = big[(big["c1x"] >= 2.0) & (big["prev_bov_pos"] == 1) & (big["d"] >= year_gap)].copy()

    px = con.execute(f"""
        SELECT stock_code, CAST(d AS DATE) d, close_px, total_amt,
               lead(close_px) OVER (PARTITION BY stock_code ORDER BY d) t1_close
        FROM read_parquet('{ROLLUP}', hive_partitioning=false)
        WHERE d >= DATE '{year_gap}' ORDER BY stock_code, d""").fetchdf()
    df = pool.merge(px, on=["stock_code", "d"], how="left")

    fact = pd.read_parquet(A158)
    fact["d"] = pd.to_datetime(fact["d"])
    fact = fact[fact["d"] >= pd.Timestamp(year_gap)]
    df["d"] = pd.to_datetime(df["d"])
    df = df.merge(fact, on=["stock_code", "d"], how="left")

    df = df[df["t1_close"].notna() & df["close_px"].notna()].copy()
    df["win"] = (df["t1_close"] > df["close_px"]).astype(int)
    df["ret1"] = df["t1_close"] / df["close_px"] - 1
    n_all = len(df)
    df = df[df["KMID"] != 0].copy()  # 可交易过滤（与 2026 同口径）
    df["h2"] = df["d"] >= pd.Timestamp(str(MID))
    print(f"[pool] C1 {n_all:,} → 可交易 {len(df):,}")
    return df


def score(df: pd.DataFrame, th: dict, label: str):
    m = (df["IMIN10"] <= th["IMIN10__le__q20"]) & \
        (df["QTLD30"] >= th["QTLD30__ge__q80"]) & \
        (df["RSQR5"] >= th["RSQR5__ge__q80"])
    sub = df[m].copy()
    if not len(sub):
        print(f"[{label}] 0 触发")
        return sub
    h1, h2 = sub[~sub["h2"]], sub[sub["h2"]]

    def row(name, s):
        return (name, len(s), s["win"].mean() * 100, s["ret1"].mean() * 100)

    print(f"\n[{label}] 触发 {len(sub)} 次")
    print(f"  全期     n={len(sub):4d}  wr={sub.win.mean()*100:5.1f}%  avg={sub.ret1.mean()*100:+5.2f}%")
    print(f"  上半(H1) n={len(h1):4d}  wr={h1.win.mean()*100:5.1f}%  avg={h1.ret1.mean()*100:+5.2f}%" if len(h1) else "  上半(H1) n=0")
    print(f"  下半(H2) n={len(h2):4d}  wr={h2.win.mean()*100:5.1f}%  avg={h2.ret1.mean()*100:+5.2f}%" if len(h2) else "  下半(H2) n=0")
    print("  --- 分月 ---")
    for mth, g in sub.groupby(sub["d"].dt.to_period("M")):
        print(f"  {mth}  n={len(g):3d}  wr={g.win.mean()*100:5.1f}%  avg={g.ret1.mean()*100:+5.2f}%")
    return sub


def economics(sub: pd.DataFrame, label: str, min_n: int = 0):
    """口径 B（每日等权篮子复利，全仓）+ N>=3 门槛变体。"""
    for gate in (0, min_n):
        cnt = sub.groupby("d").size()
        days = cnt[cnt >= gate].index if gate > 0 else cnt.index
        d = sub[sub["d"].isin(days)].groupby("d")["ret1"].mean()
        if not len(d):
            continue
        gross = (1 + d).prod() - 1
        net = (1 + d - COST).prod() - 1
        tag = f"N>={gate}" if gate else "全量日"
        print(f"  [{label}] {tag}: {len(d)} 个交易日  毛 {gross*100:+.2f}%  净 {net*100:+.2f}%")


def main():
    global GAP, MID, OUT_CSV, BLAYER
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2025)
    args = ap.parse_args()
    GAP = GAP.format(YEAR=args.year)
    MID = MID.format(YEAR=args.year)
    OUT_CSV = OUT_CSV.format(YEAR=args.year)
    BLAYER = BLAYER.format(YEAR=args.year)

    meta = json.load(open(META, encoding="utf-8"))
    th = meta["thresholds_h1_quantiles"]
    print(f"[frozen] 2026-H1 阈值: {th}")

    df = load_pool(GAP)
    h1b = df[~df["h2"]]["win"].mean() * 100
    h2b = df[df["h2"]]["win"].mean() * 100
    print(f"[baseline] C1 可交易池 T+1 胜率: H1 {h1b:.1f}% / H2 {h2b:.1f}%")

    sub = score(df, th, f"STAB_LOW_TREND @{args.year}（冻结阈值）")
    if len(sub):
        print("  --- 朴素经济性（口径B，仅对照）---")
        economics(sub, str(args.year), min_n=3)

        out = sub[["d", "stock_code", "close_px", "t1_close", "ret1", "win",
                   "IMIN10", "QTLD30", "RSQR5"]].copy()
        out["d"] = out["d"].dt.date
        out = out.sort_values("d")
        out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
        stats = {
            "signal": "STAB_LOW_TREND_2025_validation",
            "frozen_thresholds_from": "stab_low_trend_2026.meta.json",
            "n": int(len(sub)), "win_rate": round(float(sub.win.mean()), 4),
            "avg_ret": round(float(sub.ret1.mean()), 5),
            "n_h1": int((~sub.h2).sum()), "wr_h1": round(float(sub[~sub.h2].win.mean()), 4),
            "n_h2": int(sub.h2.sum()), "wr_h2": round(float(sub[sub.h2].win.mean()), 4),
        }
        json.dump(stats, open(OUT_CSV.replace(".csv", ".meta.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"[out] {OUT_CSV}")


if __name__ == "__main__":
    main()
