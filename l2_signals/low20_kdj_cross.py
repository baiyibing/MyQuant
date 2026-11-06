"""信号研究：低位 × KDJ 月线金叉确认（LOW20_KDJ_CROSS 工作名，探索中，未入 catalog）。

条件（2026-11-06 用户定义；条件1 沿用 low20_smallsell_dry 的口径）：
  C1 低位：T 收盘 < 过去 30 个交易日（T-1..T-30，不含 T）收盘的 20% 分位（线性插值，严格满窗）
  K1 周线多头发散：T 日所在周（ISO 周）周线 KDJ J > K
  K2 月线金叉当日：T 日所在月（自然月）月线 J > K，且 T-1 日（上一交易日）月线 J < K

KDJ 口径（TDX 式 9/3/3），**周/月 bar 为逐日 as-of 运行 bar，无未来函数**：
  T 日的周期 bar = 前 8 个已完成周期的最终 bar ∪ 当前周期截至 T 的运行 bar
  （H=截至T最高 L=截至T最低 C=T收）；RSV=(C−LLV9)/(HHV9−LLV9)×100（严格满 9 窗，
  H=L 退化为 50）；K=SMA(RSV,3)、D=SMA(K,3)（沿已完成周期最终 bar 递推，种子 50），
  J=3K−2D；当前周期内逐日用运行 bar 重估 K/D/J（行情软件日图上周期 KDJ 的演化语义）。
  ⚠ v1（2026-11-06 上午）曾误用完整周期 bar（月末 H/L/C 映射到月内每天），月线金叉
  只在每月首日触发且用到整月未来数据——结果作废，见 docs/l2_signals 研究记录 v2。

考察：T+10 收盘相对 T 收盘涨幅（另报 T+1/T+5 上下文；按票自身交易日历）。

烧入说明：价格缓存自 2019-12 起 → 周线 KDJ 约 2020-03 起、月线约 2020-09 起有效。

取数（全 E: SSD 缓存，仅需价格，不碰 B 层与 J: 机械盘）：
  E:/stock_data/l2_research/cache/daily_px_2019_2026.parquet（core rollup OHLC 五列提取）

用法：
    D:/anaconda3/envs/vanna312/python.exe l2_signals/low20_kdj_cross.py
"""
from __future__ import annotations

import argparse
import os

import duckdb
import numpy as np
import pandas as pd

PX_E = "E:/stock_data/l2_research/cache/daily_px_2019_2026.parquet"
PX_J = ("J:/l2_lake/rollup/daily_stock/version=l2-daily-v3/"
        "params=a2e3a427af892982d0ce/date=*/part.parquet")
PX_OVERRIDE: str | None = None   # --px-cache 注入（等比复权缓存）
OUT_TMPL = "E:/stock_data/l2_research/signals/low20_kdj_cross_{year}.csv"
YEARS = range(2020, 2027)


def px_path() -> str:
    for p in (PX_OVERRIDE, PX_E, PX_J):
        if p and os.path.exists(p):
            if p.startswith("J:"):
                print(f"[warn] 价格走 J: 机械盘回退: {p}")
            return p
    raise FileNotFoundError("价格源不存在（E: 缓存与 J: rollup 均无）")


def load() -> pd.DataFrame:
    con = duckdb.connect()
    df = con.execute(f"""
        SELECT stock_code, d,
               CAST(high_px AS DOUBLE) high_px, CAST(low_px AS DOUBLE) low_px,
               CAST(close_px AS DOUBLE) close_px
        FROM read_parquet('{px_path()}', hive_partitioning=false)
        ORDER BY stock_code, d
    """).fetchdf()
    con.close()
    return df


def _asof_period_kdj(g: pd.DataFrame, pkeys: list[str], n: int = 9,
                     tag: str = "wk") -> pd.DataFrame:
    """逐日 as-of 周期 KDJ（无未来函数），返回 stock_code/d/{tag}_k/{tag}_j。

    g 需按 (stock_code, d) 排序。当前周期为该票第 <n 个周期时输出 NaN。
    """
    pk = ["stock_code"] + pkeys
    gg = g.sort_values(["stock_code", "d"], kind="mergesort").reset_index(drop=True)
    grp = gg.groupby(pk, sort=False)
    gg["_h_run"] = grp["high_px"].cummax()   # 当前周期截至 T 的最高
    gg["_l_run"] = grp["low_px"].cummin()    # 当前周期截至 T 的最低

    # 周期最终 bar（每周期最后一日的运行值 = 该周期完整 H/L/C）
    periods = (gg.groupby(pk, as_index=False, sort=True)
                 .agg(_fl=("_l_run", "last"), _fh=("_h_run", "last"),
                      _fc=("close_px", "last")))
    periods = periods.sort_values(pk).reset_index(drop=True)
    st = periods["stock_code"].to_numpy()
    sgrp = periods["stock_code"]

    # 最终 bar 的 RSV（严格 n 窗，头 n−1 个周期 NaN）
    llv9 = periods["_fl"].groupby(sgrp, sort=False).rolling(n, min_periods=n).min().reset_index(level=0, drop=True)
    hhv9 = periods["_fh"].groupby(sgrp, sort=False).rolling(n, min_periods=n).max().reset_index(level=0, drop=True)
    rng9 = hhv9 - llv9
    frsv = np.where(rng9.notna() & (rng9 > 0),
                    (periods["_fc"] - llv9) / np.where(rng9 > 0, rng9, 1.0) * 100.0,
                    np.where(rng9.notna(), 50.0, np.nan))

    # K/D 状态沿最终 bar 递推（K=D=50 种子；逐票重置）
    ks = np.full(len(periods), np.nan)
    ds = np.full(len(periods), np.nan)
    kp, dp, prev_stock = 50.0, 50.0, None
    for i in range(len(periods)):
        if st[i] != prev_stock:
            kp, dp, prev_stock = 50.0, 50.0, st[i]
        v = frsv[i]
        if np.isnan(v):
            continue
        kp = v / 3.0 + kp * 2.0 / 3.0
        dp = kp / 3.0 + dp * 2.0 / 3.0
        ks[i], ds[i] = kp, dp

    # 日级输入：前 n−1 个已完成周期的 LLV/HHV + 上一完成周期后的 K/D 状态
    prev_fl = periods["_fl"].groupby(sgrp, sort=False).shift(1)
    prev_fh = periods["_fh"].groupby(sgrp, sort=False).shift(1)
    periods["_pllv"] = (prev_fl.groupby(sgrp, sort=False)
                        .rolling(n - 1, min_periods=n - 1).min().reset_index(level=0, drop=True))
    periods["_phhv"] = (prev_fh.groupby(sgrp, sort=False)
                        .rolling(n - 1, min_periods=n - 1).max().reset_index(level=0, drop=True))
    periods["_kp"] = pd.Series(ks).groupby(sgrp, sort=False).shift(1)
    periods["_dp"] = pd.Series(ds).groupby(sgrp, sort=False).shift(1)

    gg = gg.merge(periods[pk + ["_pllv", "_phhv", "_kp", "_dp"]], on=pk, how="left")
    gg = gg.sort_values(["stock_code", "d"], kind="mergesort").reset_index(drop=True)
    llv_t = np.minimum(gg["_l_run"].to_numpy(), gg["_pllv"].to_numpy())
    hhv_t = np.maximum(gg["_h_run"].to_numpy(), gg["_phhv"].to_numpy())
    rng_t = hhv_t - llv_t
    ok = ~np.isnan(gg["_pllv"].to_numpy()) & ~np.isnan(gg["_kp"].to_numpy())
    rsv_t = np.where(ok & (rng_t > 0),
                     (gg["close_px"].to_numpy() - llv_t) / np.where(rng_t > 0, rng_t, 1.0) * 100.0,
                     50.0)
    k_t = rsv_t / 3.0 + gg["_kp"].to_numpy() * 2.0 / 3.0
    d_t = k_t / 3.0 + gg["_dp"].to_numpy() * 2.0 / 3.0
    j_t = 3.0 * k_t - 2.0 * d_t
    out = pd.DataFrame({
        "stock_code": gg["stock_code"], "d": gg["d"],
        f"{tag}_k": np.where(ok, k_t, np.nan),
        f"{tag}_j": np.where(ok, j_t, np.nan),
    })
    return out


def compute(df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    g = df.sort_values(["stock_code", "d"], kind="mergesort").reset_index(drop=True)

    # C1 低位（同 low20_smallsell_dry：T-1..T-30 不含 T，严格满窗）
    grp = g.groupby("stock_code", sort=False)
    hist_close = grp["close_px"].shift(1)
    g["q_hist"] = (hist_close.groupby(g["stock_code"], sort=False)
                   .rolling(args.window, min_periods=args.window).quantile(args.q)
                   .reset_index(level=0, drop=True))
    g["c1"] = g["q_hist"].notna() & g["close_px"].notna() & (g["close_px"] < g["q_hist"])

    # 周线 / 月线 as-of KDJ（无未来函数）
    iso = g["d"].dt.isocalendar()
    g["_iy"], g["_iw"] = iso.year.astype("int64"), iso.week.astype("int64")
    g["_y"], g["_m"] = g["d"].dt.year.astype("int64"), g["d"].dt.month.astype("int64")

    wk = _asof_period_kdj(g, ["_iy", "_iw"], tag="wk")
    mo = _asof_period_kdj(g, ["_y", "_m"], tag="mo")
    g = g.merge(wk, on=["stock_code", "d"], how="left")
    g = g.merge(mo, on=["stock_code", "d"], how="left")
    g = g.sort_values(["stock_code", "d"], kind="mergesort").reset_index(drop=True)
    grp = g.groupby("stock_code", sort=False)
    g["mo_k_p"] = grp["mo_k"].shift(1)   # T-1 日月线值（同月内逐日演化，或上月末值）
    g["mo_j_p"] = grp["mo_j"].shift(1)

    kdj_ok = (g[["wk_k", "wk_j", "mo_k", "mo_j", "mo_k_p", "mo_j_p"]].notna().all(axis=1))
    g["k1"] = kdj_ok & (g["wk_j"] > g["wk_k"])                       # 周线 J>K
    g["k2"] = kdj_ok & (g["mo_j"] > g["mo_k"]) & (g["mo_j_p"] < g["mo_k_p"])  # 月线金叉当日
    g["kdj"] = g["k1"] & g["k2"]

    # 前瞻收益
    for k in (1, 5, 10):
        g[f"ret{k}"] = grp["close_px"].shift(-k) / g["close_px"] - 1.0
    return g


def stat(pool: pd.DataFrame, label: str) -> None:
    print(f"  [{label}] n={len(pool):,}")
    for k in (1, 5, 10):
        r = pool[f"ret{k}"].dropna()
        if not len(r):
            print(f"   T+{k:<2}      —")
            continue
        print(f"   T+{k:<2} n={len(r):>8,}  mean={r.mean()*100:+6.2f}%  med={r.median()*100:+6.2f}%  "
              f"win={(r > 0).mean()*100:5.1f}%  p25={r.quantile(.25)*100:+6.2f}%  p75={r.quantile(.75)*100:+6.2f}%")


def main() -> None:
    ap = argparse.ArgumentParser(description="LOW20_KDJ_CROSS 低位×KDJ月线金叉假设检验（as-of 无未来函数）")
    ap.add_argument("--window", type=int, default=30)
    ap.add_argument("--q", type=float, default=0.20)
    ap.add_argument("--px-cache", dest="px_cache", default="",
                    help="价格缓存覆盖（等比复权：daily_px_adj_2019_2026.parquet）")
    ap.add_argument("--out-tmpl", dest="out_tmpl", default=OUT_TMPL)
    args = ap.parse_args()
    if args.px_cache:
        global PX_OVERRIDE
        PX_OVERRIDE = args.px_cache

    df = load()
    print(f"[load] rows={len(df):,} stocks={df['stock_code'].nunique():,}  "
          f"{df['d'].min().date()}..{df['d'].max().date()}")
    g = compute(df, args)

    for year in YEARS:
        y = g[(g["d"] >= pd.Timestamp(f"{year}-01-01")) & (g["d"] < pd.Timestamp(f"{year + 1}-01-01"))]
        head = y[y["c1"] & y["kdj"]]
        print(f"== {year} ==")
        print(f"[pool] C1={int(y['c1'].sum()):,}  KDJ={int(y['kdj'].sum()):,}  "
              f"C1×KDJ={len(head):,}  有效窗={int(y['q_hist'].notna().sum()):,}")
        if len(head):
            dom = head["d"].dt.day.value_counts()
            print(f"  信号日分布: 月内日 ≤10:{int(head['d'].dt.day.le(10).sum())}  11-20:{int(head['d'].dt.day.between(11, 20).sum())}  >20:{int(head['d'].dt.day.gt(20).sum())}")
        stat(head, f"C1×KDJ @{year}")
        stat(y[y["kdj"]], "KDJ 单独（对照）")
        stat(y[y["c1"]], "C1 单独（对照）")
        stat(y[y["q_hist"].notna()], "BASE 全体有效窗（对照）")

        out_path = args.out_tmpl.format(year=year)
        cols = ["d", "stock_code", "close_px", "q_hist", "wk_k", "wk_j", "mo_k", "mo_j",
                "mo_k_p", "mo_j_p", "ret1", "ret5", "ret10"]
        out = head.sort_values(["d", "stock_code"])[cols].copy()
        out["d"] = out["d"].dt.date
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        out.to_csv(out_path, index=False, encoding="utf-8-sig", float_format="%.6g")
        print(f"[out] {out_path}  rows={len(out):,}")


if __name__ == "__main__":
    main()
