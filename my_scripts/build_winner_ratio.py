"""构建每日获利盘比例（CYQ winner ratio）——数据源 = qlib bins，零外部依赖。

算法 = backtrader 仓 qlib_cost.cyq 的 SSOT 递推（Rust turnover-resist 同族）：
- 每日成交量按三角分布摊到 [low, high] 原始价格网格（0.01 元步长）
- 旧筹码按换手率衰减：cumpdf_t = cumpdf_{t-1}*(1-turn_t) + curpdf_t*turn_t
- winner_ratio(T) = T 日收盘价以下的筹码占比（cyqk_c）

数据自洽处理（2026-09-14 交叉验证发现）：
- bins 的 $volume 含后复权因子漂移（浦发 8.6x/平安 166x/宁德 1.8x），不可直接用；
  真实成交股数 = $amount/$adjclose；换手率 = $amount/($adjclose*$netcsfree)
- $netcsfree = 自由流通股本（用户确认），逐日覆盖
- bins 的 high/low/open/vwap 均为后复权（浦发 20260908: high=88.16 vs adjclose=9.28）：
  逐日换算因子 factor = $adjclose/$close 把 high/low 拉回原始价空间，筹码网格用原始价
- 换手率/股数自洽：真实成交股数 = $amount/$adjclose

用法::

    python build_winner_ratio.py --test 2026-01-01:2026-09-08 \
        [--out F:/stock_data/cyq_winner_ratio_daily_2026.parquet] [--workers 8]

输出 parquet: stock_code(QLib 形), date, winner_ratio（测试窗每个交易日 × 全市场）
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

_QLIB_DIR = Path.home() / ".qlib" / "qlib_data" / "my_data"
_DEFAULT_OUT = Path("F:/stock_data/cyq_winner_ratio_daily_2026.parquet")
_MAX_GRID = 250_000  # 单股价格网格点数保护（对齐 Rust 口径）


def _triang_into(grid: np.ndarray, low: float, high: float, close: float, vol: float, out: np.ndarray) -> None:
    """单日成交量按三角分布摊到 grid（峰值在 close），累加进 out。退化情形用点质量。"""
    n = grid.shape[0]
    if vol <= 0 or high <= 0 or low < 0 or high < low:
        return
    if (high - low) < 1e-9 or (close - low) < 1e-9 or (high - close) < 1e-9:
        idx = int(np.searchsorted(grid, close))
        if idx >= n:
            idx = n - 1
        out[idx] += vol
        return
    for i in range(n):
        p = grid[i]
        if p < low or p > high:
            continue
        if p <= close:
            out[i] += vol * 2.0 * (p - low) / ((high - low) * (close - low))
        else:
            out[i] += vol * 2.0 * (high - p) / ((high - low) * (high - close))


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
    out 长度 = capture_pos 个数；无效日（NaN）跳过递推且不产出。
    """
    n_hist = date_pos.shape[0]
    n_cap = int(capture_flag.sum())
    out = np.full(n_cap, np.nan)
    if n_hist < 10 or close.shape[0] != n_hist:
        return out

    gmin = float(np.nanmin(low)); gmax = float(np.nanmax(high))
    n_grid = int((gmax - gmin) / step) + 1
    if n_grid <= 1 or n_grid > _MAX_GRID:
        return out

    grid = gmin + np.arange(n_grid) * step
    cumpdf = np.zeros(n_grid)
    first = True
    for j in range(n_hist):
        c = close[j]; h = high[j]; l = low[j]; s = shares[j]; d = turnover[j]
        if np.isnan(c) or np.isnan(h) or np.isnan(l) or np.isnan(s) or np.isnan(d):
            continue  # 停牌/缺数：分布冻结
        cur = np.zeros(n_grid)
        _triang_into(grid, l, h, c, s, cur)
        if first:
            cumpdf = cur * d
            first = False
        else:
            cumpdf = cumpdf * (1.0 - d) + cur * d
        if capture_flag[date_pos[j]] == 1:
            total = float(cumpdf.sum())
            if total <= 0:
                continue
            pos = int(np.searchsorted(grid, c, side="right"))
            winner = float(cumpdf[:pos].sum()) / total if pos > 0 else 0.0
            out[capture_slot[date_pos[j]]] = min(max(winner, 0.0), 1.0)
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
    wr = _stock_winner_ratio_impl(close, high, low, shares, turnover, date_pos, capture_flag, capture_slot, step)
    return code, wr


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="CYQ 每日获利盘比例（qlib bins 数据源）")
    ap.add_argument("--test", required=True, help="测试窗 START:END")
    ap.add_argument("--window", type=int, default=1000, help="衰减回看交易日数（默认 1000，对齐 Rust）")
    ap.add_argument("--step", type=float, default=0.01)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default=str(_DEFAULT_OUT))
    args = ap.parse_args(argv)

    from datetime import datetime

    s, e = args.test.split(":", 1)
    d_s = datetime.strptime(s, "%Y-%m-%d")
    d_e = datetime.strptime(e, "%Y-%m-%d")

    import qlib
    from qlib.config import REG_CN
    from qlib.data import D

    qlib.init(provider_uri=str(_QLIB_DIR), region=REG_CN, kernels=8)
    cal = D.calendar()
    dates = pd.DatetimeIndex(cal)
    pos = {d_: i for i, d_ in enumerate(dates)}

    i_end = pos.get(d_e)
    i_start = pos.get(d_s)
    # 端点落在节假日时就近吸附到交易日（start 向后、end 向前）
    if i_start is None:
        i_start = int(dates.searchsorted(pd.Timestamp(d_s)))
    if i_end is None:
        i_end = int(dates.searchsorted(pd.Timestamp(d_e))) - 1
    if i_end is None or i_start is None or i_start > i_end or i_end >= len(dates):
        print(f"FAIL: 测试窗端点无法吸附到交易日 {s}/{e}", file=sys.stderr)
        return 2
    i_hist_start = max(0, i_start - args.window)
    hist_start = dates[i_hist_start]

    codes = sorted(D.list_instruments(D.instruments(market="all"), start_time=hist_start, end_time=d_e, as_list=True))
    print(f"universe={len(codes)}  历史 {hist_start.date()}~{d_e.date()}（{i_end - i_hist_start + 1} 交易日）", flush=True)

    fields = ["$adjclose", "$close", "$high", "$low", "$amount", "$netcsfree"]
    fdf = D.features(codes, fields, start_time=hist_start, end_time=d_e)
    fdf.columns = ["adjclose", "close", "high", "low", "amount", "netcsfree"]
    fdf = fdf.reset_index()

    # 真实成交股数与换手率（单位自洽，见模块 docstring）
    fdf["shares"] = np.where((fdf.adjclose > 0) & (fdf.amount > 0), fdf.amount / fdf.adjclose, np.nan)
    fdf["turnover"] = np.where(fdf.netcsfree > 0, fdf.shares / fdf.netcsfree, np.nan)
    fdf["turnover"] = fdf.turnover.clip(0, 0.999)
    # high/low 后复权 → 原始价空间（factor = adjclose/close；close<=0 或 adjclose<=0 的行置 NaN）
    ok = (fdf.close > 0) & (fdf.adjclose > 0)
    factor = np.where(ok, fdf.adjclose / fdf.close, np.nan)
    fdf["raw_high"] = np.where(ok, fdf.high * factor, np.nan)
    fdf["raw_low"] = np.where(ok, fdf.low * factor, np.nan)
    fdf["date_pos"] = fdf.datetime.map(pos) - i_hist_start  # 相对历史窗起点的位置（0..hist_len-1）
    print(
        f"特征行: {len(fdf)}  adjclose 缺失率 {fdf.adjclose.isna().mean():.2%}  "
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
                g["adjclose"].to_numpy(np.float64),
                g["raw_high"].to_numpy(np.float64),
                g["raw_low"].to_numpy(np.float64),
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
    if args.workers <= 1:
        results = map(_work_one, tasks)
        for code, wr in results:
            if np.all(np.isnan(wr)):
                continue
            n_ok += 1
            rows.append(
                pd.DataFrame(
                    {
                        "stock_code": code,
                        "date": dates[i_start : i_end + 1][: len(wr)],
                        "winner_ratio": wr,
                    }
                ).dropna()
            )
            if n_ok % 500 == 0:
                print(f"  done {n_ok}  elapsed={time.perf_counter() - t0:.0f}s", flush=True)
    else:
        with multiprocessing.get_context("spawn").Pool(args.workers) as pool:
            for code, wr in pool.imap_unordered(_work_one, tasks, chunksize=8):
                if np.all(np.isnan(wr)):
                    continue
                n_ok += 1
                rows.append(
                    pd.DataFrame(
                        {
                            "stock_code": code,
                            "date": dates[i_start : i_end + 1][: len(wr)],
                            "winner_ratio": wr,
                        }
                    ).dropna()
                )
                if n_ok % 500 == 0:
                    print(f"  done {n_ok}  elapsed={time.perf_counter() - t0:.0f}s", flush=True)

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
