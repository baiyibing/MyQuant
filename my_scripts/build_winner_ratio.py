"""构建每日获利盘比例（CYQ winner ratio）——数据源 = qlib bins，零外部依赖。

算法 = backtrader 仓 qlib_cost.cyq 的 SSOT 递推（Rust turnover-resist 同族）：
- 每日成交量按三角分布摊到 [low, high] 价格网格（0.01 元步长），归一化使当日质量 = vol
- 旧筹码按换手率衰减：cumpdf_t = cumpdf_{t-1}*(1-turn_t) + curpdf_t*turn_t
- winner_ratio(T) = T 日收盘价及以下的筹码占比（cyqk_c / get_winner）

数据口径（2026-09-14 交叉验证）：
- 价格用后复权 $close/$high/$low（同一复权空间；窗内与前复权只差全局尺度，
  winner_ratio 不变）。不要用 $adjclose 不复权价——除权后旧筹码会错位。
- 真实成交股数 = $amount/$adjclose（$volume 含后复权因子漂移，不可直接用）
- 换手率默认 $amount/($adjclose*$netcsfree)（自由流通，对 QMT 真值 Spearman 0.92）；
  --shares circ 则分母改 $basiccurhold*10000（流通股本，对齐 Rust cyqk_T 锚点）
- $basiccurhold 单位是万股； $netcsfree 单位是股
- 后复权跨度过大（茅台等）时自动放宽步长，避免 _MAX_GRID 丢票

产物是外部 parquet（与 ST 的 st_daily 同级），不 dump 进 qlib bins。
券商 CSV winratio 若日后进训练/表达式，走独立 bin 字段，与本产物无关。

用法::

    python build_winner_ratio.py --test 2026-01-01:2026-09-14 \
        [--out {OSKH_SOURCE_PARQUET_ROOT}/cyq_winner_ratio_daily_2026.parquet] [--workers 8]
        [--shares free|circ] [--codes SH688366,SZ002007]
"""

from __future__ import annotations

import argparse
import multiprocessing
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from data_root import resolve_source_parquet

_QLIB_DIR = Path.home() / ".qlib" / "qlib_data" / "my_data"
_DEFAULT_OUT = resolve_source_parquet("cyq_winner_ratio_daily_2026.parquet")
_MAX_GRID = 250_000  # 单股价格网格点数保护；超限则放宽 step


def _triang_into(
    grid: np.ndarray,
    low: float,
    high: float,
    close: float,
    vol: float,
    step: float,
    out: np.ndarray,
) -> None:
    """单日成交量按三角分布摊到 grid，归一化后 sum(out)=vol（SSOT calc_triang_pdf）。"""
    n = grid.shape[0]
    if vol <= 0 or n <= 0 or step <= 0:
        return
    if high < low:
        high, low = low, high
    if close < low:
        close = low
    elif close > high:
        close = high
    if (high - low) < 1e-12:
        idx = int((close - grid[0]) / step)
        if idx < 0:
            idx = 0
        elif idx >= n:
            idx = n - 1
        out[idx] += vol
        return
    c = (close - low) / (high - low)
    square_scale = (high - low) * (high - low)
    total = 0.0
    for i in range(n):
        p = grid[i]
        if p < low or p > high:
            continue
        if p <= close:
            if c == 0.0:
                pdf = 2.0 * (high - p) / square_scale
            elif (1.0 - c) < 1e-14:
                pdf = 2.0 * (p - low) / square_scale
            else:
                pdf = 2.0 * (p - low) / (c * square_scale)
        else:
            denom = square_scale * (1.0 - c)
            pdf = 0.0 if abs(denom) < 1e-15 else 2.0 * (high - p) / denom
        out[i] = pdf
        total += pdf
    if total > 1e-15:
        inv = vol / total
        for i in range(n):
            out[i] *= inv


def _stock_winner_ratio_impl(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    shares: np.ndarray,
    turnover: np.ndarray,
    date_pos: np.ndarray,
    capture_flag: np.ndarray,
    capture_slot: np.ndarray,
    step: float,
) -> np.ndarray:
    """逐日衰减递推 + 快照日 winner_ratio。

    date_pos/capture_flag/capture_slot 覆盖整个历史窗（日历相对位置）；
    out 长度 = capture 日个数；无效日（NaN）跳过递推且不产出（停牌冻结分布）。
    """
    n_hist = date_pos.shape[0]
    n_cap = int(capture_flag.sum())
    out = np.full(n_cap, np.nan)
    if n_hist < 10 or close.shape[0] != n_hist:
        return out

    gmin = float(np.nanmin(low))
    gmax = float(np.nanmax(high))
    if not np.isfinite(gmin) or not np.isfinite(gmax) or gmax < gmin:
        return out
    span = gmax - gmin
    if span < 1e-15:
        n_grid = 1
    else:
        n_grid = int(np.ceil(span / step)) + 1
        if n_grid > _MAX_GRID:
            step = span / float(_MAX_GRID - 1)
            n_grid = _MAX_GRID
    if n_grid < 1:
        return out

    grid = gmin + np.arange(n_grid) * step
    cumpdf = np.zeros(n_grid)
    first = True
    n_flag = capture_flag.shape[0]
    for j in range(n_hist):
        c = close[j]
        h = high[j]
        l = low[j]
        s = shares[j]
        d = turnover[j]
        if np.isnan(c) or np.isnan(h) or np.isnan(l) or np.isnan(s) or np.isnan(d):
            continue
        if s <= 0 or d < 0:
            continue
        cur = np.zeros(n_grid)
        _triang_into(grid, l, h, c, s, step, cur)
        if first:
            cumpdf = cur * d
            first = False
        else:
            cumpdf = cumpdf * (1.0 - d) + cur * d
        dp = int(date_pos[j])
        if dp < 0 or dp >= n_flag:
            continue
        if capture_flag[dp] == 1:
            total = float(cumpdf.sum())
            if total <= 0:
                continue
            pos = int(np.searchsorted(grid, c, side="right"))
            winner = float(cumpdf[:pos].sum()) / total if pos > 0 else 0.0
            out[int(capture_slot[dp])] = min(max(winner, 0.0), 1.0)
    return out


def _make_jit():
    """numba 可用则编译内核；不可用回落纯 python（慢但正确）。"""
    global _stock_winner_ratio_impl, _triang_into
    try:
        from numba import njit

        tri_pure = getattr(_triang_into, "py_func", None) or _triang_into
        impl_pure = getattr(_stock_winner_ratio_impl, "py_func", None) or _stock_winner_ratio_impl
        _triang_into = njit(cache=True)(tri_pure)
        _stock_winner_ratio_impl = njit(cache=True)(impl_pure)
    except Exception as exc:  # noqa: BLE001
        print(f"[build_winner_ratio] numba 不可用（{exc}），回落纯 python", flush=True)


_work_one_state = {"jit": False}


def _work_one(task):
    code, close, high, low, shares, turnover, date_pos, capture_flag, capture_slot, step = task
    if not _work_one_state["jit"]:
        _make_jit()
        _work_one_state["jit"] = True
    wr = _stock_winner_ratio_impl(
        close, high, low, shares, turnover, date_pos, capture_flag, capture_slot, step
    )
    return code, wr


def _snap_test_window(dates: pd.DatetimeIndex, pos: dict, d_s, d_e):
    i_end = pos.get(d_e)
    i_start = pos.get(d_s)
    if i_start is None:
        i_start = int(dates.searchsorted(pd.Timestamp(d_s)))
    if i_end is None:
        i_end = int(dates.searchsorted(pd.Timestamp(d_e))) - 1
    return i_start, i_end


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="CYQ 每日获利盘比例（qlib bins 数据源）")
    ap.add_argument("--test", required=True, help="测试窗 START:END")
    ap.add_argument("--window", type=int, default=1000, help="衰减回看交易日数（默认 1000，对齐 Rust）")
    ap.add_argument("--step", type=float, default=0.01)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default=str(_DEFAULT_OUT))
    ap.add_argument(
        "--shares",
        choices=("free", "circ"),
        default="free",
        help="换手分母：free=$netcsfree（默认，贴 QMT）；circ=$basiccurhold×10000（贴 Rust cyqk_T）",
    )
    ap.add_argument("--codes", default="", help="逗号分隔 QLib 代码，仅算这些（冒烟用）")
    args = ap.parse_args(argv)

    from datetime import datetime

    s, e = args.test.split(":", 1)
    d_s = datetime.strptime(s, "%Y-%m-%d")
    d_e = datetime.strptime(e, "%Y-%m-%d")

    import qlib
    from qlib.config import REG_CN
    from qlib.data import D

    from handler_frame_cache import resolve_qlib_kernels

    _kernels = resolve_qlib_kernels()
    print(f"[qlib] kernels={_kernels} (QLIB_KERNELS, default 1)", flush=True)
    qlib.init(provider_uri=str(_QLIB_DIR), region=REG_CN, kernels=_kernels)
    cal = D.calendar()
    dates = pd.DatetimeIndex(cal)
    pos = {d_: i for i, d_ in enumerate(dates)}

    i_start, i_end = _snap_test_window(dates, pos, d_s, d_e)
    if i_end is None or i_start is None or i_start > i_end or i_end >= len(dates):
        print(f"FAIL: 测试窗端点无法吸附到交易日 {s}/{e}", file=sys.stderr)
        return 2
    i_hist_start = max(0, i_start - args.window)
    hist_start = dates[i_hist_start]

    codes = sorted(
        D.list_instruments(D.instruments(market="all"), start_time=hist_start, end_time=d_e, as_list=True)
    )
    if args.codes:
        want = {c.strip().upper() for c in args.codes.split(",") if c.strip()}
        codes = [c for c in codes if str(c).upper() in want]
        if not codes:
            print(f"FAIL: --codes 无交集 {sorted(want)}", file=sys.stderr)
            return 2
    print(
        f"universe={len(codes)} shares={args.shares}  "
        f"历史 {hist_start.date()}~{dates[i_end].date()}（{i_end - i_hist_start + 1} 交易日）",
        flush=True,
    )

    fields = ["$close", "$high", "$low", "$adjclose", "$amount", "$netcsfree"]
    if args.shares == "circ":
        fields.append("$basiccurhold")
    fdf = D.features(codes, fields, start_time=hist_start, end_time=d_e)
    col_names = ["close", "high", "low", "adjclose", "amount", "netcsfree"]
    if args.shares == "circ":
        col_names.append("basiccurhold")
    fdf.columns = col_names
    fdf = fdf.reset_index()

    fdf["shares"] = np.where((fdf.adjclose > 0) & (fdf.amount > 0), fdf.amount / fdf.adjclose, np.nan)
    if args.shares == "circ":
        denom = fdf.basiccurhold * 10000.0
    else:
        denom = fdf.netcsfree
    fdf["turnover"] = np.where(denom > 0, fdf.shares / denom, np.nan)
    fdf["turnover"] = fdf.turnover.clip(0, 0.999)
    fdf["date_pos"] = fdf.datetime.map(pos) - i_hist_start
    print(
        f"特征行: {len(fdf)}  close 缺失率 {fdf.close.isna().mean():.2%}  "
        f"turnover 中位 {fdf.turnover.median():.4%}",
        flush=True,
    )

    capture_pos = np.arange(i_start, i_end + 1) - i_hist_start
    hist_len = i_end - i_hist_start + 1
    capture_flag = np.zeros(hist_len, dtype=np.int8)
    capture_flag[capture_pos] = 1
    capture_slot = np.zeros(hist_len, dtype=np.int64)
    capture_slot[capture_pos] = np.arange(capture_pos.shape[0])
    step = float(args.step)

    tasks = []
    for code, g in fdf.groupby("instrument", sort=False):
        g = g.sort_values("date_pos")
        tasks.append(
            (
                code,
                g["close"].to_numpy(np.float64),
                g["high"].to_numpy(np.float64),
                g["low"].to_numpy(np.float64),
                g["shares"].to_numpy(np.float64),
                g["turnover"].to_numpy(np.float64),
                g["date_pos"].to_numpy(np.int64),
                capture_flag,
                capture_slot,
                step,
            )
        )

    t0 = time.perf_counter()
    rows: list[pd.DataFrame] = []
    n_ok = 0
    capture_dates = dates[i_start : i_end + 1]

    def _collect(results):
        nonlocal n_ok
        for code, wr in results:
            if np.all(np.isnan(wr)):
                continue
            n_ok += 1
            rows.append(
                pd.DataFrame(
                    {
                        "stock_code": code,
                        "date": capture_dates[: len(wr)],
                        "winner_ratio": wr,
                    }
                ).dropna()
            )
            if n_ok % 500 == 0:
                print(f"  done {n_ok}  elapsed={time.perf_counter() - t0:.0f}s", flush=True)

    if args.workers <= 1:
        _collect(map(_work_one, tasks))
    else:
        with multiprocessing.get_context("spawn").Pool(args.workers) as pool:
            _collect(pool.imap_unordered(_work_one, tasks, chunksize=8))

    if not rows:
        print("FAIL: 无有效产出", file=sys.stderr)
        return 3
    out_df = pd.concat(rows, ignore_index=True)
    out_df["stock_code"] = out_df["stock_code"].astype(str)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp.parquet")
    out_df.to_parquet(tmp, index=False)
    os.replace(tmp, out_path)
    print(
        f"DONE stocks={n_ok}/{len(tasks)} rows={len(out_df)} elapsed={time.perf_counter() - t0:.0f}s -> {out_path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
