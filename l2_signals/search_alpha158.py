"""Alpha158 × 大单 C1 池联合信号搜索（H1 发现 / H2 验证）。

C1 池：大单(10万档)量 ≥ 2×前日。特征 = 158 Alpha158 因子 + 10 个大单特征 + 2 个价格上下文。
切分：H1 = 2026-01-05..06-30（发现，含分位阈值），H2 = 2026-07-01..（验证）。
门槛（沿用交接标准）：全年 n≥50 且 T+1 胜率>55%；H2 n≥15 且胜率>50%。

用法：
    D:/anaconda3/envs/vanna312/python.exe l2_signals/search_alpha158.py [--depth 3]
"""
import argparse
import csv
import itertools
import os
import sys
import time

import duckdb
import numpy as np
import pandas as pd

A158 = "E:/stock_data/l2_research/alpha158_daily.parquet"
BLAYER = "J:/l2_lake/rollup/bigorder_daily_2026.parquet"
FF = "E:/stock_data/free_float_shares.parquet"
ROLLUP = "J:/l2_lake/rollup/daily_stock/version=l2-daily-v3/params=a2e3a427af892982d0ce/date=*/part.parquet"
OUT = "E:/stock_data/l2_research/alpha158_search_results.csv"

GAP = "2026-01-05"
MID = pd.Timestamp("2026-07-01")

# 大单域切点（六信号族已验证的条件，保留原文语义）
BIGORDER_CUTS = {
    "bs": [("bs<0.10", lambda s: s < 0.10), ("bs>0.10", lambda s: s > 0.10), ("bs>0.20", lambda s: s > 0.20)],
    "ddxr": [("ddxr<0.50", lambda s: s < 0.50), ("ddxr<0.75", lambda s: s < 0.75), ("ddxr>0.50", lambda s: s > 0.50)],
    "nfr": [("nfr>0.005", lambda s: s > 0.005), ("nfr>0.02", lambda s: s > 0.02), ("nfr>0.05", lambda s: s > 0.05)],
    "c1x": [("c1x<3", lambda s: s < 3), ("c1x>3", lambda s: s > 3), ("c1x>5", lambda s: s > 5)],
    "bsr": [("bsr>1", lambda s: s > 1.0), ("bsr<1", lambda s: s < 1.0)],
    "pr": [("pr<0.5", lambda s: s < 0.5), ("pr>0.5", lambda s: s > 0.5)],
    "ret_prev": [("ret_prev<0", lambda s: s < 0), ("ret_prev>0", lambda s: s > 0), ("ret_prev<0.02", lambda s: s < 0.02)],
    "KMID": [("KMID<0", lambda s: s < 0), ("KMID>0", lambda s: s > 0), ("KMID<0.02", lambda s: s < 0.02)],
}


def load_pool() -> pd.DataFrame:
    con = duckdb.connect()
    big = con.execute(f"""
        SELECT CAST(d AS DATE) d, stock_code,
               buyord10w_vol bov, saleord10w_vol sov,
               buyord10w_amt bam, saleord10w_amt sam,
               buyord10w_active_amt baam, saleord10w_active_amt saam,
               bov / lag(bov) OVER (PARTITION BY stock_code ORDER BY d) c1x
        FROM read_parquet('{BLAYER}') ORDER BY stock_code, d""").fetchdf()
    pool = big[(big["c1x"] >= 2.0) & (big["d"] >= GAP)].copy()

    px = con.execute(f"""
        SELECT stock_code, CAST(d AS DATE) d, close_px, total_amt,
               lead(close_px) OVER (PARTITION BY stock_code ORDER BY d) t1_close,
               close_px / lag(close_px) OVER (PARTITION BY stock_code ORDER BY d) - 1 ret_prev
        FROM read_parquet('{ROLLUP}', hive_partitioning=false)
        WHERE d >= DATE '2025-12-01' ORDER BY stock_code, d""").fetchdf()

    ff = con.execute(f"""
        SELECT stock_code, CAST(m_timetag AS DATE) d, freeFloatCapital ffv
        FROM read_parquet('{FF}') WHERE freeFloatCapital > 0
        ORDER BY stock_code, d""").fetchdf()

    df = pool.merge(px, on=["stock_code", "d"], how="left")
    df = con.execute("""
        SELECT p.*, f.ffv FROM df p
        ASOF LEFT JOIN ff f ON p.stock_code = f.stock_code AND p.d >= f.d
        ORDER BY p.stock_code, p.d""").fetchdf()

    fact = pd.read_parquet(A158)
    fact["d"] = pd.to_datetime(fact["d"])
    fact = fact[fact["d"] >= pd.Timestamp(GAP)]
    df["d"] = pd.to_datetime(df["d"])
    df = df.merge(fact, on=["stock_code", "d"], how="left")

    # 大单特征 + 标签
    nbam = df["bam"] - df["sam"]
    df["nbam_m"] = nbam / 1e6
    df["ddxr"] = ((df["baam"] - df["saam"]) / nbam).where(nbam != 0)
    df["bs"] = (df["bam"] / df["total_amt"]).where(df["total_amt"] > 0)
    df["pr"] = ((df["bam"] + df["sam"]) / df["total_amt"]).where(df["total_amt"] > 0)
    df["nfr"] = (nbam / df["ffv"] / df["close_px"]).where(df["ffv"] > 0)
    df["bsr"] = (df["bov"] / df["sov"]).where(df["sov"] > 0)
    df["c1x"] = df["c1x"].astype(float)
    df = df[df["t1_close"].notna() & df["close_px"].notna()].copy()  # 无次日收盘的末日剔除
    df["win"] = (df["t1_close"] > df["close_px"]).astype(int)
    df["ret1"] = df["t1_close"] / df["close_px"] - 1
    df["h2"] = pd.to_datetime(df["d"]) >= MID
    return df


def build_conditions(df: pd.DataFrame, factor_cols):
    """H1 分位阈值 → 布尔条件矩阵（阈值只用 H1，防泄漏）。"""
    h1 = df[~df["h2"]]
    conds = {}
    for col in factor_cols:
        x = df[col]
        if x.notna().sum() < 200:
            continue
        q20, q40, q60, q80 = h1[col].quantile([0.2, 0.4, 0.6, 0.8])
        conds[f"{col}<=q20"] = x <= q20
        conds[f"{col}>=q80"] = x >= q80
        conds[f"{col}=mid"] = (x > q40) & (x < q60)
    for col, cuts in BIGORDER_CUTS.items():
        for name, fn in cuts:
            conds[name] = fn(df[col])
    return pd.DataFrame(conds, index=df.index)


def ev(mask, h2):
    """返回 (n_h1, wr_h1, avg_h1, n_h2, wr_h2, avg_h2, n_all, wr_all, avg_all) 或 None。"""
    m1, m2 = mask & ~h2, mask & h2
    n1, n2 = int(m1.sum()), int(m2.sum())
    if n1 == 0 or n2 == 0:
        return None
    d1, d2 = df_win[m1], df_win[m2]
    dret1, dret2 = df_ret[m1], df_ret[m2]
    wr1, wr2 = d1.mean(), d2.mean()
    n = n1 + n2
    wr = (d1.sum() + d2.sum()) / n
    avg = (dret1.sum() + dret2.sum()) / n
    return n1, wr1, dret1.mean(), n2, wr2, dret2.mean(), n, wr, avg


def fmt(name, r):
    n1, wr1, a1, n2, wr2, a2, n, wr, a = r
    return f"{name:42s} n={n:4d} wr={wr*100:5.1f}% avg={a*100:+5.2f}% | H1 {n1:4d} {wr1*100:5.1f}% | H2 {n2:4d} {wr2*100:5.1f}%"


def main():
    global df_win, df_ret
    ap = argparse.ArgumentParser()
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--top-single", type=int, default=30)
    ap.add_argument("--top-pairs", type=int, default=60)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    t0 = time.time()
    df = load_pool()
    h1n, h2n = (~df["h2"]).sum(), df["h2"].sum()
    h1w, h2w = df["win"][~df["h2"]].mean(), df["win"][df["h2"]].mean()
    print(f"C1池 {len(df):,}  H1 {h1n:,}({h1w*100:.1f}%)  H2 {h2n:,}({h2w*100:.1f}%)  {time.time()-t0:.0f}s")

    df_win = df["win"].to_numpy()
    df_ret = df["ret1"].to_numpy()
    h2_arr = df["h2"].to_numpy()

    # 基线信号复现（QUIET 系 sanity check）
    base = (df["bs"] < 0.10) & (df["KMID"] < 0) & (df["ret_prev"] < 0)
    r = ev(base.to_numpy(), h2_arr)
    if r:
        print("基线复现 STEP_DIP_ACCUM(bs<10,KMID<0,ret_prev<0): " + fmt("baseline", r))

    factor_cols = [c for c in df.columns if c not in (
        "d", "stock_code", "bov", "sov", "bam", "sam", "baam", "saam",
        "close_px", "total_amt", "t1_close", "ffv", "win", "ret1", "h2")]
    C = build_conditions(df, factor_cols)
    print(f"条件池 {C.shape[1]} 个  {time.time()-t0:.0f}s")

    results = []

    def record(combo, r, depth):
        n1, wr1, a1, n2, wr2, a2, n, wr, a = r
        results.append({"depth": depth, "combo": " & ".join(combo), "n": n, "wr": round(wr, 4),
                        "avg_ret": round(a, 5), "n_h1": n1, "wr_h1": round(wr1, 4),
                        "n_h2": n2, "wr_h2": round(wr2, 4)})

    masks = {c: C[c].to_numpy() for c in C.columns}

    # ---- 单因子发现层：门槛放宽（单因子最强仅 ~49%），只作种子与方向参考
    singles = []
    for col in C.columns:
        r = ev(masks[col], h2_arr)
        if r is None:
            continue
        n1, wr1, _, n2, wr2, _, n, wr, _ = r
        if n1 >= 150 and n2 >= 25 and wr1 > 0.475 and wr2 > 0.47:
            singles.append((col, r))
    singles.sort(key=lambda t: -min(t[1][1], t[1][4]))
    print(f"\n== 单因子种子 {len(singles)}（按 min(wr1,wr2) 排）==")
    for name, r in singles[:12]:
        print(fmt(name, r))
    seed_pool = [n for n, _ in singles[: args.top_single]]

    # ---- 2 组合：全量扫描（C(520,2)≈13.5 万对，交互才是信号所在）
    def passes2(r):
        n1, wr1, _, n2, wr2, _, n, wr, _ = r
        return (n1 >= 60 and n2 >= 12 and n >= 50 and
                wr > 0.55 and wr1 >= 0.52 and wr2 > 0.50)

    pairs = []
    all_names = list(masks)
    for i, a in enumerate(all_names):
        ma = masks[a]
        for b in all_names[i + 1:]:
            mb = masks[b]
            m = ma & mb
            if m.sum() < 50:
                continue
            r = ev(m, h2_arr)
            if r is not None and passes2(r):
                pairs.append(((a, b), r, m))
    pairs.sort(key=lambda t: -min(t[1][1], t[1][4]))
    print(f"\n== 2 组合通过 {len(pairs)} ==")
    for key, r, _ in pairs[:15]:
        print(fmt(" & ".join(key), r))
        record(key, r, 2)

    # ---- 3 组合：top 对 × 种子扩展；剔除已通过对的近超集（n 差 <5% 视为冗余）
    def passes3(r):
        n1, wr1, _, n2, wr2, _, n, wr, _ = r
        return (n1 >= 40 and n2 >= 10 and n >= 50 and
                wr > 0.56 and wr1 >= 0.53 and wr2 > 0.51)

    passed_pair_n = [(set(k), r[6]) for k, r, _ in pairs]
    triples = []
    seen = set()
    for (pa, pb), _, pm in pairs[: args.top_pairs]:
        for s in seed_pool:
            if s in (pa, pb):
                continue
            key = tuple(sorted((pa, pb, s)))
            if key in seen:
                continue
            seen.add(key)
            m = pm & masks[s]
            if m.sum() < 50:
                continue
            ks = set(key)
            if any(ks.issuperset(pk) and m.sum() >= 0.95 * pn for pk, pn in passed_pair_n):
                continue
            r = ev(m, h2_arr)
            if r is not None and passes3(r):
                triples.append((key, r, m))
    triples.sort(key=lambda t: -min(t[1][1], t[1][4]))
    print(f"\n== 3 组合通过 {len(triples)} ==")
    for key, r, _ in triples[:15]:
        print(fmt(" & ".join(key), r))
        record(key, r, 3)

    if not results:
        print("[done] 无组合通过门槛，不写 CSV")
        return
    results.sort(key=lambda r: (-r["depth"], -r["wr"]))
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)
    print(f"\n[done] {len(results)} 条 → {args.out}  {time.time()-t0:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
