"""信号研究 v3：低位 × KDJ 原版条件（J vs D + 日线）——LOW20_KDJ_JD。

条件（用户 2026-11-06 原版定义，自策略代码转录）：
  C1 低位：T 收盘 < 过去 30 个交易日（T-1..T-30，不含 T）收盘的 20% 分位（严格满窗）
  K1 周线：T 日所在周（ISO 周，as-of 运行 bar）KDJ J > D
  K2 月线金叉当日：T 日所在月（自然月，as-of 运行 bar）J > D，且 T-1 日 J < D
  K3 日线：T 日日线 KDJ J > D

KDJ(9,3,3) TDX 式（K=D=50 种子，SMA 1/3）；as-of 无未来函数。
考察：T+10 收盘相对 T 收盘涨幅（另报 T+1/T+5）。

价格源（--px-cache，QMT 源，无 2025Q4 洞）：
  daily_px_vadj_2019_2026.parquet   等比前复权（vendor none × 1/累积dr）——主口径
  daily_px_vfront_2019_2026.parquet QMT front 等差前复权——对照（止 2026-09-21；
                                    穿零段行在加载时剔除）

用法：
    D:/anaconda3/envs/vanna312/python.exe l2_signals/low20_kdj_jd.py --tag vadj
    D:/anaconda3/envs/vanna312/python.exe l2_signals/low20_kdj_jd.py --tag vfront
"""
from __future__ import annotations

import argparse
import os

import duckdb
import numpy as np
import pandas as pd

CACHE = "E:/stock_data/l2_research/cache/daily_px_{tag}_2019_2026.parquet"
OUT_TMPL = "E:/stock_data/l2_research/signals/low20_kdj_jd_{tag}_{year}.csv"
YEARS = range(2020, 2027)


def load(tag: str, end: str) -> pd.DataFrame:
    path = CACHE.format(tag=tag)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    con = duckdb.connect()
    df = con.execute(f"""
        SELECT stock_code, d, o, h, l, c
        FROM read_parquet('{path}')
        WHERE d <= DATE '{end}'
    """).fetchdf()
    con.close()
    df["d"] = pd.to_datetime(df["d"])
    return df.sort_values(["stock_code", "d"]).reset_index(drop=True)


def _kdj_chain(rsv: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """K/D 沿有效 RSV 递推（种子 50）。"""
    k = np.full(len(rsv), np.nan)
    d = np.full(len(rsv), np.nan)
    kp = dp = 50.0
    for i in range(len(rsv)):
        if not valid[i]:
            continue
        kp = rsv[i] / 3.0 + kp * 2.0 / 3.0
        dp = kp / 3.0 + dp * 2.0 / 3.0
        k[i], d[i] = kp, dp
    return k, d


def daily_kdj(g: pd.DataFrame) -> pd.DataFrame:
    llv = g["l"].rolling(9, min_periods=9).min()
    hhv = g["h"].rolling(9, min_periods=9).max()
    rng = hhv - llv
    ok = rng.notna().to_numpy()
    rsv = np.where(ok & (rng.to_numpy() > 0),
                   (g["c"].to_numpy() - llv.to_numpy()) / np.where(rng.to_numpy() > 0, rng.to_numpy(), 1.0) * 100.0,
                   50.0)
    k, d = _kdj_chain(rsv, ok)
    return pd.DataFrame({"stock_code": g["stock_code"].to_numpy(), "d": g["d"].to_numpy(),
                         "dk": k, "dd": d, "dj": 3 * k - 2 * d})


def asof_period_kdj(g: pd.DataFrame, keys: list[str], n: int = 9) -> pd.DataFrame:
    """as-of 周期 KDJ（K/D/J），运行 bar 语义同 low20_kdj_cross（无未来函数）。"""
    gg = g.sort_values("d").reset_index(drop=True)
    grp = gg.groupby(keys, sort=False)
    gg["_hr"] = grp["h"].cummax()
    gg["_lr"] = grp["l"].cummin()
    pk = ["stock_code"] + keys
    periods = (gg.groupby(pk, as_index=False, sort=True)
                 .agg(_fl=("_lr", "last"), _fh=("_hr", "last"), _fc=("c", "last"))
                 .sort_values(pk).reset_index(drop=True))
    st = periods["stock_code"].to_numpy()
    llv9 = periods["_fl"].groupby(st).rolling(n, min_periods=n).min().reset_index(level=0, drop=True)
    hhv9 = periods["_fh"].groupby(st).rolling(n, min_periods=n).max().reset_index(level=0, drop=True)
    rng9 = hhv9 - llv9
    valid = rng9.notna().to_numpy()
    frsv = np.where(valid & (rng9.to_numpy() > 0),
                    (periods["_fc"].to_numpy() - llv9.to_numpy()) / np.where(rng9.to_numpy() > 0, rng9.to_numpy(), 1.0) * 100.0,
                    50.0)
    ks, ds = _kdj_chain(frsv, valid)
    periods["_kp"] = pd.Series(ks).groupby(st).shift(1)
    periods["_dp"] = pd.Series(ds).groupby(st).shift(1)
    periods["_pllv"] = (periods["_fl"].groupby(st).shift(1).groupby(st)
                        .rolling(n - 1, min_periods=n - 1).min().reset_index(level=0, drop=True))
    periods["_phhv"] = (periods["_fh"].groupby(st).shift(1).groupby(st)
                        .rolling(n - 1, min_periods=n - 1).max().reset_index(level=0, drop=True))
    gg = gg.merge(periods[pk + ["_pllv", "_phhv", "_kp", "_dp"]], on=pk, how="left")
    gg = gg.sort_values("d").reset_index(drop=True)
    llv_t = np.minimum(gg["_lr"].to_numpy(), gg["_pllv"].to_numpy())
    hhv_t = np.maximum(gg["_hr"].to_numpy(), gg["_phhv"].to_numpy())
    rng_t = hhv_t - llv_t
    ok = ~np.isnan(gg["_pllv"].to_numpy()) & ~np.isnan(gg["_kp"].to_numpy())
    rsv_t = np.where(ok & (rng_t > 0),
                     (gg["c"].to_numpy() - llv_t) / np.where(rng_t > 0, rng_t, 1.0) * 100.0,
                     50.0)
    k_t = rsv_t / 3.0 + gg["_kp"].to_numpy() * 2.0 / 3.0
    d_t = k_t / 3.0 + gg["_dp"].to_numpy() * 2.0 / 3.0
    j_t = 3.0 * k_t - 2.0 * d_t
    return pd.DataFrame({"stock_code": gg["stock_code"].to_numpy(), "d": gg["d"].to_numpy(),
                         "k": np.where(ok, k_t, np.nan),
                         "dd": np.where(ok, d_t, np.nan),
                         "j": np.where(ok, j_t, np.nan)})


def compute(df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    g = df.sort_values(["stock_code", "d"]).reset_index(drop=True)
    # C1（同前两版口径）
    grp = g.groupby("stock_code", sort=False)
    hist = grp["c"].shift(1)
    g["q_hist"] = (hist.groupby(g["stock_code"], sort=False)
                   .rolling(args.window, min_periods=args.window).quantile(args.q)
                   .reset_index(level=0, drop=True))
    g["c1"] = g["q_hist"].notna() & (g["c"] < g["q_hist"])
    # 日线 KDJ
    parts = [daily_kdj(sub) for _, sub in g.groupby("stock_code", sort=False)]
    day = pd.concat(parts, ignore_index=True)
    # 周/月 as-of KDJ
    iso = g["d"].dt.isocalendar()
    wk = asof_period_kdj(
        g.assign(_iy=iso.year.astype("int64").to_numpy(), _iw=iso.week.astype("int64").to_numpy()),
        ["_iy", "_iw"])
    mo = asof_period_kdj(g.assign(_y=g["d"].dt.year.to_numpy(), _m=g["d"].dt.month.to_numpy()),
                         ["_y", "_m"])
    for frame, suf in ((day, "d"), (wk, "w"), (mo, "m")):
        cols = {"k": f"{suf}k", "dd": f"{suf}d", "j": f"{suf}j"}
        g = g.merge(frame.rename(columns=cols), on=["stock_code", "d"], how="left")
    g = g.sort_values(["stock_code", "d"]).reset_index(drop=True)
    grp = g.groupby("stock_code", sort=False)
    g["moj_p"] = grp["mj"].shift(1)
    g["mod_p"] = grp["md"].shift(1)
    kdj_ok = g[["wk", "wd", "wj", "mk", "md", "mj", "dk", "dd", "dj",
                "moj_p", "mod_p"]].notna().all(axis=1)
    g["k1"] = kdj_ok & (g["wj"] > g["wd"])
    # 月线金叉：cross_window=1 即"穿越当日"（原版）；N>1 = 最近 N 个交易日内发生过
    # J 上穿 D（今日仍须 J>D）——吸收触发日漂移（两口径同一次金叉落在不同日）。
    cross_day = kdj_ok & (g["mj"] > g["md"]) & (g["moj_p"] < g["mod_p"])
    w = max(1, int(getattr(args, "cross_window", 1)))
    within = (g.groupby("stock_code", sort=False)
                .apply(lambda sub: sub.rolling(w, min_periods=1).max())
                .reset_index(drop=True)) if False else (
        cross_day.groupby(g["stock_code"], sort=False)
        .transform(lambda s: s.rolling(w, min_periods=1).max()).fillna(False))
    g["k2"] = kdj_ok & (g["mj"] > g["md"]) & within.to_numpy()
    g["k3"] = kdj_ok & (g["dj"] > g["dd"])
    g["kdj"] = g["k1"] & g["k2"] & g["k3"]
    for k in (1, 5, 10):
        g[f"ret{k}"] = grp["c"].shift(-k) / g["c"] - 1.0
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
    ap = argparse.ArgumentParser(description="LOW20_KDJ_JD 低位×KDJ原版条件（J/D+日线）")
    ap.add_argument("--tag", default="vadj", choices=["vadj", "vfront", "vnone"])
    ap.add_argument("--window", type=int, default=30)
    ap.add_argument("--q", type=float, default=0.20)
    ap.add_argument("--end", default="2026-09-21", help="统一截止（front 源止 2026-09-21）")
    ap.add_argument("--cross-window", dest="cross_window", type=int, default=1,
                    help="月线金叉窗：1=穿越当日（原版）；N=最近 N 交易日内穿越过")
    args = ap.parse_args()

    df = load(args.tag, args.end)
    print(f"[load:{args.tag}] rows={len(df):,} stocks={df['stock_code'].nunique():,}  "
          f"{df['d'].min().date()}..{df['d'].max().date()}")
    g = compute(df, args)
    for year in YEARS:
        y = g[(g["d"] >= pd.Timestamp(f"{year}-01-01")) & (g["d"] < pd.Timestamp(f"{year + 1}-01-01"))]
        final = y[y["c1"] & y["kdj"]]
        print(f"== {year} ==")
        print(f"[pool] C1={int(y['c1'].sum()):,}  KDJ4={int(y['kdj'].sum()):,}  "
              f"C1×KDJ4={len(final):,}  有效窗={int(y['q_hist'].notna().sum()):,}")
        stat(final, f"C1×KDJ4 @{year}")
        stat(y[y["kdj"]], "KDJ4 单独")
        stat(y[y["c1"]], "C1 单独")
        out_path = OUT_TMPL.format(tag=args.tag, year=year)
        if args.cross_window > 1:
            out_path = out_path.replace(f"_{year}.csv", f"_w{args.cross_window}_{year}.csv")
        cols = ["d", "stock_code", "c", "q_hist", "wk", "wd", "wj", "mk", "md", "mj",
                "moj_p", "mod_p", "dk", "dd", "dj", "ret1", "ret5", "ret10"]
        out = final.sort_values(["d", "stock_code"])[cols].copy()
        out["d"] = out["d"].dt.date
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        out.to_csv(out_path, index=False, encoding="utf-8-sig", float_format="%.6g")
        print(f"[out] {out_path}  rows={len(out):,}")


if __name__ == "__main__":
    main()
