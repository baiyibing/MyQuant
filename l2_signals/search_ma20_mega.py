"""Gen2 搜索：净大单×MA20上穿 池 × Alpha158 联合信号搜索（H1 发现 / H2 验证 + 跨年诊断）。

池定义（用户方案，两核心指标）：
    1. 净大单量/有效流通盘 > 2%   —— (bov - sov) / freeFloatCapital > 0.02（量口径）
    2. close 站上 20 日均线        —— 当日首站（close>MA20 且昨 close<=MA20）或昨日首站

特征 = 158 Alpha158 因子 + 大单特征(bs/ddxr/nfr/c1x/bsr/pr) + MA20 上下文(ma20_dist/cross_age/still_above)。
切分：H1 = 当年 1 月..6 月底（发现，含分位阈值），H2 = 7 月..（验证）。
门槛（沿用交接标准）：全年 n≥50 且 T+1 胜率>55%；H2 n≥10-12 且胜率>50%。
跨年诊断（非门槛，仅打印）：冻结 H1 条件 spec → 2023/2024/2025 池打分。

用法：
    D:/anaconda3/envs/vanna312/python.exe l2_signals/search_ma20_mega.py [--year 2026] [--depth 3]
"""
import argparse
import csv
import os
import sys
import time

import duckdb
import numpy as np
import pandas as pd

A158 = "E:/stock_data/l2_research/alpha158_daily.parquet"
FF = "E:/stock_data/free_float_shares.parquet"
ROLLUP = "J:/l2_lake/rollup/daily_stock/version=l2-daily-v3/params=a2e3a427af892982d0ce/date=*/part.parquet"
OUT = "E:/stock_data/l2_research/ma20_mega_search_results.csv"

MID_MONTH = 7          # H1/H2 切分月
RATIO_TH = 0.02        # 净大单量/流通 阈值
WARMUP_DAYS = 70       # MA20 预热（跨年取前一年 12 月）


def limit_pct(code: str) -> float:
    """按板块给涨停幅（近似：未识别 ST 5%）。涨停收盘=T 收盘竞价封死，买不进。"""
    if code.startswith(("688", "689")) or code.startswith("30"):
        return 0.20
    if code[:3] in ("920", "430", "830", "870", "880") or code.startswith(("83", "87", "88", "43")):
        return 0.30
    return 0.10

# 固定值条件（沿用六信号族 + gen2 新增）。op: le/ge/gt/lt/eq/mid
FIXED_CUTS = [
    ("bs<0.10", "bs", "lt", 0.10), ("bs>0.10", "bs", "gt", 0.10), ("bs>0.20", "bs", "gt", 0.20),
    ("ddxr<0.50", "ddxr", "lt", 0.50), ("ddxr>0.50", "ddxr", "gt", 0.50),
    ("nfr>0.03", "nfr", "gt", 0.03), ("nfr>0.05", "nfr", "gt", 0.05),
    ("nfr_vol>0.03", "nfr_vol", "gt", 0.03), ("nfr_vol>0.05", "nfr_vol", "gt", 0.05),
    ("c1x>=2", "c1x", "ge", 2.0), ("c1x<2", "c1x", "lt", 2.0),
    ("bsr>1", "bsr", "gt", 1.0), ("bsr<1", "bsr", "lt", 1.0),
    ("pr<0.5", "pr", "lt", 0.5), ("pr>0.5", "pr", "gt", 0.5),
    ("ret_prev<0", "ret_prev", "lt", 0.0), ("ret_prev>0", "ret_prev", "gt", 0.0),
    ("KMID<0", "KMID", "lt", 0.0), ("KMID>0", "KMID", "gt", 0.0),
    ("ma20_dist<0.02", "ma20_dist", "lt", 0.02), ("ma20_dist>0.02", "ma20_dist", "gt", 0.02),
    ("ma20_dist<0.05", "ma20_dist", "lt", 0.05),
    ("cross_age=0", "cross_age", "eq", 0), ("cross_age=1", "cross_age", "eq", 1),
    ("still_above=1", "still_above", "eq", 1),
]


def load_year(year: int, exclude_limit_close: bool = False) -> pd.DataFrame:
    """gen2 池：净大单量/流通>2% × MA20上穿(当日或昨日首站)，含 158 因子 + 大单 + MA20 特征。

    exclude_limit_close=True 时剔除信号日收盘涨停（可买性硬条件，v2 搜索用）：
    引擎验证发现 MAX5<=1.0 指纹下 98-100% 信号日收盘涨停，T 收盘入场不可行。
    """
    con = duckdb.connect()
    big = con.execute(f"""
        SELECT CAST(d AS DATE) d, stock_code,
               buyord10w_vol bov, saleord10w_vol sov,
               buyord10w_amt bam, saleord10w_amt sam,
               buyord10w_active_amt baam, saleord10w_active_amt saam,
               bov / lag(bov) OVER (PARTITION BY stock_code ORDER BY d) c1x
        FROM read_parquet('J:/l2_lake/rollup/bigorder_daily_{year}.parquet') ORDER BY stock_code, d""").fetchdf()

    px = con.execute(f"""
        SELECT stock_code, CAST(d AS DATE) d, close_px, total_amt,
               lead(close_px) OVER (PARTITION BY stock_code ORDER BY d) t1_close,
               close_px / lag(close_px) OVER (PARTITION BY stock_code ORDER BY d) - 1 ret_prev
        FROM read_parquet('{ROLLUP}', hive_partitioning=false)
        WHERE d >= DATE '{year}-01-01' - INTERVAL {WARMUP_DAYS} DAY AND d < DATE '{year + 1}-01-01'
        ORDER BY stock_code, d""").fetchdf()
    px["ma20"] = px.groupby("stock_code")["close_px"].transform(
        lambda s: s.rolling(20, min_periods=20).mean())
    above = px["close_px"] > px["ma20"]
    cross = above & (~above.groupby(px["stock_code"]).shift(1, fill_value=False))
    cross_prev = cross.groupby(px["stock_code"]).shift(1, fill_value=False)
    px["cross_age"] = np.where(cross, 0, np.where(cross_prev, 1, -1))  # -1=非新上穿
    px["ma20_dist"] = px["close_px"] / px["ma20"] - 1
    px = px[px["d"] >= f"{year}-01-01"]

    ff = con.execute(f"""
        SELECT stock_code, CAST(m_timetag AS DATE) d, freeFloatCapital ffv
        FROM read_parquet('{FF}') WHERE freeFloatCapital > 0
        ORDER BY stock_code, d""").fetchdf()

    df = big.merge(px, on=["stock_code", "d"], how="inner")
    df = con.execute("""
        SELECT p.*, f.ffv FROM df p
        ASOF LEFT JOIN ff f ON p.stock_code = f.stock_code AND p.d >= f.d
        ORDER BY p.stock_code, p.d""").fetchdf()

    ok = df["ffv"].notna() & (df["ffv"] > 0) & df["ma20"].notna()
    df["nfr_vol"] = ((df["bov"] - df["sov"]) / df["ffv"]).where(ok)
    df["nfr"] = ((df["bam"] - df["sam"]) / (df["ffv"] * df["close_px"])).where(ok)

    pool = df[(df["nfr_vol"] > RATIO_TH) & (df["cross_age"] >= 0)].copy()
    if exclude_limit_close:
        lp = pool["stock_code"].map(limit_pct)
        n0 = len(pool)
        pool = pool[pool["ret_prev"] < lp - 0.0015].copy()  # ret_prev 列 = 信号日当日涨幅
        print(f"[buyable {year}] 剔除收盘涨停 {n0 - len(pool):,} 行，余 {len(pool):,}")

    fact = pd.read_parquet(A158, columns=None)
    fact["d"] = pd.to_datetime(fact["d"])
    fact = fact[(fact["d"] >= pd.Timestamp(f"{year}-01-01")) & (fact["d"] < pd.Timestamp(f"{year + 1}-01-01"))]
    pool["d"] = pd.to_datetime(pool["d"])
    pool = pool.merge(fact, on=["stock_code", "d"], how="left")

    nbam = pool["bam"] - pool["sam"]
    pool["nbam_m"] = nbam / 1e6
    pool["ddxr"] = ((pool["baam"] - pool["saam"]) / nbam).where(nbam != 0)
    pool["bs"] = (pool["bam"] / pool["total_amt"]).where(pool["total_amt"] > 0)
    pool["pr"] = ((pool["bam"] + pool["sam"]) / pool["total_amt"]).where(pool["total_amt"] > 0)
    pool["bsr"] = (pool["bov"] / pool["sov"]).where(pool["sov"] > 0)
    pool["c1x"] = pool["c1x"].astype(float)
    pool["still_above"] = (pool["close_px"] > pool["ma20"]).astype(int)
    pool = pool[pool["t1_close"].notna() & pool["close_px"].notna()].copy()
    pool["win"] = (pool["t1_close"] > pool["close_px"]).astype(int)
    pool["ret1"] = pool["t1_close"] / pool["close_px"] - 1
    pool["h2"] = pool["d"] >= pd.Timestamp(f"{year}-{MID_MONTH:02d}-01")

    n_all = len(pool)
    pool = pool[pool["KMID"] != 0].copy()  # 一字/T 字板不可买
    print(f"[pool {year}] 池 {n_all:,} → 可交易 {len(pool):,}（剔一字/T字 {n_all - len(pool):,}）")
    return pool


def build_spec(df: pd.DataFrame, factor_cols) -> dict:
    """条件 spec：{名称: (列, op, 值[, 值2])}。分位阈值只取 H1，防泄漏。"""
    h1 = df[~df["h2"]]
    spec = {}
    for col in factor_cols:
        if df[col].notna().sum() < 200:
            continue
        q20, q40, q60, q80 = h1[col].quantile([0.2, 0.4, 0.6, 0.8])
        spec[f"{col}<=q20"] = (col, "le", q20)
        spec[f"{col}>=q80"] = (col, "ge", q80)
        spec[f"{col}=mid"] = (col, "gt_lt", q40, q60)
    for name, col, op, v in FIXED_CUTS:
        spec[name] = (col, op, v)
    return spec


def eval_spec(df: pd.DataFrame, spec: dict) -> dict:
    """spec → 布尔掩码字典（任意年份 df 均可复算，跨年冻结用）。"""
    out = {}
    cols = {s[0] for s in spec.values()}
    data = {c: df[c].to_numpy() for c in cols if c in df.columns}
    for name, s in spec.items():
        col, op = s[0], s[1]
        if col not in data:
            continue
        x = data[col]
        if op == "le":
            out[name] = x <= s[2]
        elif op == "ge":
            out[name] = x >= s[2]
        elif op == "lt":
            out[name] = x < s[2]
        elif op == "gt":
            out[name] = x > s[2]
        elif op == "eq":
            out[name] = x == s[2]
        elif op == "gt_lt":
            out[name] = (x > s[2]) & (x < s[3])
    return out


def ev(mask, h2, win, ret):
    m1, m2 = mask & ~h2, mask & h2
    n1, n2 = int(m1.sum()), int(m2.sum())
    if n1 == 0 or n2 == 0:
        return None
    w1, w2 = win[m1], win[m2]
    n = n1 + n2
    wr = (w1.sum() + w2.sum()) / n
    avg = (ret[m1].sum() + ret[m2].sum()) / n
    return n1, w1.mean(), n2, w2.mean(), n, wr, avg


def fmt(name, r):
    n1, wr1, n2, wr2, n, wr, avg = r
    return f"{name:46s} n={n:4d} wr={wr*100:5.1f}% avg={avg*100:+5.2f}% | H1 {n1:4d} {wr1*100:5.1f}% | H2 {n2:4d} {wr2*100:5.1f}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--top-single", type=int, default=30)
    ap.add_argument("--top-pairs", type=int, default=60)
    ap.add_argument("--xyear-diag", default="2023,2024,2025", help="跨年诊断年份（逗号分隔，空=关）")
    ap.add_argument("--exclude-limit-close", action="store_true",
                    help="v2：池剔除信号日收盘涨停（可买性硬条件，见引擎验证教训）")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    t0 = time.time()
    df = load_year(args.year, exclude_limit_close=args.exclude_limit_close)
    h1, h2 = df[~df["h2"]], df[df["h2"]]
    print(f"[base] H1 {len(h1):,}({h1['win'].mean()*100:.1f}%)  H2 {len(h2):,}({h2['win'].mean()*100:.1f}%)  {time.time()-t0:.0f}s")

    win = df["win"].to_numpy()
    ret = df["ret1"].to_numpy()
    h2_arr = df["h2"].to_numpy()

    factor_cols = [c for c in df.columns if c not in (
        "d", "stock_code", "bov", "sov", "bam", "sam", "baam", "saam",
        "close_px", "total_amt", "t1_close", "ffv", "ma20", "win", "ret1", "h2")]
    spec = build_spec(df, factor_cols)
    masks = eval_spec(df, spec)
    print(f"[conds] {len(masks)} 个条件  {time.time()-t0:.0f}s")

    results = []

    def record(combo, r, depth):
        n1, wr1, n2, wr2, n, wr, avg = r
        results.append({"depth": depth, "combo": " & ".join(combo), "n": n, "wr": round(wr, 4),
                        "avg_ret": round(avg, 5), "n_h1": n1, "wr_h1": round(wr1, 4),
                        "n_h2": n2, "wr_h2": round(wr2, 4)})

    # ---- 单因子种子（门槛放宽：单因子少有独立 >50%，作种子用）
    singles = []
    for name, m in masks.items():
        r = ev(m, h2_arr, win, ret)
        if r is None:
            continue
        n1, wr1, n2, wr2, *_ = r
        if n1 >= 150 and n2 >= 25 and wr1 > 0.475 and wr2 > 0.47:
            singles.append((name, r))
    singles.sort(key=lambda t: -min(t[1][1], t[1][3]))
    print(f"\n== 单因子种子 {len(singles)}（按 min(wr1,wr2) 排）==")
    for name, r in singles[:12]:
        print(fmt(name, r))
    seeds = [n for n, _ in singles[: args.top_single]]

    # ---- 2 组合全扫
    def passes2(r):
        n1, wr1, n2, wr2, n, wr, _ = r
        return n1 >= 60 and n2 >= 12 and n >= 50 and wr > 0.55 and wr1 >= 0.52 and wr2 > 0.50

    pairs = []
    names = list(masks)
    for i, a in enumerate(names):
        ma = masks[a]
        for b in names[i + 1:]:
            m = ma & masks[b]
            if m.sum() < 50:
                continue
            r = ev(m, h2_arr, win, ret)
            if r is not None and passes2(r):
                pairs.append(((a, b), r, m))
    pairs.sort(key=lambda t: -min(t[1][1], t[1][3]))
    print(f"\n== 2 组合通过 {len(pairs)} ==")
    for key, r, _ in pairs[:15]:
        print(fmt(" & ".join(key), r))
        record(key, r, 2)

    # ---- 3 组合：top 对 × 种子扩展
    if args.depth >= 3:
        def passes3(r):
            n1, wr1, n2, wr2, n, wr, _ = r
            return n1 >= 40 and n2 >= 10 and n >= 50 and wr > 0.56 and wr1 >= 0.53 and wr2 > 0.51

        pair_ns = [(set(k), r[4]) for k, r, _ in pairs]
        triples = []
        seen = set()
        for (pa, pb), _, pm in pairs[: args.top_pairs]:
            for s in seeds:
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
                if any(ks.issuperset(pk) and m.sum() >= 0.95 * pn for pk, pn in pair_ns):
                    continue
                r = ev(m, h2_arr, win, ret)
                if r is not None and passes3(r):
                    triples.append((key, r))
        triples.sort(key=lambda t: -min(t[1][1], t[1][3]))
        print(f"\n== 3 组合通过 {len(triples)} ==")
        for key, r in triples[:15]:
            print(fmt(" & ".join(key), r))
            record(key, r, 3)

    if not results:
        print("[done] 无组合通过门槛，不写 CSV")
        return

    # ---- 跨年诊断（冻结 H1 spec 直接打分，非门槛，仅看稳定性）
    if args.xyear_diag.strip():
        diag_years = [int(y) for y in args.xyear_diag.split(",") if y.strip()]
        cand = sorted(results, key=lambda r: (-r["depth"], -r["wr"]))[:10]
        print(f"\n== 跨年诊断（冻结 {args.year}-H1 条件，前 10 组合 × {diag_years}）==")
        pools = {y: load_year(y, exclude_limit_close=args.exclude_limit_close) for y in diag_years}
        for row in cand:
            conds = row["combo"].split(" & ")
            line = [f"{row['combo']}"]
            for y in diag_years:
                mm = eval_spec(pools[y], spec)
                m = np.logical_and.reduce([mm[c] for c in conds])
                w = pools[y]["win"].to_numpy()[m]
                line.append(f"{y}: n={m.sum():4d} wr={w.mean()*100:5.1f}%" if m.sum() else f"{y}: n=0")
            print("  " + " | ".join(line))

    results.sort(key=lambda r: (-r["depth"], -r["wr"]))
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)
    print(f"\n[done] {len(results)} 条 → {args.out}  {time.time()-t0:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
