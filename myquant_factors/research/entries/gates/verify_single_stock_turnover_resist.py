from typing import Any, cast


from myquant_factors._runtime import research_root, resolve_source_parquet
# -*- coding: utf-8 -*-
"""
单只股票换手阻力分步验算脚本。

按 canonical（换手率衰减）算法，逐行拆解指定股票在指定截面的
中间量与最终结果，并与全市场 CSV 输出交叉验证。

用法：
    python scripts/gates/verify_single_stock_turnover_resist.py --code 003816.SZ --date 20260604
"""

import argparse
import sys
from pathlib import Path

REPO = str(research_root())
sys.path.append(REPO)  # append (not insert(0)) keeps stdlib precedence; gate-clean

import duckdb
import numpy as np
import pandas as pd
from numba import jit

from myquant_factors._runtime import StockDataReader
from myquant_factors import cyq
from myquant_factors.distribution_of_chips import make_price_grid
from myquant_factors._runtime import resolve_source_parquet

# ---------------------------------------------------------------------------
# 复用 full_market_canonical_resist.py 中的 numba 核心函数
# ---------------------------------------------------------------------------


@jit(nopython=True)
def _batch_triang_curpdf(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    vol: np.ndarray,
    x: np.ndarray,
) -> np.ndarray:
    """Compute triang PDF for all days in a single numba call."""
    n_days = len(close)
    n_bins = len(x)
    pdfs = np.zeros((n_days, n_bins), dtype=np.float64)
    step = x[1] - x[0] if n_bins > 1 else 0.01

    for d in range(n_days):
        h, l, c_val, v = high[d], low[d], close[d], vol[d]

        if h == l:  # 涨跌停日
            idx = int(round((c_val - x[0]) / step))
            if 0 <= idx < n_bins:
                pdfs[d, idx] = v
            continue

        scale = h - l
        c_param = (c_val - l) / scale
        loc = l
        peak = loc + scale * c_param
        upper = loc + scale
        sq_scale = scale * scale

        if c_param <= 0.0:
            for i in range(n_bins):
                xi = x[i]
                if loc <= xi <= upper:
                    pdfs[d, i] = 2.0 * (upper - xi) / sq_scale
        elif c_param >= 1.0:
            for i in range(n_bins):
                xi = x[i]
                if loc <= xi <= upper:
                    pdfs[d, i] = 2.0 * (xi - loc) / sq_scale
        else:
            for i in range(n_bins):
                xi = x[i]
                if loc <= xi <= peak:
                    pdfs[d, i] = 2.0 * (xi - loc) / (c_param * sq_scale)
                elif peak < xi <= upper:
                    pdfs[d, i] = 2.0 * (upper - xi) / (sq_scale * (1.0 - c_param))

        total = 0.0
        for i in range(n_bins):
            total += pdfs[d, i]
        if total > 0.0:
            for i in range(n_bins):
                pdfs[d, i] = pdfs[d, i] / total * v

    return pdfs


@jit(nopython=True)
def _batch_cumpdf_4way(
    curpdf_t: np.ndarray,
    curpdf_prev: np.ndarray,
    t_circ_t: np.ndarray,
    t_circ_p: np.ndarray,
    t_free_t: np.ndarray,
    t_free_p: np.ndarray,
) -> tuple:
    """Compute 4 cumpdf results in a single numba call."""
    n_days = len(t_circ_t)
    n_bins = curpdf_t.shape[1]

    decay = t_circ_t.copy()
    diff = 1.0 - decay
    mul = (curpdf_t.T * decay).T
    c1 = np.empty(n_bins, dtype=np.float64)
    for i in range(n_days):
        c1 = c1 * diff[i] + mul[i] if i else curpdf_t[i] * decay[i]

    decay = t_circ_p.copy()
    diff = 1.0 - decay
    mul = (curpdf_prev.T * decay).T
    c2 = np.empty(n_bins, dtype=np.float64)
    for i in range(n_days):
        c2 = c2 * diff[i] + mul[i] if i else curpdf_prev[i] * decay[i]

    decay = t_free_t.copy()
    diff = 1.0 - decay
    mul = (curpdf_t.T * decay).T
    c3 = np.empty(n_bins, dtype=np.float64)
    for i in range(n_days):
        c3 = c3 * diff[i] + mul[i] if i else curpdf_t[i] * decay[i]

    decay = t_free_p.copy()
    diff = 1.0 - decay
    mul = (curpdf_prev.T * decay).T
    c4 = np.empty(n_bins, dtype=np.float64)
    for i in range(n_days):
        c4 = c4 * diff[i] + mul[i] if i else curpdf_prev[i] * decay[i]

    return c1, c2, c3, c4


# ---------------------------------------------------------------------------
# 股本加载（复用 full_market_canonical_resist.py 的 DuckDB 查询逻辑）
# ---------------------------------------------------------------------------


def load_capital_maps(code: str, target: pd.Timestamp) -> dict:
    """从 free_float_shares.parquet + float_shares.parquet 加载单只股票股本。"""
    target_prev = target - pd.Timedelta(days=1)
    cap_path = str(resolve_source_parquet("free_float_shares.parquet"))

    con = duckdb.connect()
    cap_df = con.execute(
        f"""
        SELECT * FROM (
          SELECT stock_code, 'T' as which, freeFloatCapital, circulating_capital,
            ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY m_timetag DESC) AS rn
          FROM read_parquet('{cap_path}')
          WHERE m_timetag <= '{target.strftime('%Y-%m-%d')}'
        ) WHERE rn = 1
        UNION ALL
        SELECT * FROM (
          SELECT stock_code, 'T_prev' as which, freeFloatCapital, circulating_capital,
            ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY m_timetag DESC) AS rn
          FROM read_parquet('{cap_path}')
          WHERE m_timetag <= '{target_prev.strftime('%Y-%m-%d')}'
        ) WHERE rn = 1
        """
    ).df()
    con.close()

    cap_t = cap_tp = free_t = free_tp = 0
    for _, row in cap_df.iterrows():
        if row["stock_code"] == code:
            if row["which"] == "T":
                cap_t = row["circulating_capital"] or 0
                free_t = row["freeFloatCapital"] or 0
            else:
                cap_tp = row["circulating_capital"] or 0
                free_tp = row["freeFloatCapital"] or 0

    if cap_t <= 0 or cap_tp <= 0:
        fs_df = pd.read_parquet(resolve_source_parquet("float_shares.parquet"))
        fs_map = dict(zip(fs_df["stock_code"], fs_df["FloatVolume"]))
        fallback = fs_map.get(code, 0)
        cap_t = cap_t or fallback
        cap_tp = cap_tp or fallback

    return {
        "circ_t": cap_t,
        "circ_prev": cap_tp,
        "free_t": free_t,
        "free_prev": free_tp,
    }


# ---------------------------------------------------------------------------
# 分步验算主逻辑
# ---------------------------------------------------------------------------


def verify(code: str, date_str: str, window: int = 1000, step: float = 0.01) -> dict:
    target = pd.Timestamp(date_str)

    print("=" * 50)
    print("Step 0: 获取股本数据")
    print("=" * 50)
    caps = load_capital_maps(code, cast(Any, target))
    print(f"circulating_capital T    = {caps['circ_t']:,.0f}")
    print(f"circulating_capital T-1  = {caps['circ_prev']:,.0f}")
    print(f"freeFloatCapital T       = {caps['free_t']:,.0f}")
    print(f"freeFloatCapital T-1     = {caps['free_prev']:,.0f}")
    print()

    print("=" * 50)
    print("Step 1: 读取日线数据")
    print("=" * 50)
    reader = StockDataReader()
    df = reader.read_stock(code, period="1d", adjust_type="front")
    assert df is not None
    df = df.sort_index()
    print(f"原始数据条数: {len(df)}")
    print(f"数据起止: {df.index.min().date()} ~ {df.index.max().date()}")
    print()

    print("=" * 50)
    print("Step 2: 确定目标日期窗口")
    print("=" * 50)
    df_t = df[df.index.normalize() <= target]
    unique_dates = df_t.index.normalize().unique()
    print(f"截至 {date_str} 的不重复日期数: {len(unique_dates)}")
    extended_dates = unique_dates[-(window + 1) :]
    print(
        f"取最近 {window + 1} 个不重复日期: "
        f"{extended_dates[0].date()} ~ {extended_dates[-1].date()}"
    )
    mask_ext = df_t.index.normalize().isin(extended_dates)
    df_w = df_t.loc[mask_ext]
    print(f"窗口内实际数据条数: {len(df_w)}")
    print()

    if len(df_w) < window + 1:
        print(f"[ERROR] 数据不足 {window + 1} 条，无法验算")
        return {}

    print("=" * 50)
    print("Step 3: 构造计算数组")
    print("=" * 50)
    arr_raw = (
        df_w.rename(columns={"volume": "vol"})
        [["close", "high", "low", "vol"]]
        .values.astype(np.float64)
    )
    print(f"arr_raw shape: {arr_raw.shape} (columns: close, high, low, vol)")
    print(
        f"第一行(最早): close={arr_raw[0, 0]:.4f}, high={arr_raw[0, 1]:.4f}, "
        f"low={arr_raw[0, 2]:.4f}, vol={arr_raw[0, 3]:.0f}"
    )
    print(
        f"最后一行(T日): close={arr_raw[-1, 0]:.4f}, high={arr_raw[-1, 1]:.4f}, "
        f"low={arr_raw[-1, 2]:.4f}, vol={arr_raw[-1, 3]:.0f}"
    )
    print(
        f"倒数第二行(T-1): close={arr_raw[-2, 0]:.4f}, high={arr_raw[-2, 1]:.4f}, "
        f"low={arr_raw[-2, 2]:.4f}, vol={arr_raw[-2, 3]:.0f}"
    )
    print()

    print("=" * 50)
    print("Step 4: 价格网格 (make_price_grid)")
    print("=" * 50)
    max_p = float(np.nanmax(arr_raw[:, 1]))
    min_p = float(np.nanmin(arr_raw[:, 2]))
    xs = make_price_grid(min_p, max_p, step)
    print(f"最小价: {min_p:.4f}, 最大价: {max_p:.4f}, 步长: {step}")
    print(f"价格网格长度: {len(xs)}")
    print(f"网格范围: [{xs.min():.4f}, {xs.max():.4f}]")
    print()

    print("=" * 50)
    print("Step 5: 计算逐日三角分布 curpdf")
    print("=" * 50)
    curpdfs = _batch_triang_curpdf(
        arr_raw[:, 0], arr_raw[:, 1], arr_raw[:, 2], arr_raw[:, 3], xs
    )
    print(f"curpdfs shape: {curpdfs.shape} (days x bins)")
    print(f"curpdfs[0] sum    = {curpdfs[0].sum():.0f}  (应≈vol={arr_raw[0, 3]:.0f})")
    print(f"curpdfs[-1] sum   = {curpdfs[-1].sum():.0f}  (应≈vol={arr_raw[-1, 3]:.0f})")
    print(f"curpdfs[-2] sum   = {curpdfs[-2].sum():.0f}  (应≈vol={arr_raw[-2, 3]:.0f})")
    print()

    print("=" * 50)
    print("Step 6: 分割 T 窗口与 T-1 窗口的 curpdf")
    print("=" * 50)
    curpdf_t = curpdfs[1:, :]
    curpdf_prev = curpdfs[:-1, :]
    print(f"curpdf_t     shape: {curpdf_t.shape}")
    print(f"curpdf_prev  shape: {curpdf_prev.shape}")
    print()

    print("=" * 50)
    print("Step 7: 计算逐日换手率（4 组）")
    print("=" * 50)
    vol_arr = arr_raw[:, 3]
    turnover_circ_t_arr = vol_arr * 100.0 / caps["circ_t"]
    turnover_circ_prev_arr = vol_arr * 100.0 / caps["circ_prev"]
    turnover_free_t_arr = vol_arr * 100.0 / caps["free_t"]
    turnover_free_prev_arr = vol_arr * 100.0 / caps["free_prev"]
    print(f"T 日流通换手率最后1日 = {turnover_circ_t_arr[-1]:.6f}")
    print(f"T 日自由换手率最后1日 = {turnover_free_t_arr[-1]:.6f}")
    print()

    print("=" * 50)
    print("Step 8: 衰减累积 cumpdf (_batch_cumpdf_4way)")
    print("=" * 50)
    cumpdf_circ_t, cumpdf_circ_prev, cumpdf_free_t, cumpdf_free_prev = (
        _batch_cumpdf_4way(
            curpdf_t,
            curpdf_prev,
            turnover_circ_t_arr[1:],
            turnover_circ_prev_arr[:-1],
            turnover_free_t_arr[1:],
            turnover_free_prev_arr[:-1],
        )
    )
    print(f"cumpdf_circ_t    sum = {cumpdf_circ_t.sum():.6f}")
    print(f"cumpdf_circ_prev sum = {cumpdf_circ_prev.sum():.6f}")
    print(f"cumpdf_free_t    sum = {cumpdf_free_t.sum():.6f}")
    print(f"cumpdf_free_prev sum = {cumpdf_free_prev.sum():.6f}")
    print()

    print("=" * 50)
    print("Step 9: 提取 cyqk (ChipFactor.get_cyqk_c)")
    print("=" * 50)
    close_t = float(arr_raw[-1, 0])
    close_prev = float(arr_raw[-2, 0])
    cyqk_circ_t = cyq.ChipFactor(
        close_t, pd.Series(cumpdf_circ_t, index=xs, name="cumpdf")
    ).get_cyqk_c()
    cyqk_circ_prev = cyq.ChipFactor(
        close_prev, pd.Series(cumpdf_circ_prev, index=xs, name="cumpdf")
    ).get_cyqk_c()
    cyqk_free_t = cyq.ChipFactor(
        close_t, pd.Series(cumpdf_free_t, index=xs, name="cumpdf")
    ).get_cyqk_c()
    cyqk_free_prev = cyq.ChipFactor(
        close_prev, pd.Series(cumpdf_free_prev, index=xs, name="cumpdf")
    ).get_cyqk_c()
    print(f"T 日 close    = {close_t:.4f}")
    print(f"T-1日 close   = {close_prev:.4f}")
    print(f"cyqk_circ_t   = {cyqk_circ_t:.4f}")
    print(f"cyqk_circ_prev= {cyqk_circ_prev:.4f}")
    print(f"cyqk_free_t   = {cyqk_free_t:.4f}")
    print(f"cyqk_free_prev= {cyqk_free_prev:.4f}")
    print()

    print("=" * 50)
    print("Step 10: 获利筹码变化 profit_chip_diff")
    print("=" * 50)
    profit_chip_diff_circ = cyqk_circ_t - cyqk_circ_prev
    profit_chip_diff_free = cyqk_free_t - cyqk_free_prev
    print(f"circ  = {cyqk_circ_t:.4f} - {cyqk_circ_prev:.4f} = {profit_chip_diff_circ:.6f}")
    print(f"free  = {cyqk_free_t:.4f} - {cyqk_free_prev:.4f} = {profit_chip_diff_free:.6f}")
    print()

    print("=" * 50)
    print("Step 11: 换手率（仅 T 日）")
    print("=" * 50)
    vol_t = float(arr_raw[-1, 3])
    turnover_circ_t = vol_t * 100.0 / caps["circ_t"] if caps["circ_t"] > 0 else 0.0
    turnover_free_t = vol_t * 100.0 / caps["free_t"] if caps["free_t"] > 0 else 0.0
    print(f"vol_t = {vol_t:,.0f}")
    print(
        f"turnover_circ_t = {vol_t:,.0f} * 100 / {caps['circ_t']:,.0f} = {turnover_circ_t:.6f}"
    )
    print(
        f"turnover_free_t = {vol_t:,.0f} * 100 / {caps['free_t']:,.0f} = {turnover_free_t:.6f}"
    )
    print()

    print("=" * 50)
    print("Step 12: 换手阻力 = profit_chip_diff / turnover_T")
    print("=" * 50)
    turnover_resistance_circ = (
        profit_chip_diff_circ / turnover_circ_t if turnover_circ_t > 0 else 0.0
    )
    turnover_resistance_free = (
        profit_chip_diff_free / turnover_free_t if turnover_free_t > 0 else 0.0
    )
    print(
        f"circ  = {profit_chip_diff_circ:.6f} / {turnover_circ_t:.6f} = {turnover_resistance_circ:.4f}"
    )
    print(
        f"free  = {profit_chip_diff_free:.6f} / {turnover_free_t:.6f} = {turnover_resistance_free:.4f}"
    )
    print()

    print("=" * 50)
    print("Step 13: 布林带 (20日, 2σ, ddof=1)")
    print("=" * 50)
    close_series = pd.Series(arr_raw[:, 0])
    if len(close_series) >= 20:
        bb_mid = float(close_series.rolling(20).mean().iloc[-1])
        bb_std = float(close_series.rolling(20).std().iloc[-1])
    else:
        bb_mid = float(close_series.mean())
        bb_std = float(close_series.std())
    bb_upper = bb_mid + 2.0 * bb_std
    bb_lower = bb_mid - 2.0 * bb_std
    bb_pos = (
        (close_t - bb_lower) / (bb_upper - bb_lower)
        if bb_upper > bb_lower
        else 0.5
    )
    bb_w = (bb_upper - bb_lower) / bb_mid if bb_mid > 0 else 0.0
    print(f"bb_mid     = {bb_mid:.2f}")
    print(f"bb_std     = {bb_std:.4f}")
    print(f"bb_upper   = {bb_upper:.2f}")
    print(f"bb_lower   = {bb_lower:.2f}")
    print(f"bb_position= {bb_pos:.4f}")
    print(f"bb_width   = {bb_w:.4f}")
    print()

    result = {
        "code": code,
        "date": date_str,
        "close": round(close_t, 2),
        "cyqk_T": round(cyqk_circ_t, 4),
        "cyqk_T_1": round(cyqk_circ_prev, 4),
        "profit_chip_diff": round(profit_chip_diff_circ, 6),
        "turnover": round(turnover_circ_t, 6),
        "turnover_resistance": round(turnover_resistance_circ, 4),
        "turnover_free": round(turnover_free_t, 6),
        "turnover_resistance_free": round(turnover_resistance_free, 4),
        "circulating_capital": caps["circ_t"],
        "freeFloatCapital": caps["free_t"],
        "bb_upper": round(bb_upper, 2),
        "bb_middle": round(bb_mid, 2),
        "bb_lower": round(bb_lower, 2),
        "bb_position": round(bb_pos, 4),
        "bb_width": round(bb_w, 4),
    }

    # 与 CSV 交叉验证
    print("=" * 50)
    print("与 CSV 输出对比")
    print("=" * 50)
    csv_paths = [
        f"backtest_output/canonical_resist_batch_{date_str}.csv",
        f"backtest_output/canonical_resist_rust_{date_str}.csv",
    ]
    found = False
    for csv_path in csv_paths:
        p = Path(csv_path)
        if not p.exists():
            continue
        try:
            csv = pd.read_csv(csv_path, encoding="utf-8-sig")
            row = csv[csv["stock_code"] == code]
            if len(row):
                found = True
                r = row.iloc[0]
                match = lambda k: "✅" if abs(result[k] - r[k]) < 1e-9 else "❌"
                print(f"对比文件: {csv_path}")
                print(f"  close                 {match('close')} 验算 {result['close']:.2f}  vs CSV {r['close']:.2f}")
                print(f"  cyqk_T                {match('cyqk_T')} 验算 {result['cyqk_T']:.4f}  vs CSV {r['cyqk_T']:.4f}")
                print(f"  cyqk_T_1              {match('cyqk_T_1')} 验算 {result['cyqk_T_1']:.4f}  vs CSV {r['cyqk_T_1']:.4f}")
                print(f"  profit_chip_diff      {match('profit_chip_diff')} 验算 {result['profit_chip_diff']:.6f}  vs CSV {r['profit_chip_diff']:.6f}")
                print(f"  turnover              {match('turnover')} 验算 {result['turnover']:.6f}  vs CSV {r['turnover']:.6f}")
                print(f"  turnover_resistance   {match('turnover_resistance')} 验算 {result['turnover_resistance']:.4f}  vs CSV {r['turnover_resistance']:.4f}")
                print(f"  turnover_free         {match('turnover_free')} 验算 {result['turnover_free']:.6f}  vs CSV {r['turnover_free']:.6f}")
                print(f"  turnover_resistance_free {match('turnover_resistance_free')} 验算 {result['turnover_resistance_free']:.4f}  vs CSV {r['turnover_resistance_free']:.4f}")
                print(f"  bb_upper              {match('bb_upper')} 验算 {result['bb_upper']:.2f}  vs CSV {r['bb_upper']:.2f}")
                print(f"  bb_middle             {match('bb_middle')} 验算 {result['bb_middle']:.2f}  vs CSV {r['bb_middle']:.2f}")
                print(f"  bb_lower              {match('bb_lower')} 验算 {result['bb_lower']:.2f}  vs CSV {r['bb_lower']:.2f}")
                print(f"  bb_position           {match('bb_position')} 验算 {result['bb_position']:.4f}  vs CSV {r['bb_position']:.4f}")
                print(f"  bb_width              {match('bb_width')} 验算 {result['bb_width']:.4f}  vs CSV {r['bb_width']:.4f}")
        except Exception as e:
            print(f"  读取 {csv_path} 失败: {e}")

    if not found:
        print("  未找到可对比的 CSV 文件")

    return result


def main():
    parser = argparse.ArgumentParser(description="单只股票换手阻力分步验算")
    parser.add_argument("--code", required=True, help="股票代码，如 003816.SZ")
    parser.add_argument("--date", required=True, help="截面日期 YYYYMMDD")
    parser.add_argument("--window", type=int, default=1000, help="筹码衰减窗口，默认 1000")
    parser.add_argument("--step", type=float, default=0.01, help="价格步长，默认 0.01")
    args = parser.parse_args()

    verify(args.code, args.date, args.window, args.step)


if __name__ == "__main__":
    main()
