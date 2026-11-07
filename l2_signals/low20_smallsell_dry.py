"""信号研究：低位 × 小卖单枯竭（工作名 LOW20_SMALLSELL_DRY，探索中，未入 catalog）。

条件（2026-11-06 用户定义）：
  C1 低位：T 日收盘价 < 过去 30 个交易日收盘价的 20% 分位（线性插值）
  C2 小卖枯竭：A = 过去 30 个交易日小卖单（单笔委托合计额 < 10 万元，B 层
     saleordsml_amt）累加值 / 30；T 日小卖单额 < 0.5 × A
  考察：T+5..T+10 各期收盘价相对 T 日收盘的涨幅（另报窗口内 max/min）

口径默认（--include-t 可切含 T 窗口）：
  - 「过去 30 个交易日」= T-1..T-30（不含 T）：与「T 日 …」对举，取不含 T 的历史窗；
  - 严格满窗：窗口 30 个交易日全部有 B 层小卖额（min_periods=window），停牌/缺数即无效；
  - 分位 = pandas rolling.quantile 线性插值（与 alpha158_build 的 Quantile 语义一致）；
  - 前瞻 = 该票第 k 个后续交易日收盘 / T 收盘 - 1（按票自身交易日历）。

取数（全 E: SSD 缓存；J: 机械盘只作回退并打警告）：
  B 层 v2（18 列） E:/stock_data/l2_research/cache/bigorder_daily_{year}.parquet
    ← J:/l2_lake/rollup/bigorder_daily_{year}.parquet（2026-11-06 v2 重算件副本）
  日线收盘        E:/stock_data/l2_research/cache/daily_px_2019_2026.parquet
    ← core rollup OHLC 五列提取（2019-12-01 起，7.54M 行）

用法：
    D:/anaconda3/envs/vanna312/python.exe l2_signals/low20_smallsell_dry.py --year 2026
    D:/anaconda3/envs/vanna312/python.exe l2_signals/low20_smallsell_dry.py --year 2020
    （2025 B 层截至 09-25；2020 缺 2019 预热，信号约从 2020-02 起有效）
"""
from __future__ import annotations

import argparse
import os

import duckdb
import pandas as pd

CACHE = "E:/stock_data/l2_research/cache"
BLAYER_E = CACHE + "/bigorder_daily_{year}.parquet"
BLAYER_J = "J:/l2_lake/rollup/bigorder_daily_{year}.parquet"
PX_E = CACHE + "/daily_px_2019_2026.parquet"
PX_J = ("J:/l2_lake/rollup/daily_stock/version=l2-daily-v3/"
        "params=a2e3a427af892982d0ce/date=*/part.parquet")
PX_OVERRIDE: str | None = None   # --px-cache 注入（如等比复权缓存 daily_px_adj_2019_2026.parquet）
OUT_TMPL = "E:/stock_data/l2_research/signals/low20_smallsell_dry_{year}.csv"


def _existing(*paths: str) -> str | None:
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


def blayer_path(year: int) -> str:
    p = _existing(BLAYER_E.format(year=year), BLAYER_J.format(year=year))
    if p is None:
        raise FileNotFoundError(f"B 层 {year} 不存在（E: 缓存与 J: 均无）")
    if p.startswith("J:"):
        print(f"[warn] {year} B 层走 J: 机械盘回退: {p}")
    return p


def px_path() -> str:
    p = _existing(PX_OVERRIDE, PX_E, PX_J)
    if p is None:
        raise FileNotFoundError("价格源不存在（E: 缓存与 J: rollup 均无）")
    if p.startswith("J:"):
        print(f"[warn] 价格走 J: 机械盘回退: {p}")
    return p


def load(year: int, warm_start: str) -> pd.DataFrame:
    """价 × B 层内连接（都存在的日子 = 该票实际交易日），含前一年 11 月起预热。"""
    bl_files = [blayer_path(y) for y in (year - 1, year) if _exists_quiet(y)]
    if not bl_files:
        raise FileNotFoundError(f"{year} 及 {year - 1} 的 B 层都不存在")
    bl_list = ", ".join(f"'{p}'" for p in bl_files)
    con = duckdb.connect()
    df = con.execute(f"""
        WITH px AS (
          SELECT stock_code, d, CAST(close_px AS DOUBLE) close_px
          FROM read_parquet('{px_path()}', hive_partitioning=false)
          WHERE d >= DATE '{warm_start}'
        ),
        big AS (
          SELECT stock_code, d, CAST(saleordsml_amt AS DOUBLE) sml
          FROM read_parquet([{bl_list}], hive_partitioning=false)
          WHERE d >= DATE '{warm_start}'
        )
        SELECT p.stock_code, p.d, p.close_px, b.sml
        FROM px p JOIN big b USING (stock_code, d)
        ORDER BY p.stock_code, p.d
    """).fetchdf()
    con.close()
    return df


def _exists_quiet(year: int) -> bool:
    return _existing(BLAYER_E.format(year=year), BLAYER_J.format(year=year)) is not None


def compute(df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    g = df.sort_values(["stock_code", "d"], kind="mergesort").reset_index(drop=True)
    grp = g.groupby("stock_code", sort=False)
    w = args.window

    # 历史窗序列（默认不含 T：先组内 shift(1) 再取 w 窗；--include-t 则含当日）
    close_s = g["close_px"] if args.include_t else grp["close_px"].shift(1)
    sml_s = g["sml"] if args.include_t else grp["sml"].shift(1)
    g["q_hist"] = (close_s.groupby(g["stock_code"], sort=False)
                   .rolling(w, min_periods=w).quantile(args.q)
                   .reset_index(level=0, drop=True))
    g["a_hist"] = (sml_s.groupby(g["stock_code"], sort=False)
                   .rolling(w, min_periods=w).mean()   # 累加值/30 = 均值
                   .reset_index(level=0, drop=True))

    # 前瞻收益：T+k 收盘 / T 收盘 - 1（按票自身交易日历）
    for k in range(args.fwd_start, args.fwd_end + 1):
        g[f"ret{k}"] = grp["close_px"].shift(-k) / g["close_px"] - 1.0
    retcols = [f"ret{k}" for k in range(args.fwd_start, args.fwd_end + 1)]
    g["ret_max"] = g[retcols].max(axis=1)
    g["ret_min"] = g[retcols].min(axis=1)

    valid = (g["q_hist"].notna() & g["a_hist"].notna()
             & g["sml"].notna() & g["close_px"].notna())
    g["c1"] = valid & (g["close_px"] < g["q_hist"])
    g["c2"] = valid & (g["sml"] < args.ratio * g["a_hist"])
    g["sml_ratio"] = g["sml"] / g["a_hist"]

    # 只保留目标年（预热行到此为止）
    return g[g["d"] >= pd.Timestamp(f"{args.year}-01-01")].reset_index(drop=True)


def valid_mask(g: pd.DataFrame) -> pd.Series:
    return (g["q_hist"].notna() & g["a_hist"].notna()
            & g["sml"].notna() & g["close_px"].notna())


def horizon_table(df: pd.DataFrame, horizons: range, label: str) -> None:
    print(f"  [{label}] n={len(df):,}")
    print("   k       n     mean      med    win%      p25      p75")
    for k in horizons:
        r = df[f"ret{k}"].dropna()
        if not len(r):
            print(f"  T+{k:<2} {0:>7}        —")
            continue
        print(f"  T+{k:<2} {len(r):>7}  {r.mean()*100:+7.2f}%  {r.median()*100:+7.2f}%  "
              f"{(r > 0).mean()*100:5.1f}  {r.quantile(.25)*100:+7.2f}%  {r.quantile(.75)*100:+7.2f}%")
    rm, rn = df["ret_max"].dropna(), df["ret_min"].dropna()
    if len(rm):
        print(f"  窗max  mean={rm.mean()*100:+.2f}% med={rm.median()*100:+.2f}% win={(rm > 0).mean()*100:.1f}%"
              f"   窗min  mean={rn.mean()*100:+.2f}% med={rn.median()*100:+.2f}% win={(rn > 0).mean()*100:.1f}%")


def main() -> None:
    ap = argparse.ArgumentParser(description="LOW20_SMALLSELL_DRY 低位×小卖枯竭假设检验")
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--window", type=int, default=30, help="历史窗交易日数（默认 30）")
    ap.add_argument("--q", type=float, default=0.20, help="分位阈值（默认 0.20）")
    ap.add_argument("--ratio", type=float, default=0.5, help="T 日小卖额 / A 阈值（默认 0.5）")
    ap.add_argument("--fwd-start", dest="fwd_start", type=int, default=5)
    ap.add_argument("--fwd-end", dest="fwd_end", type=int, default=10)
    ap.add_argument("--include-t", dest="include_t", action="store_true",
                    help="历史窗含 T（默认 T-1..T-30 不含 T）")
    ap.add_argument("--px-cache", dest="px_cache", default="",
                    help="价格缓存覆盖（默认原始价；等比复权用 "
                         "E:/stock_data/l2_research/cache/daily_px_adj_2019_2026.parquet）")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    if args.px_cache:
        global PX_OVERRIDE
        PX_OVERRIDE = args.px_cache

    warm_start = f"{args.year - 1}-11-01"   # ≥30 个交易日预热
    df = load(args.year, warm_start)
    print(f"[load] rows={len(df):,} stocks={df['stock_code'].nunique():,}  "
          f"{df['d'].min().date()}..{df['d'].max().date()}  "
          f"窗 w={args.window} q={args.q} ratio={args.ratio} "
          f"({'含T' if args.include_t else '不含T'})")

    g = compute(df, args)
    vm = valid_mask(g)
    both = g[g["c1"] & g["c2"]]
    print(f"[pool] 有效窗={vm.sum():,}  C1={int(g['c1'].sum()):,}  "
          f"C2={int(g['c2'].sum()):,}  BOTH={len(both):,}  "
          f"(仅C1={int((g['c1'] & ~g['c2']).sum()):,}  仅C2={int((g['c2'] & ~g['c1']).sum()):,})")

    horizons = range(args.fwd_start, args.fwd_end + 1)
    k_last = f"ret{args.fwd_end}"
    horizon_table(both, horizons, f"BOTH @{args.year}")
    horizon_table(g[vm], horizons, "BASE 全体有效窗（对照）")
    horizon_table(g[g["c1"]], horizons, "C1 低位（含与C2重叠）")
    horizon_table(g[g["c2"]], horizons, "C2 小卖枯竭（含与C1重叠）")

    sub = both.copy()
    if len(sub):
        sub["m"] = sub["d"].dt.to_period("M")
        print("  --- 分月（BOTH 池）---")
        for mth, s in sub.groupby("m"):
            r = s[k_last].dropna()
            stat = f"T+{args.fwd_end} mean={r.mean()*100:+.2f}% win={(r > 0).mean()*100:.1f}%" if len(r) else "无前瞻"
            print(f"  {mth}  n={len(s):4d}  {stat}")
        h2 = sub["d"] >= pd.Timestamp(f"{args.year}-07-01")
        for tag, s in (("H1", sub[~h2]), ("H2", sub[h2])):
            if len(s):
                r = s[k_last].dropna()
                m = f"mean={r.mean()*100:+.2f}% win={(r > 0).mean()*100:.1f}%" if len(r) else "无前瞻"
                print(f"  {tag} n={len(s):,}  T+{args.fwd_end} {m}")

    out_path = args.out or OUT_TMPL.format(year=args.year)
    cols = (["d", "stock_code", "close_px", "q_hist", "sml", "a_hist", "sml_ratio"]
            + [f"ret{k}" for k in horizons] + ["ret_max", "ret_min"])
    out = both.sort_values(["d", "stock_code"])[cols].copy()
    out["d"] = out["d"].dt.date
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    out.to_csv(out_path, index=False, encoding="utf-8-sig", float_format="%.6g")
    print(f"[out] {out_path}  rows={len(out):,}")


if __name__ == "__main__":
    main()
