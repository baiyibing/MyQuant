"""复现 gen0 六信号族（对拍 E:/stock_data 黄金 CSV）。

六族（规范名 → 黄金 / 定稿条件）
--------------------------------
STEP_DIP_ACCUM   step_optimized_2026.csv
                 C1 ∧ ret_prev<0 ∧ ret_1d<0 ∧ bs<0.10          Exact 21/21
QUIET_DIP_TECH   （无黄金；与 ACCUM 同 C1/C4，不含大单）
                 C1_阴线守MA5 ∧ C4_昨小阳
QUIET_DIP_ACCUM  quiet_dip_accum_2026.csv
                 C1∧C2∧C3∧C4                                  Exact 18/18
MEGA_ORDER_ACCUM mega_order_accum_2026.csv
                 nfr_vol = (bov−sov)/ffv > 5%                 Exact 1321（不要求 T+1）
VOL_SURGE_BUY    命名卡定稿（= BIG_ORDER_STEP；v2/v3 CSV 非 Exact）
                 C1 ∧ bov>sov ∧ close>MA20 ∧ close>MA100 ∧ nbam>3000万
DIP_CATCH_FALL   dip_buy_accum_2026.csv
                 close<昨收 ∧ nfr_vol>2%                       gold 全覆盖；带 T+1 时略少

用法
----
    D:/anaconda3/envs/vanna312/python.exe l2_signals/reproduce_gen0_signals.py --list
    D:/anaconda3/envs/vanna312/python.exe l2_signals/reproduce_gen0_signals.py --signal MEGA_ORDER_ACCUM
    D:/anaconda3/envs/vanna312/python.exe l2_signals/reproduce_gen0_signals.py --signal ALL --year 2026
"""
from __future__ import annotations

import argparse
import os
import sys

import duckdb
import pandas as pd

ROLLUP = (
    "J:/l2_lake/rollup/daily_stock/version=l2-daily-v3/"
    "params=a2e3a427af892982d0ce/date=*/part.parquet"
)
FF = "E:/stock_data/free_float_shares.parquet"
BLAYER_TMPL = "J:/l2_lake/rollup/bigorder_daily_{year}.parquet"
OUT_DIR = "E:/stock_data/l2_research/signals"

# 黄金 CSV（仅 2026；缺则跳过对拍）
GOLD = {
    "STEP_DIP_ACCUM": ("E:/stock_data/step_optimized_2026.csv", "日期", "代码"),
    "QUIET_DIP_ACCUM": ("E:/stock_data/quiet_dip_accum_2026.csv", "日期", "股票代码"),
    "MEGA_ORDER_ACCUM": ("E:/stock_data/mega_order_accum_2026.csv", "日期", "股票代码"),
    "DIP_CATCH_FALL": ("E:/stock_data/dip_buy_accum_2026.csv", "日期", "股票代码"),
}

# BIG_ORDER_STEP 与 VOL_SURGE_BUY 同条件（命名卡定稿名）
ALIASES = {"BIG_ORDER_STEP": "VOL_SURGE_BUY"}

SIGNALS = [
    "STEP_DIP_ACCUM",
    "QUIET_DIP_TECH",
    "QUIET_DIP_ACCUM",
    "MEGA_ORDER_ACCUM",
    "VOL_SURGE_BUY",
    "DIP_CATCH_FALL",
]


def _resolve(name: str) -> str:
    name = name.upper()
    return ALIASES.get(name, name)


def load_mega_like(year: int) -> pd.DataFrame:
    """以 B 层为主表（MEGA/DIP 黄金含仅有大单、价域边界日的行）。"""
    blayer = BLAYER_TMPL.format(year=year)
    if not os.path.exists(blayer):
        raise FileNotFoundError(f"B 层不存在: {blayer}")
    px_start = f"{year - 1}-12-01"
    gap = f"{year}-01-01"
    con = duckdb.connect()
    dmin, dmax, nrow = con.execute(
        f"SELECT min(d), max(d), count(*) FROM read_parquet('{blayer}')"
    ).fetchone()
    print(f"[blayer] {blayer}  rows={nrow:,}  {dmin}..{dmax}")
    df = con.execute(f"""
        WITH big AS (
          SELECT CAST(d AS DATE) d, stock_code,
                 buyord10w_vol bov, saleord10w_vol sov,
                 buyord10w_amt bam, saleord10w_amt sam,
                 lag(buyord10w_vol) OVER (PARTITION BY stock_code ORDER BY d) prev_bov
          FROM read_parquet('{blayer}')
        ),
        px AS (
          SELECT stock_code, CAST(d AS DATE) d,
                 open_px, high_px, low_px, close_px, total_amt,
                 lag(close_px) OVER (PARTITION BY stock_code ORDER BY d) pc,
                 lag(close_px, 2) OVER (PARTITION BY stock_code ORDER BY d) pc2,
                 lead(close_px) OVER (PARTITION BY stock_code ORDER BY d) t1_close,
                 lag(open_px) OVER (PARTITION BY stock_code ORDER BY d) po,
                 lag(high_px) OVER (PARTITION BY stock_code ORDER BY d) ph,
                 lag(low_px) OVER (PARTITION BY stock_code ORDER BY d) pl,
                 avg(close_px) OVER (
                   PARTITION BY stock_code ORDER BY d
                   ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
                 ) ma5,
                 CAST(NULL AS DOUBLE) ma20,
                 CAST(NULL AS DOUBLE) ma100
          FROM read_parquet('{ROLLUP}', hive_partitioning=false)
          WHERE d >= DATE '{px_start}'
        ),
        ff AS (
          SELECT stock_code, CAST(m_timetag AS DATE) d, freeFloatCapital ffv
          FROM read_parquet('{FF}') WHERE freeFloatCapital > 0
        )
        SELECT b.stock_code, b.d, b.bov, b.sov, b.bam, b.sam, b.prev_bov, f.ffv,
               p.open_px, p.high_px, p.low_px, p.close_px, p.total_amt,
               p.po, p.ph, p.pl, p.pc, p.pc2, p.t1_close, p.ma5, p.ma20, p.ma100
        FROM big b
        ASOF LEFT JOIN ff f ON b.stock_code = f.stock_code AND b.d >= f.d
        LEFT JOIN px p ON b.stock_code = p.stock_code AND b.d = p.d
        WHERE b.d >= DATE '{gap}'
          AND f.ffv > 0
    """).fetchdf()
    df["d"] = pd.to_datetime(df["d"]).dt.normalize()
    print(f"[join-big] rows={len(df):,}  {df.d.min().date()}..{df.d.max().date()}")
    return df


def load(year: int, *, need_ma100: bool = False) -> pd.DataFrame:
    blayer = BLAYER_TMPL.format(year=year)
    if not os.path.exists(blayer):
        raise FileNotFoundError(f"B 层不存在: {blayer}")
    px_start = f"{year - 1}-06-01" if need_ma100 else f"{year - 1}-12-01"
    gap = f"{year}-01-02"
    con = duckdb.connect()
    dmin, dmax, nrow = con.execute(
        f"SELECT min(d), max(d), count(*) FROM read_parquet('{blayer}')"
    ).fetchone()
    dmax_s = pd.Timestamp(dmax).strftime("%Y-%m-%d")
    print(f"[blayer] {blayer}  rows={nrow:,}  {dmin}..{dmax}")
    ma100_expr = (
        "avg(close_px) OVER (PARTITION BY stock_code ORDER BY d "
        "ROWS BETWEEN 99 PRECEDING AND CURRENT ROW) ma100,"
        if need_ma100
        else "CAST(NULL AS DOUBLE) ma100,"
    )
    df = con.execute(f"""
        WITH px AS (
          SELECT stock_code, CAST(d AS DATE) d,
                 open_px, high_px, low_px, close_px, total_amt,
                 lag(open_px)  OVER (PARTITION BY stock_code ORDER BY d) po,
                 lag(high_px)  OVER (PARTITION BY stock_code ORDER BY d) ph,
                 lag(low_px)   OVER (PARTITION BY stock_code ORDER BY d) pl,
                 lag(close_px) OVER (PARTITION BY stock_code ORDER BY d) pc,
                 lag(close_px, 2) OVER (PARTITION BY stock_code ORDER BY d) pc2,
                 lead(close_px) OVER (PARTITION BY stock_code ORDER BY d) t1_close,
                 avg(close_px) OVER (
                   PARTITION BY stock_code ORDER BY d
                   ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
                 ) ma5,
                 avg(close_px) OVER (
                   PARTITION BY stock_code ORDER BY d
                   ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                 ) ma20,
                 {ma100_expr}
                 1 AS _
          FROM read_parquet('{ROLLUP}', hive_partitioning=false)
          WHERE d >= DATE '{px_start}'
        ),
        big AS (
          SELECT CAST(d AS DATE) d, stock_code,
                 buyord10w_vol bov, saleord10w_vol sov,
                 buyord10w_amt bam, saleord10w_amt sam,
                 lag(buyord10w_vol) OVER (PARTITION BY stock_code ORDER BY d) prev_bov
          FROM read_parquet('{blayer}')
        ),
        ff AS (
          SELECT stock_code, CAST(m_timetag AS DATE) d, freeFloatCapital ffv
          FROM read_parquet('{FF}') WHERE freeFloatCapital > 0
        )
        SELECT p.stock_code, p.d, p.open_px, p.high_px, p.low_px, p.close_px, p.total_amt,
               p.po, p.ph, p.pl, p.pc, p.pc2, p.t1_close, p.ma5, p.ma20, p.ma100,
               b.bov, b.sov, b.bam, b.sam, b.prev_bov, f.ffv
        FROM px p
        LEFT JOIN big b USING (stock_code, d)
        ASOF LEFT JOIN ff f ON p.stock_code = f.stock_code AND p.d >= f.d
        WHERE p.d >= DATE '{gap}'
          AND p.d <= DATE '{dmax_s}'
    """).fetchdf()
    df["d"] = pd.to_datetime(df["d"]).dt.normalize()
    print(f"[join] rows={len(df):,}  {df.d.min().date()}..{df.d.max().date()}")
    return df


def _feats(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["nfr"] = (out["bov"] - out["sov"]) / out["ffv"]
    out["ret_p"] = out["pc"] / out["pc2"] - 1.0
    out["ret_1d"] = out["close_px"] / out["pc"] - 1.0
    out["bs"] = out["bam"] / out["total_amt"]
    out["nbam"] = out["bam"] - out["sam"]
    out["c1"] = (out["prev_bov"] > 0) & (out["bov"] >= 2.0 * out["prev_bov"])
    out["amp_p"] = (out["ph"] - out["pl"]) / out["pc"]
    out["c1_quiet"] = (
        (out["open_px"] <= out["pc"] * 1.02)
        & (out["high_px"] <= out["pc"] * 1.04)
        & (out["close_px"] < out["pc"])
        & (out["close_px"] < out["open_px"])
        & (out["close_px"] > out["ma5"])
    )
    out["c4_quiet"] = (out["pc"] > out["po"]) & (out["amp_p"] < 0.05)
    return out


def apply_signal(name: str, df: pd.DataFrame, *, require_t1: bool) -> pd.DataFrame:
    name = _resolve(name)
    f = _feats(df)
    if name == "STEP_DIP_ACCUM":
        m = (
            f["c1"]
            & f["ret_p"].notna()
            & f["ret_1d"].notna()
            & (f["ret_p"] < 0)
            & (f["ret_1d"] < 0)
            & (f["bs"] < 0.10)
            & f["bam"].notna()
            & (f["total_amt"] > 0)
        )
    elif name == "QUIET_DIP_TECH":
        m = f["c1_quiet"].fillna(False) & f["c4_quiet"].fillna(False)
    elif name == "QUIET_DIP_ACCUM":
        m = (
            f["c1_quiet"].fillna(False)
            & (f["nfr"] > 0.02)
            & f["ret_p"].notna()
            & (f["ret_p"] <= 0.05)
            & f["c4_quiet"].fillna(False)
            & f["bov"].notna()
            & (f["ffv"] > 0)
        )
    elif name == "MEGA_ORDER_ACCUM":
        # 只依赖 B 层 + 流通；不要求价域 lag（否则丢 01-05 等黄金行）
        m = (f["nfr"] > 0.05) & f["bov"].notna() & (f["ffv"] > 0)
    elif name == "VOL_SURGE_BUY":
        m = (
            f["c1"]
            & (f["bov"] > f["sov"])
            & f["ma20"].notna()
            & f["ma100"].notna()
            & (f["close_px"] > f["ma20"])
            & (f["close_px"] > f["ma100"])
            & (f["nbam"] > 3e7)
            & f["bam"].notna()
        )
    elif name == "DIP_CATCH_FALL":
        m = (
            f["pc"].notna()
            & (f["close_px"] < f["pc"])
            & (f["nfr"] > 0.02)
            & f["bov"].notna()
            & (f["ffv"] > 0)
        )
    else:
        raise KeyError(f"unknown signal: {name}")

    if require_t1:
        m = m & f["t1_close"].notna()

    out = f.loc[m].copy()
    if len(out) and out["t1_close"].notna().any():
        out["ret1"] = out["t1_close"] / out["close_px"] - 1.0
        out["win"] = (out["t1_close"] > out["close_px"]).astype("Int64")
        # 无 T+1 的行 win/ret1 置空
        no_t1 = out["t1_close"].isna()
        out.loc[no_t1, "ret1"] = pd.NA
        out.loc[no_t1, "win"] = pd.NA
    else:
        out["ret1"] = pd.NA
        out["win"] = pd.NA
    return out.sort_values(["d", "stock_code"])


def check_gold(name: str, sub: pd.DataFrame) -> None:
    if name not in GOLD:
        print(f"[gold] {name}: 无黄金 CSV（跳过对拍）")
        return
    path, dcol, ccol = GOLD[name]
    if not os.path.exists(path):
        print(f"[gold] 缺失: {path}")
        return
    gold = pd.read_csv(path)
    gold["d"] = pd.to_datetime(gold[dcol]).dt.normalize()
    gold["stock_code"] = gold[ccol].astype(str)
    gset = set(zip(gold["d"], gold["stock_code"]))
    sset = set(zip(sub["d"], sub["stock_code"]))
    hit, miss, extra = len(gset & sset), len(gset - sset), len(sset - gset)
    tag = "EXACT" if gset == sset else ("COVER_GOLD" if miss == 0 else "partial")
    print(
        f"[gold] {name}  gold={len(gset)} repro={len(sset)}  "
        f"hit={hit} miss={miss} extra={extra}  [{tag}]"
    )
    if miss and miss <= 8:
        print("  miss sample:", sorted(gset - sset)[:8])
    if extra and extra <= 8 and miss == 0:
        print("  extra sample:", sorted(sset - gset)[:8])


def report(name: str, sub: pd.DataFrame, year: int) -> None:
    n = len(sub)
    scored = sub.dropna(subset=["win"])
    print(f"[{name} @{year}] n={n}", end="")
    if len(scored):
        print(
            f"  (有T+1={len(scored)})  wr={scored.win.mean()*100:.1f}%  "
            f"avg={scored.ret1.mean()*100:+.2f}%"
        )
        h2 = scored["d"] >= pd.Timestamp(f"{year}-07-01")
        h1, h2s = scored[~h2], scored[h2]
        if len(h1):
            print(f"  H1 n={len(h1)}  wr={h1.win.mean()*100:.1f}%  avg={h1.ret1.mean()*100:+.2f}%")
        if len(h2s):
            print(f"  H2 n={len(h2s)}  wr={h2s.win.mean()*100:.1f}%  avg={h2s.ret1.mean()*100:+.2f}%")
    else:
        print("  （无 T+1 可评分）")


def save(name: str, sub: pd.DataFrame, year: int, out_path: str) -> None:
    cols = [
        "d", "stock_code", "close_px", "open_px", "t1_close", "ret1", "win",
        "nfr", "ret_p", "ret_1d", "bs", "nbam", "bov", "sov", "ffv", "prev_bov",
        "ma5", "ma20", "ma100",
    ]
    cols = [c for c in cols if c in sub.columns]
    out = sub[cols].copy()
    out["d"] = out["d"].dt.date
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"[out] {out_path}")


def run_one(name: str, year: int, out: str, require_t1: bool) -> None:
    name = _resolve(name)
    if name not in SIGNALS:
        raise SystemExit(f"unknown signal {name}; choose from {SIGNALS + list(ALIASES)}")
    need_ma100 = name == "VOL_SURGE_BUY"
    if name in ("MEGA_ORDER_ACCUM", "DIP_CATCH_FALL"):
        df = load_mega_like(year)
    else:
        df = load(year, need_ma100=need_ma100)
    # MEGA/DIP 黄金 CSV 含末日无 T+1 行；默认不对这两族强制 T+1（可用 --require-t1 覆盖）
    if require_t1:
        use_t1 = True
    elif name in ("MEGA_ORDER_ACCUM", "DIP_CATCH_FALL"):
        use_t1 = False
    else:
        use_t1 = True
    sub = apply_signal(name, df, require_t1=use_t1)
    report(name, sub, year)
    if year == 2026:
        check_gold(name, sub)
    out_path = out or os.path.join(OUT_DIR, f"{name.lower()}_{year}.csv")
    save(name, sub, year, out_path)


def main() -> None:
    ap = argparse.ArgumentParser(description="Reproduce gen0 L2 signal families")
    ap.add_argument("--signal", default="ALL", help="信号代号或 ALL")
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--out", default="", help="单信号输出路径（ALL 时忽略）")
    ap.add_argument("--list", action="store_true")
    ap.add_argument(
        "--require-t1",
        action="store_true",
        default=False,
        help="强制所有族要求存在 T+1（默认 MEGA/DIP 对拍时不要求）",
    )
    args = ap.parse_args()
    if args.list:
        for s in SIGNALS:
            print(s)
        for a, t in ALIASES.items():
            print(f"{a} -> {t}")
        return

    targets = SIGNALS if args.signal.upper() == "ALL" else [_resolve(args.signal)]
    for name in targets:
        print("=" * 60)
        try:
            run_one(
                name,
                args.year,
                args.out if len(targets) == 1 else "",
                require_t1=args.require_t1,
            )
        except Exception as e:
            print(f"[error] {name}: {e}", file=sys.stderr)
            raise


if __name__ == "__main__":
    main()
