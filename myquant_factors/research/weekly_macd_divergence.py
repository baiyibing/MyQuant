#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""周线 MACD 底背离批量扫描 runner（数据装载 + 标的枚举 + CLI）。

因子算法本体在 ``oskh_factors/weekly_macd_divergence.py``（纯 pandas，零
oskh_data 依赖，RFC-003 包规约）；本脚本只做：前复权日线装载
（``StockDataReader.read_stock(adjust_type='front')``）→ 调因子入口 → CSV/摘要。
本脚本在 ``scripts/`` 下（非热路径），不受
``oskh_data.reader._enforce_adjust_type_policy`` 的 ``none`` 限制。

方案 SSOT：``docs/engineering/plan-weekly-macd-divergence-2026-07-20.md`` v3。

CLI::

    # 单股/多股
    python scripts/analysis/weekly_macd_divergence.py --symbols 000001.SZ,600519.SH
    # 全市场（枚举 stock_data 前复权分区，默认排除 ETF）
    python scripts/analysis/weekly_macd_divergence.py --all --limit 200   # 冒烟
    python scripts/analysis/weekly_macd_divergence.py --all               # 全量
"""

from __future__ import annotations

import argparse  # noqa: E402
import logging  # noqa: E402
import time  # noqa: E402
from dataclasses import asdict, fields  # noqa: E402
from datetime import date  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Dict, List, Optional, Sequence, Tuple  # noqa: E402

import pandas as pd  # noqa: E402

from myquant_infra.reference_data.symbols import is_etf_code  # noqa: E402
from myquant_factors._runtime import StockDataReader  # noqa: E402
from myquant_infra.reference_data.symbols import is_canonical_symbol, to_canonical_symbol  # noqa: E402

from myquant_factors.weekly_macd_divergence import (  # noqa: E402
    DEFAULT_COUNT_WINDOW_WEEKS,
    DEFAULT_LOOKBACK_WEEKS,
    DEFAULT_MIN_GAP_WEEKS,
    DEFAULT_MIN_HISTORY_WEEKS,
    STRENGTH_MEDIUM,
    STRENGTH_STRONG,
    STRENGTH_WEAK,
    DivergenceSignal,
    detect_weekly_macd_divergence,
)

logger = logging.getLogger("weekly_macd_divergence")

_SIGNAL_COLUMNS = [f.name for f in fields(DivergenceSignal)]


# ---------------------------------------------------------------------------
# 数据装载（reader → 因子入口）
# ---------------------------------------------------------------------------


def _load_daily_bars(
    symbol: str,
    start_time: Optional[str],
    end_time: Optional[str],
    reader: StockDataReader,
) -> Optional[pd.DataFrame]:
    """读前复权日线。None + ``_last_query_error`` → loud fail（v3 🟡）。"""
    # reader._last_query_error 成功时不清零：先手动复位，使 None 返回能区分
    # 「真无数据」与「查询失败」。
    if hasattr(reader, "_last_query_error"):
        reader._last_query_error = None
    df = reader.read_stock(
        symbol,
        start_time=start_time,
        end_time=end_time,
        period="1d",
        adjust_type="front",
    )
    if df is None:
        err = getattr(reader, "_last_query_error", None)
        if err:
            raise RuntimeError(f"read_stock({symbol}) 查询失败（loud fail）: {err}")
    return df


def detect_divergence(
    symbol: str,
    reader: StockDataReader,
    *,
    lookback: int = DEFAULT_LOOKBACK_WEEKS,
    min_gap: int = DEFAULT_MIN_GAP_WEEKS,
    count_window: int = DEFAULT_COUNT_WINDOW_WEEKS,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    min_history_weeks: int = DEFAULT_MIN_HISTORY_WEEKS,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    as_of_date: str = "",
) -> Optional[List[DivergenceSignal]]:
    """单股检测：装载前复权日线 → ``oskh_factors.detect_weekly_macd_divergence``。

    返回 ``list[DivergenceSignal]``（可为空 = 无信号）；``None`` = skipped
    （无数据或周线数 < ``min_history_weeks``）。
    """
    daily = _load_daily_bars(symbol, start_time, end_time, reader)
    if daily is None or len(daily) == 0:
        return None
    return detect_weekly_macd_divergence(
        daily,
        symbol,
        lookback=lookback,
        min_gap=min_gap,
        count_window=count_window,
        fast=fast,
        slow=slow,
        signal=signal,
        min_history_weeks=min_history_weeks,
        as_of_date=as_of_date,
    )


def _enumerate_symbols(*, include_etf: bool = False) -> List[str]:
    """枚举 ``period=1d/dividend_type=front/`` 分区目录 → canonical symbol 列表（r2 🔴-1）。"""
    from myquant_factors._runtime import resolve_period_root

    part = resolve_period_root("1d") / "dividend_type=front"
    if not part.is_dir():
        raise FileNotFoundError(f"前复权分区目录不存在: {part}")
    symbols: List[str] = []
    for child in sorted(part.iterdir()):
        if not child.is_dir() or not child.name.startswith("symbol="):
            continue
        sym = to_canonical_symbol(child.name)
        if not is_canonical_symbol(sym):
            continue
        if not include_etf and is_etf_code(sym):
            continue
        symbols.append(sym)
    return symbols


# ---------------------------------------------------------------------------
# CLI / 批量 runner（P1）
# ---------------------------------------------------------------------------


def _parse_macd_params(text: str) -> Tuple[int, int, int]:
    parts = [int(x) for x in str(text).split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("--macd-params 需 fast,slow,signal 三参，如 12,26,9")
    return parts[0], parts[1], parts[2]


def _signals_to_frame(signals: Sequence[DivergenceSignal]) -> pd.DataFrame:
    rows = [asdict(s) for s in signals]
    df = pd.DataFrame(rows) if rows else pd.DataFrame({c: [] for c in _SIGNAL_COLUMNS})
    if not df.empty:
        # is_uptrend None → "unknown"（CSV 标注区别，v3 §2.5）
        df["is_uptrend"] = df["is_uptrend"].map(lambda v: "unknown" if v is None else str(bool(v)))
    return df


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="周线 MACD 底背离检测（前复权日线 → 周线 → MACD 三级判定）")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--symbols", help="逗号分隔 canonical 代码，如 000001.SZ,600519.SH")
    src.add_argument("--all", action="store_true", help="枚举 stock_data 前复权分区全市场（默认排除 ETF）")
    ap.add_argument("--include-etf", action="store_true", help="全市场扫描时包含 ETF")
    ap.add_argument("--out", default=None, help="输出 CSV（默认 data/divergence_signals_<YYYYMMDD>.csv）")
    ap.add_argument("--min-history", type=int, default=DEFAULT_MIN_HISTORY_WEEKS, help="最少周线数（默认 260）")
    ap.add_argument("--macd-params", type=_parse_macd_params, default=(12, 26, 9), help="如 12,26,9")
    ap.add_argument("--lookback", type=int, default=DEFAULT_LOOKBACK_WEEKS, help="条件 A/B 回望窗口（默认 60 周）")
    ap.add_argument("--min-gap", type=int, default=DEFAULT_MIN_GAP_WEEKS, help="候选合并间隔（默认 8 周）")
    ap.add_argument("--count-window", type=int, default=DEFAULT_COUNT_WINDOW_WEEKS, help="分类计数窗口（默认 52 周）")
    ap.add_argument("--start", dest="start_time", default=None, help="日线起始（如 20150101，默认全历史）")
    ap.add_argument("--end", dest="end_time", default=None, help="日线截止（默认最新）")
    ap.add_argument("--limit", type=int, default=None, help="仅扫前 N 只（冒烟用）")
    ap.add_argument("--data-root", default=None, help="覆盖数据根（默认 OSKH_DATA_ROOT / 项目根）")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    fast, slow, signal = args.macd_params
    as_of = date.today().isoformat()
    t0 = time.monotonic()

    with StockDataReader(mode="duckdb_persistent", project_root=args.data_root) as reader:
        if args.symbols:
            symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
        else:
            symbols = _enumerate_symbols(include_etf=args.include_etf)
        if args.limit:
            symbols = symbols[: args.limit]
        logger.info("标的数 %d（min_history=%d 周, lookback=%d, macd=%d/%d/%d）",
                    len(symbols), args.min_history, args.lookback, fast, slow, signal)

        all_signals: List[DivergenceSignal] = []
        skipped = 0
        errors = 0
        for i, sym in enumerate(symbols, 1):
            try:
                sigs = detect_divergence(
                    sym,
                    reader,
                    lookback=args.lookback,
                    min_gap=args.min_gap,
                    count_window=args.count_window,
                    fast=fast,
                    slow=slow,
                    signal=signal,
                    min_history_weeks=args.min_history,
                    start_time=args.start_time,
                    end_time=args.end_time,
                    as_of_date=as_of,
                )
            except Exception as exc:  # 单股失败不阻断全量
                errors += 1
                logger.warning("%s 检测异常: %s", sym, exc)
                continue
            if sigs is None:
                skipped += 1
                continue
            all_signals.extend(sigs)
            if i % 500 == 0:
                logger.info("进度 %d/%d，累计信号 %d", i, len(symbols), len(all_signals))

    out_path = Path(args.out) if args.out else Path("data") / f"divergence_signals_{date.today():%Y%m%d}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df = _signals_to_frame(all_signals)
    df.to_csv(out_path, index=False, encoding="utf-8")

    counts: Dict[str, int] = {STRENGTH_STRONG: 0, STRENGTH_MEDIUM: 0, STRENGTH_WEAK: 0}
    for s in all_signals:
        counts[s.signal_strength] = counts.get(s.signal_strength, 0) + 1
    elapsed = time.monotonic() - t0
    print(
        f"完成：标的 {len(symbols)}，信号 {len(all_signals)}"
        f"（STRONG {counts[STRENGTH_STRONG]} / MEDIUM {counts[STRENGTH_MEDIUM]} / WEAK {counts[STRENGTH_WEAK]}），"
        f"skipped {skipped}，errors {errors}，耗时 {elapsed:.1f}s"
    )
    print(f"CSV: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
