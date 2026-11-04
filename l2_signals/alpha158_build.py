"""Alpha158 因子构建：core rollup OHLCV → 158 因子 parquet。

因子集与表达式严格对齐 qlib 官方 Alpha158DL（l2_signals/alpha158_spec.json），
滚动算子语义复刻 qlib/data/ops.py（详见 README「qlib 语义复刻要点」）。

用法（vanna312 环境）：
    D:/anaconda3/envs/vanna312/python.exe l2_signals/alpha158_build.py
    D:/anaconda3/envs/vanna312/python.exe l2_signals/alpha158_build.py --selftest
    D:/anaconda3/envs/vanna312/python.exe l2_signals/alpha158_build.py --start 2025-01-01 --chunk 400

数据流：只读 J:/ 湖全历史（保证 2026 年初窗口已满 60 日），输出 d>=--start 的长表。
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = json.load(open(os.path.join(HERE, "alpha158_spec.json")))

ROLLUP = "J:/l2_lake/rollup/daily_stock/version=l2-daily-v3/params=a2e3a427af892982d0ce/date=*/part.parquet"
DEFAULT_OUT = "E:/stock_data/l2_research/alpha158_daily.parquet"
WINDOWS = [5, 10, 20, 30, 60]
EPS = 1e-12
STD_ATOL = 2e-05  # qlib Rsquare/Corr 的零波动掩码阈值


# ---------------------------------------------------------------- qlib 对拍算子
def ols_trio(x: np.ndarray, w: int):
    """窗口 OLS：slope/rsquare/resi，对拍 qlib.data._libs.rolling。

    x: (T, S)。返回三个 (T, S) 数组；前 w-1 行按 min_periods=1 用前缀窗口补齐。
    """
    T, S = x.shape
    slope = np.full((T, S), np.nan)
    rsqr = np.full((T, S), np.nan)
    resi = np.full((T, S), np.nan)
    if T >= w:
        Wv = np.lib.stride_tricks.sliding_window_view(x, w, axis=0)  # (T-w+1, S, w)
        i = np.arange(w, dtype=np.float64)
        sy = Wv.sum(-1)                      # Σy
        syy = np.einsum("tsw,tsw->ts", Wv, Wv, optimize=True)  # Σy²
        sxiy = Wv @ i                        # Σ(i·y)
        b = (w * sxiy - i.sum() * sy) / (w * float(i @ i) - i.sum() ** 2)  # slope
        a = sy / w - b * i.mean()            # intercept
        ss_tot = syy - sy * sy / w
        ss_res = syy - a * sy - b * sxiy     # OLS 恒等式
        with np.errstate(divide="ignore", invalid="ignore"):
            r2 = 1.0 - ss_res / ss_tot
        r2[~np.isfinite(r2)] = np.nan
        r2[np.isclose(np.sqrt(ss_tot / (w - 1)), 0.0, atol=STD_ATOL)] = np.nan  # qlib 零波动掩码
        slope[w - 1:] = b
        rsqr[w - 1:] = r2
        resi[w - 1:] = x[w - 1:] - (a + b * i[-1])
    # 前缀窗口（min_periods=1），逐长度向量化
    for t in range(T):
        n = t + 1
        if n >= w:
            break
        y = x[: n]
        i = np.arange(n, dtype=np.float64)
        im = i - i.mean()
        sy = y.sum(0)
        syy = np.einsum("ts,ts->s", y, y, optimize=True)
        sxiy = y.T @ i
        b = (n * sxiy - i.sum() * sy) / (n * float(i @ i) - i.sum() ** 2)
        a = sy / n - b * i.mean()
        slope[t] = b
        resi[t] = x[t] - (a + b * i[-1])
        ss_tot = syy - sy * sy / n
        ss_res = syy - a * sy - b * sxiy
        with np.errstate(divide="ignore", invalid="ignore"):
            r2 = 1.0 - ss_res / ss_tot
        if n >= 2:
            r2 = np.where(np.isclose(np.sqrt(ss_tot / (n - 1)), 0.0, atol=STD_ATOL), np.nan, r2)
        else:
            r2 = np.full(S, np.nan)
        rsqr[t] = r2
    return slope, rsqr, resi


def idx_extreme(x: np.ndarray, w: int, kind: str):
    """IdxMax/IdxMin：窗口内 argmax+1（1 基，含 NaN 与 np.argmax 一致的怪癖）。"""
    T, S = x.shape
    out = np.full((T, S), np.nan)
    if T >= w:
        Wv = np.lib.stride_tricks.sliding_window_view(x, w, axis=0)
        fn = np.argmax if kind == "max" else np.argmin
        out[w - 1:] = fn(Wv, axis=-1) + 1
    for t in range(min(w - 1, T)):
        seg = x[: t + 1]
        fn = np.argmax if kind == "max" else np.argmin
        out[t] = fn(seg, axis=0) + 1
    return out


def selftest():
    """对拍 qlib Cython 实现与 pandas 语义。"""
    from qlib.data._libs.rolling import rolling_slope, rolling_rsquare, rolling_resi

    rng = np.random.RandomState(7)
    x = rng.randn(200) * 3 + 10
    x[50] = np.nan  # 带 NaN 段两侧对拍
    for w in (3, 5, 20):
        col = x[:, None]
        s, r, e = ols_trio(col, w)
        qs, qr, qe = rolling_slope(x, w), rolling_rsquare(x, w), rolling_resi(x, w)
        qs[np.isnan(x)] = np.nan  # qlib 输入端 NaN 天直接 NaN 对齐比较
        for mine, ref, name in ((s[:, 0], qs, "slope"), (r[:, 0], qr, "rsqr"), (e[:, 0], qe, "resi")):
            both = ~np.isnan(mine) & ~np.isnan(ref)
            assert both.sum() > 10, f"{name} w={w} 对拍样本不足"
            diff = np.abs(mine[both] - ref[both])
            assert diff.max() < 1e-9, f"{name} w={w} 最大偏差 {diff.max()}"
    # Rank pct 语义：pandas rolling rank == percentileofscore(kind='mean')
    from scipy.stats import percentileofscore
    ser = pd.Series(rng.randn(50))
    mine = ser.rolling(10, min_periods=1).rank(pct=True).iloc[20]
    ref = percentileofscore(ser.iloc[11:21].values, ser.iloc[20]) / 100
    assert abs(mine - ref) < 1e-12, (mine, ref)
    print("[selftest] ols_trio vs qlib._libs: OK; rolling rank pct: OK")


# ---------------------------------------------------------------- 因子计算
def compute_factors(chunk: pd.DataFrame) -> pd.DataFrame:
    """一个股票块（长表 date×stock×六基础列）→ 长表 d/stock_code + 158 因子。"""
    dates = np.sort(chunk["d"].unique())
    stocks = chunk["stock_code"].unique()
    piv = {}
    for col, name in (("open_px", "O"), ("high_px", "H"), ("low_px", "L"),
                      ("close_px", "C"), ("vwap", "VW"), ("total_vol", "V")):
        piv[name] = chunk.pivot(index="d", columns="stock_code", values=col).reindex(dates)[stocks]
    O, H, L, C, VW, V = (piv[k] for k in ("O", "H", "L", "C", "VW", "V"))

    C1 = C.shift(1)
    V1 = V.shift(1)
    dC, aC = C - C1, (C - C1).abs()
    dV, aV = V - V1, (V - V1).abs()
    up = (dC > 0).astype(float)
    dn = (dC < 0).astype(float)
    vu = (dV > 0).astype(float)
    vd = (dV < 0).astype(float)
    lv = np.log(V + 1)
    cl = C / C1
    vr = np.log(V / V1 + 1)
    wv = (C / C1 - 1).abs() * V
    upC = np.maximum(dC, 0)
    dnC = np.maximum(-dC, 0)
    upV = np.maximum(dV, 0)
    dnV = np.maximum(-dV, 0)

    F = {}
    rng = (H - L)
    F["KMID"], F["KLEN"] = (C - O) / O, rng / O
    F["KMID2"] = (C - O) / (rng + EPS)
    F["KUP"], F["KUP2"] = (H - np.maximum(O, C)) / O, (H - np.maximum(O, C)) / (rng + EPS)
    F["KLOW"], F["KLOW2"] = (np.minimum(O, C) - L) / O, (np.minimum(O, C) - L) / (rng + EPS)
    F["KSFT"], F["KSFT2"] = (2 * C - H - L) / O, (2 * C - H - L) / (rng + EPS)
    F["OPEN0"], F["HIGH0"], F["LOW0"], F["VWAP0"] = O / C, H / C, L / C, VW / C

    def roll(df, w, fn, q=None):
        r = df.rolling(w, min_periods=1)
        return r.quantile(q) if q is not None else getattr(r, fn)()

    for w in WINDOWS:
        sl, rq, rs = ols_trio(C.to_numpy(dtype=np.float64), w)
        sl, rq, rs = pd.DataFrame(sl, index=dates, columns=stocks), pd.DataFrame(rq, index=dates, columns=stocks), pd.DataFrame(rs, index=dates, columns=stocks)
        mxH, mnL = roll(H, w, "max"), roll(L, w, "min")
        imx = idx_extreme(H.to_numpy(dtype=np.float64), w, "max")
        imn = idx_extreme(L.to_numpy(dtype=np.float64), w, "min")
        F[f"ROC{w}"] = C.shift(w) / C
        F[f"MA{w}"] = roll(C, w, "mean") / C
        F[f"STD{w}"] = roll(C, w, "std") / C
        F[f"BETA{w}"] = sl / C
        F[f"RSQR{w}"] = rq
        F[f"RESI{w}"] = rs / C
        F[f"MAX{w}"] = mxH / C
        F[f"MIN{w}"] = mnL / C
        F[f"QTLU{w}"] = roll(C, w, "quantile", 0.8) / C
        F[f"QTLD{w}"] = roll(C, w, "quantile", 0.2) / C
        F[f"RANK{w}"] = roll(C, w, "rank")
        F[f"RSV{w}"] = (C - mnL) / (mxH - mnL + EPS)
        F[f"IMAX{w}"] = pd.DataFrame(imx, index=dates, columns=stocks) / w
        F[f"IMIN{w}"] = pd.DataFrame(imn, index=dates, columns=stocks) / w
        F[f"IMXD{w}"] = pd.DataFrame((imx - imn) / w, index=dates, columns=stocks)
        corr = C.rolling(w, min_periods=1).corr(lv)
        corr = corr.mask(np.isclose(C.rolling(w, min_periods=1).std(), 0, atol=STD_ATOL) |
                         np.isclose(lv.rolling(w, min_periods=1).std(), 0, atol=STD_ATOL))
        F[f"CORR{w}"] = corr
        cord = cl.rolling(w, min_periods=1).corr(vr)
        cord = cord.mask(np.isclose(cl.rolling(w, min_periods=1).std(), 0, atol=STD_ATOL) |
                         np.isclose(vr.rolling(w, min_periods=1).std(), 0, atol=STD_ATOL))
        F[f"CORD{w}"] = cord
        F[f"CNTP{w}"], F[f"CNTN{w}"] = roll(up, w, "mean"), roll(dn, w, "mean")
        F[f"CNTD{w}"] = F[f"CNTP{w}"] - F[f"CNTN{w}"]
        F[f"SUMP{w}"] = roll(upC, w, "sum") / (roll(aC, w, "sum") + EPS)
        F[f"SUMN{w}"] = roll(dnC, w, "sum") / (roll(aC, w, "sum") + EPS)
        F[f"SUMD{w}"] = (roll(upC, w, "sum") - roll(dnC, w, "sum")) / (roll(aC, w, "sum") + EPS)
        F[f"VMA{w}"] = roll(V, w, "mean") / (V + EPS)
        F[f"VSTD{w}"] = roll(V, w, "std") / (V + EPS)
        F[f"WVMA{w}"] = roll(wv, w, "std") / (roll(wv, w, "mean") + EPS)
        F[f"VSUMP{w}"] = roll(upV, w, "sum") / (roll(aV, w, "sum") + EPS)
        F[f"VSUMN{w}"] = roll(dnV, w, "sum") / (roll(aV, w, "sum") + EPS)
        F[f"VSUMD{w}"] = (roll(upV, w, "sum") - roll(dnV, w, "sum")) / (roll(aV, w, "sum") + EPS)

    got = sorted(F)
    want = sorted(SPEC["names"])
    assert got == want, f"因子名单不一致: 多={set(got)-set(want)} 少={set(want)-set(got)}"

    out = pd.DataFrame({
        "d": np.repeat(dates, len(stocks)),
        "stock_code": np.tile(stocks, len(dates)),
    })
    arrs = {k: v.to_numpy(dtype=np.float32).ravel() for k, v in F.items()}
    out = pd.concat([out, pd.DataFrame(arrs, index=out.index)], axis=1)
    out = out[out["ROC60"].notna() | out["MA5"].notna()]  # 至少有一个因子非空
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--start", default="2025-01-01", help="输出日期下界（滚动窗口仍用全历史）")
    ap.add_argument("--chunk", type=int, default=400, help="每块股票数")
    ap.add_argument("--limit-chunks", type=int, default=0, help=">0 时试跑指定块数")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return

    selftest()

    t0 = time.time()
    lf = pl.scan_parquet(ROLLUP, hive_partitioning=False).select(
        ["stock_code", "d", "open_px", "high_px", "low_px", "close_px", "vwap", "total_vol"]
    ).collect()
    df = lf.to_pandas()
    df["d"] = pd.to_datetime(df["d"]).dt.date
    df = df.sort_values(["stock_code", "d"])
    stocks = sorted(df["stock_code"].unique())
    print(f"[load] {len(df):,} 行 × {len(stocks)} 票  {time.time()-t0:.0f}s")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    writer = None
    start = pd.to_datetime(args.start).date()
    n_done = 0
    for ci in range(0, len(stocks), args.chunk):
        block = stocks[ci: ci + args.chunk]
        sub = df[df["stock_code"].isin(block)]
        res = compute_factors(sub)
        res = res[res["d"] >= start]
        if len(res) == 0:
            continue
        res = res.sort_values(["d", "stock_code"])
        table = pa.Table.from_pandas(res, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(args.out, table.schema, compression="zstd")
        writer.write_table(table)
        n_done += 1
        print(f"[chunk {n_done}] {block[0]}..{block[-1]}  rows={len(res):,}  {time.time()-t0:.0f}s", flush=True)
        if args.limit_chunks and n_done >= args.limit_chunks:
            break
    if writer:
        writer.close()
        n = pq.ParquetFile(args.out).metadata.num_rows
        print(f"[done] {args.out}  rows={n:,}  {time.time()-t0:.0f}s")
    else:
        print("[done] 无输出行")


if __name__ == "__main__":
    sys.exit(main())
