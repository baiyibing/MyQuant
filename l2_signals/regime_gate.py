"""事前 regime gate 研究：STAB_LOW_TREND 的环境条件（2026-11-05，①号研究题）。

考题（八-G 钉死的验证集）：2023H1 须关 / 2024 须关 / 2025-01 须开 /
2025-07~09 须关 / 2026 须开。滚动胜率门控是结果变量（2023 失效），
本脚本找事前可观测变量。

gate = 聚簇 × 长期位置 × 当日市场强度（全部 T 日收盘可观测，信号 T 尾盘买，无前视）：
- N >= 5                 当日信号并发数（八-B 聚簇诊断的 regime 化）
- 长期OK                  上证 MA200 60日斜率 > 0（牛市）或 距52周高点回撤 > -10%（浅回调）
- idx_ret1 > -1%          上证当日非崩盘日

两种判卷口径（详见 docs/l2_signals/2026-11-05-regime-gate-research.md）：
- 计入率口径（严）：关段计入<=30%、开段计入>=70% —— 4/5，唯一失分是 2026 计入 0.57，
  但被剔的 95 笔 2026 信号胜率仅 40.0%（弱月），gate 在经济上是对的；
- 经济口径：关段中和（胜率回到池基线附近）、开段保价值 —— 5/5。

注意：本 gate 的变量族与阈值（整数标准值）是在考题集上调形选定的，属样本内；
真样本外 = 2025Q4 补验 + 2027。多重检验风险见研究笔记第六节。

用法：
    D:/anaconda3/envs/vanna312/python.exe l2_signals/regime_gate.py
    ... regime_gate.py --index <000001_SH data.parquet> --sig-dir <signals 目录>
"""
import argparse
import os

import duckdb
import pandas as pd

SIG_DIR = "E:/stock_data/l2_research/signals"
INDEX = "E:/stock_data/index/period=1d/dividend_type=none/symbol=000001_SH/data.parquet"
YEARS = (2023, 2024, 2025, 2026)

# 考题段（月前缀 → 须开/须关；未列出的月份不考）
EXAM = [(f"2023-{m:02d}", 0) for m in range(1, 7)] + \
       [(f"2024-{m:02d}", 0) for m in range(1, 13)] + \
       [("2025-01", 1)] + \
       [(f"2025-{m:02d}", 0) for m in (7, 8, 9)] + \
       [(f"2026-{m:02d}", 1) for m in range(1, 13)]
OPEN_SEGS = {"25-01(开)", "2026(开)"}


def load_index(path: str) -> pd.DataFrame:
    con = duckdb.connect()
    idx = con.execute(f"""
        SELECT CAST(to_timestamp(time/1000) AS DATE) d, close FROM read_parquet('{path}')
        WHERE close > 0 AND time/1000 >= 946684800 ORDER BY d""").df()
    idx["ma200"] = idx["close"].rolling(200).mean()
    idx["ma200_slope"] = idx["ma200"] / idx["ma200"].shift(60) - 1.0
    idx["dd250"] = idx["close"] / idx["close"].rolling(250).max() - 1.0
    idx["idx_ret1"] = idx["close"].pct_change()
    idx["d"] = pd.to_datetime(idx["d"])
    return idx


def load_signals(sig_dir: str, years=None) -> pd.DataFrame:
    use_years = years or YEARS
    sig = pd.concat([pd.read_csv(os.path.join(sig_dir, f"stab_low_trend_{y}.csv"))
                     for y in use_years], ignore_index=True)
    sig["d"] = pd.to_datetime(sig["d"])
    sig = sig.sort_values("d").reset_index(drop=True)
    sig["N"] = sig.groupby("d")["stock_code"].transform("size")
    return sig


def segment(month: str) -> str:
    # 2020-2022 为 gate 真样本外段（变量族/阈值调形只见 2023-2026）：
    # 2020 V型修复（裸信号无α，须关）/ 2021 结构市（显著负α，须关）/
    # 2022 大熊（全年看须关；H1 反弹段不计入原考题）
    if month <= "2022-12": return "20-22(关)"
    if month <= "2023-06": return "23H1(关)"
    if month <= "2023-12": return "23H2(不考)"
    if month <= "2024-12": return "2024(关)"
    if month == "2025-01": return "25-01(开)"
    if month <= "2025-06": return "25H1(不考)"
    if month <= "2025-09": return "25H2(关)"
    return "2026(开)"


def apply_gate(df: pd.DataFrame, n_min: int = 5) -> pd.Series:
    long_ok = (df["ma200_slope"] > 0) | (df["dd250"] > -0.10)
    return (df["N"] >= n_min) & long_ok & (df["idx_ret1"] > -0.01)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sig-dir", default=SIG_DIR)
    ap.add_argument("--index", default=INDEX)
    ap.add_argument("--n-min", type=int, default=5, help="聚簇门槛（默认 5；10=保守档）")
    ap.add_argument("--years", default=None,
                    help="信号年份列表，如 2020,2021,2022（默认 2023-2026 调形窗）")
    args = ap.parse_args()

    years = tuple(int(y) for y in args.years.split(",")) if args.years else None
    df = load_signals(args.sig_dir, years).merge(
        load_index(args.index)[["d", "ma200_slope", "dd250", "idx_ret1"]], on="d", how="left")
    df["m"] = df["d"].dt.strftime("%Y-%m")
    df["seg"] = df["m"].map(segment)
    df["on"] = apply_gate(df, args.n_min)

    print("==== 段级判卷 ====")
    rows = []
    for s, sub in df.groupby("seg"):
        if "不考" in s:
            continue
        need = "开" if s in OPEN_SEGS else "关"
        frac = sub["on"].mean()
        has_on = bool(sub["on"].any())
        wr_on = sub.loc[sub["on"], "win"].mean() if has_on else None
        strict = (frac >= 0.7) if need == "开" else (frac <= 0.3)
        rows.append({"段": s, "须": need, "裸wr": round(sub["win"].mean(), 3),
                     "计入率": round(frac, 3), "计入n": int(sub["on"].sum()),
                     "计入wr": round(wr_on, 3) if wr_on is not None else None,
                     "严口径": "✓" if strict else "✗"})
    t = pd.DataFrame(rows)
    print(t.to_string(index=False))
    print(f"严口径 {(t['严口径'] == '✓').sum()}/{len(t)}（2026 计入率失分的归因见模块头）")

    print("\n==== 按年（含不考段）====")
    yr = df.groupby(df["d"].dt.year).apply(
        lambda s: pd.Series({"裸n": len(s), "裸wr": s["win"].mean(),
                             "计入n": int(s["on"].sum()),
                             "计入wr": s.loc[s["on"], "win"].mean() if s["on"].any() else None,
                             "计入ret": s.loc[s["on"], "ret1"].mean() if s["on"].any() else None}))
    kept = df[df["on"]]
    yr.loc["合计"] = {"裸n": len(df), "裸wr": df["win"].mean(), "计入n": len(kept),
                     "计入wr": kept["win"].mean(), "计入ret": kept["ret1"].mean()}
    print(yr.round(3).to_string())

    print("\n==== 月度（仅显示有计入的月）====")
    mo = df[df["on"]].groupby("m").agg(on_n=("win", "size"), on_wr=("win", "mean"),
                                       on_ret=("ret1", "mean"), N=("N", "mean"))
    print(mo.round(3).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
