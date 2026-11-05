"""复现 QUIET_DIP_TECH（C1+C4 纯技术：昨小阳 + 今日阴线守 MA5）。

口径与 QUIET_DIP_ACCUM 的 C1/C4 相同（定义卡），不含 C2/C3、不读大单。

注意：交接宣称「805 次 / 67.8%」用本口径在 2026 全市场复现为约 4.1 万次 / ~50%，
对不上；C1+C3+C4 ≈ 4.0 万 / ~50% 才接近交接另一行（38073 / 50.6%）。
本脚本按可执行定义跑，不以 805 为准。

用法：
    D:/anaconda3/envs/vanna312/python.exe l2_signals/reproduce_quiet_dip_tech.py --year 2025
    D:/anaconda3/envs/vanna312/python.exe l2_signals/reproduce_quiet_dip_tech.py --year 2026
"""
from __future__ import annotations

import argparse
import os

import duckdb
import pandas as pd

ROLLUP = "J:/l2_lake/rollup/daily_stock/version=l2-daily-v3/params=a2e3a427af892982d0ce/date=*/part.parquet"
OUT_TMPL = "E:/stock_data/l2_research/signals/quiet_dip_tech_{year}.csv"


def load(year: int) -> pd.DataFrame:
    px_start = f"{year - 1}-12-01"
    gap = f"{year}-01-02"
    con = duckdb.connect()
    df = con.execute(f"""
        WITH px AS (
          SELECT stock_code, CAST(d AS DATE) d,
                 open_px, high_px, low_px, close_px,
                 lag(open_px)  OVER (PARTITION BY stock_code ORDER BY d) po,
                 lag(high_px)  OVER (PARTITION BY stock_code ORDER BY d) ph,
                 lag(low_px)   OVER (PARTITION BY stock_code ORDER BY d) pl,
                 lag(close_px) OVER (PARTITION BY stock_code ORDER BY d) pc,
                 lag(close_px, 2) OVER (PARTITION BY stock_code ORDER BY d) pc2,
                 lead(close_px) OVER (PARTITION BY stock_code ORDER BY d) t1_close,
                 avg(close_px) OVER (
                   PARTITION BY stock_code ORDER BY d
                   ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
                 ) ma5
          FROM read_parquet('{ROLLUP}', hive_partitioning=false)
          WHERE d >= DATE '{px_start}'
        )
        SELECT * FROM px
        WHERE d >= DATE '{gap}' AND d < DATE '{year + 1}-01-01'
          AND t1_close IS NOT NULL
          AND pc IS NOT NULL AND po IS NOT NULL
          AND ph IS NOT NULL AND pl IS NOT NULL
          AND pc2 IS NOT NULL AND ma5 IS NOT NULL
    """).fetchdf()
    df["d"] = pd.to_datetime(df["d"]).dt.normalize()
    print(f"[price] {year} rows={len(df):,}  {df.d.min().date()}..{df.d.max().date()}")
    return df


def apply_signal(df: pd.DataFrame) -> pd.DataFrame:
    c1 = (
        (df["open_px"] <= df["pc"] * 1.02)
        & (df["high_px"] <= df["pc"] * 1.04)
        & (df["close_px"] < df["pc"])
        & (df["close_px"] < df["open_px"])
        & (df["close_px"] > df["ma5"])
    )
    amp = (df["ph"] - df["pl"]) / df["pc"]
    c4 = (df["pc"] > df["po"]) & (amp < 0.05)
    out = df[c1 & c4].copy()
    out["amp_p"] = amp[c1 & c4]
    out["ret_p"] = (df["pc"] / df["pc2"] - 1.0)[c1 & c4]
    out["ret1"] = out["t1_close"] / out["close_px"] - 1.0
    out["win"] = (out["t1_close"] > out["close_px"]).astype(int)
    return out.sort_values(["d", "stock_code"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    out_path = args.out or OUT_TMPL.format(year=args.year)

    sub = apply_signal(load(args.year))
    n = len(sub)
    if n == 0:
        print(f"[QUIET_DIP_TECH @{args.year}] 0 触发")
        return
    h2 = sub["d"] >= pd.Timestamp(f"{args.year}-07-01")
    h1, h2s = sub[~h2], sub[h2]
    print(
        f"[QUIET_DIP_TECH @{args.year}] n={n:,}  "
        f"wr={sub.win.mean()*100:.1f}%  avg={sub.ret1.mean()*100:+.2f}%"
    )
    if len(h1):
        print(f"  H1 n={len(h1):,}  wr={h1.win.mean()*100:.1f}%  avg={h1.ret1.mean()*100:+.2f}%")
    if len(h2s):
        print(f"  H2 n={len(h2s):,}  wr={h2s.win.mean()*100:.1f}%  avg={h2s.ret1.mean()*100:+.2f}%")
    print("  --- 分月 ---")
    for mth, g in sub.groupby(sub["d"].dt.to_period("M")):
        print(f"  {mth}  n={len(g):5d}  wr={g.win.mean()*100:5.1f}%  avg={g.ret1.mean()*100:+.2f}%")

    cols = [
        "d", "stock_code", "open_px", "high_px", "low_px", "close_px",
        "t1_close", "ret1", "win", "ma5", "ret_p", "amp_p",
    ]
    out = sub[cols].copy()
    out["d"] = out["d"].dt.date
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"[out] {out_path}")


if __name__ == "__main__":
    main()
