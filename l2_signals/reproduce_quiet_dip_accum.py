"""复现 QUIET_DIP_ACCUM（缩量阴线吸筹）；默认对拍 2026 黄金 CSV。

条件（定稿 docs/l2_signals/2026-11-04-quiet-dip-accum-signal-card.md）：
  C1 阴线守 MA5：开≤昨收×1.02 且 高≤昨收×1.04 且 收<昨收 且 收<开 且 收>MA5
                 （MA5 = 含当日的 5 日收盘均）
  C2 吸筹：      (buyord10w_vol − saleord10w_vol) / freeFloatCapital > 2%
  C3 无暴涨：    T-1 收盘涨幅（相对 T-2 收）≤ 5%
  C4 缩量小阳：  T-1 收>开 且 (高−低)/T-1收 < 5%

用法：
    D:/anaconda3/envs/vanna312/python.exe l2_signals/reproduce_quiet_dip_accum.py
    D:/anaconda3/envs/vanna312/python.exe l2_signals/reproduce_quiet_dip_accum.py --year 2025
"""
from __future__ import annotations

import argparse
import os

import duckdb
import pandas as pd

ROLLUP = "J:/l2_lake/rollup/daily_stock/version=l2-daily-v3/params=a2e3a427af892982d0ce/date=*/part.parquet"
FF = "E:/stock_data/free_float_shares.parquet"
GOLD_2026 = "E:/stock_data/quiet_dip_accum_2026.csv"
BLAYER_TMPL = "J:/l2_lake/rollup/bigorder_daily_{year}.parquet"
OUT_TMPL = "E:/stock_data/l2_research/signals/quiet_dip_accum_{year}.csv"


def load(year: int) -> pd.DataFrame:
    blayer = BLAYER_TMPL.format(year=year)
    if not os.path.exists(blayer):
        raise FileNotFoundError(f"B 层不存在: {blayer}")
    # 窗口预热：前一年 12 月起读价，保证年初 MA5 / lag 满窗
    px_start = f"{year - 1}-12-01"
    gap = f"{year}-01-02"
    con = duckdb.connect()
    # B 层覆盖范围（2025 可能缺 Q4）
    dmin, dmax, nrow = con.execute(
        f"SELECT min(d), max(d), count(*) FROM read_parquet('{blayer}')"
    ).fetchone()
    dmax_s = pd.Timestamp(dmax).strftime("%Y-%m-%d")
    print(f"[blayer] {blayer}  rows={nrow:,}  {dmin}..{dmax}")
    return con.execute(f"""
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
        ),
        big AS (
          SELECT CAST(d AS DATE) d, stock_code,
                 buyord10w_vol bov, saleord10w_vol sov,
                 buyord10w_amt bam, saleord10w_amt sam
          FROM read_parquet('{blayer}')
        ),
        ff AS (
          SELECT stock_code, CAST(m_timetag AS DATE) d, freeFloatCapital ffv
          FROM read_parquet('{FF}') WHERE freeFloatCapital > 0
        )
        SELECT p.*, b.bov, b.sov, b.bam, b.sam, f.ffv
        FROM px p
        LEFT JOIN big b USING (stock_code, d)
        ASOF LEFT JOIN ff f ON p.stock_code = f.stock_code AND p.d >= f.d
        WHERE p.d >= DATE '{gap}'
          AND p.d <= DATE '{dmax_s}'
          AND p.t1_close IS NOT NULL
          AND p.pc IS NOT NULL AND p.pc2 IS NOT NULL
          AND p.po IS NOT NULL
          AND f.ffv > 0
          AND b.bov IS NOT NULL
    """).fetchdf()


def apply_signal(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["d"] = pd.to_datetime(df["d"]).dt.normalize()
    nfr = (df["bov"] - df["sov"]) / df["ffv"]
    ret_p = df["pc"] / df["pc2"] - 1.0          # T-1 收盘涨幅
    amp_p = (df["ph"] - df["pl"]) / df["pc"]    # T-1 震幅 / T-1 收

    c1 = (
        (df["open_px"] <= df["pc"] * 1.02)
        & (df["high_px"] <= df["pc"] * 1.04)
        & (df["close_px"] < df["pc"])
        & (df["close_px"] < df["open_px"])
        & (df["close_px"] > df["ma5"])
    )
    c2 = nfr > 0.02
    c3 = ret_p <= 0.05
    c4 = (df["pc"] > df["po"]) & (amp_p < 0.05)

    out = df[c1 & c2 & c3 & c4].copy()
    out["nfr"] = nfr[c1 & c2 & c3 & c4]
    out["ret_p"] = ret_p[c1 & c2 & c3 & c4]
    out["amp_p"] = amp_p[c1 & c2 & c3 & c4]
    out["ret1"] = out["t1_close"] / out["close_px"] - 1.0
    out["win"] = (out["t1_close"] > out["close_px"]).astype(int)
    return out.sort_values(["d", "stock_code"])


def check_gold(sub: pd.DataFrame) -> None:
    if not os.path.exists(GOLD_2026):
        print(f"[warn] 黄金 CSV 不存在: {GOLD_2026}")
        return
    gold = pd.read_csv(GOLD_2026)
    gold["d"] = pd.to_datetime(gold["日期"]).dt.normalize()
    gold["stock_code"] = gold["股票代码"]
    gset = set(zip(gold["d"], gold["stock_code"]))
    sset = set(zip(sub["d"], sub["stock_code"]))
    print(
        f"[gold] n={len(gset)}  repro={len(sset)}  "
        f"hit={len(gset & sset)}  miss={len(gset - sset)}  extra={len(sset - gset)}"
    )
    if gset == sset:
        print("[gold] EXACT match")
    elif gset - sset:
        print("[gold] miss sample:", sorted(gset - sset)[:5])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    out_path = args.out or OUT_TMPL.format(year=args.year)

    df = load(args.year)
    sub = apply_signal(df)
    n = len(sub)
    if n == 0:
        print(f"[QUIET_DIP_ACCUM @{args.year}] 0 触发")
        return
    wr, avg = sub["win"].mean(), sub["ret1"].mean()
    h2 = sub["d"] >= pd.Timestamp(f"{args.year}-07-01")
    h1, h2s = sub[~h2], sub[h2]
    print(f"[QUIET_DIP_ACCUM @{args.year}] n={n}  T+1 wr={wr*100:.1f}%  avg={avg*100:+.2f}%")
    if len(h1):
        print(f"  H1 n={len(h1)}  wr={h1.win.mean()*100:.1f}%  avg={h1.ret1.mean()*100:+.2f}%")
    if len(h2s):
        print(f"  H2 n={len(h2s)}  wr={h2s.win.mean()*100:.1f}%  avg={h2s.ret1.mean()*100:+.2f}%")
    print("  --- 分月 ---")
    for mth, g in sub.groupby(sub["d"].dt.to_period("M")):
        print(f"  {mth}  n={len(g):3d}  wr={g.win.mean()*100:5.1f}%  avg={g.ret1.mean()*100:+.2f}%")

    if args.year == 2026:
        check_gold(sub)

    cols = [
        "d", "stock_code", "close_px", "open_px", "t1_close", "ret1", "win",
        "nfr", "ret_p", "amp_p", "ma5", "bov", "sov", "ffv",
    ]
    out = sub[cols].copy()
    out["d"] = out["d"].dt.date
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"[out] {out_path}")


if __name__ == "__main__":
    main()
