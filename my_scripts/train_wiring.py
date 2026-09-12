"""Qlib train R3 wiring helpers (filter_pipe + verify).

Kept free of report/plotly/LGB imports so unit tests can import without
pulling the full custom_train_backtest entrypoint.
"""

from __future__ import annotations

import argparse
import os

from qlib.data import D
from qlib.data.filter import NameDFilter

from custom_filter import UnifiedLimitUpFilter


def build_exclude_name_filter(exclude_stocks):
    """NameDFilter regex that keeps instruments not in exclude_stocks."""
    return NameDFilter(name_rule_re="^(?!(" + "|".join(exclude_stocks) + ")).*$")


def build_limit_up_filter():
    """Production limit-up filter: $zhangting field mode only (keep=False)."""
    return UnifiedLimitUpFilter(use_field="$zhangting", keep=False)


def build_production_filter_pipe(exclude_stocks):
    """Exclude blacklist then $zhangting limit-up. Order is part of the contract."""
    return [build_exclude_name_filter(exclude_stocks), build_limit_up_filter()]


def build_filtered_instruments(
    start_time,
    end_time,
    exclude_stocks,
    market="all",
    instruments_fn=None,
):
    """Production instruments: D.instruments(..., filter_pipe=[exclude, limit_up]).

    Returns the instruments config object (dict with market + filter_pipe).
    Does not hang filter_pipe on the handler dict — that key is not the live path.
    instruments_fn is injectable for unit tests (defaults to D.instruments).
    """
    filter_pipe = build_production_filter_pipe(exclude_stocks)
    fn = D.instruments if instruments_fn is None else instruments_fn
    return fn(
        market=market,
        start_time=start_time,
        end_time=end_time,
        filter_pipe=filter_pipe,
    )


def verify_limit_up_filter(filtered_handler, unfiltered_handler, segments):
    """验证 UnifiedLimitUpFilter 是否在 train/valid/test 三段生效。"""
    filtered_df = filtered_handler.fetch(col_set="feature")
    unfiltered_df = unfiltered_handler.fetch(col_set="feature")

    if "LIMIT_STATUS" not in filtered_df.columns or "LIMIT_STATUS" not in unfiltered_df.columns:
        raise ValueError("验证失败：缺少 LIMIT_STATUS 列，请确认 include_lz=True 且 $zhangting 字段可用。")

    print("\n=== Verify UnifiedLimitUpFilter (train/valid/test) ===")
    for seg_name, (seg_start, seg_end) in segments.items():
        base_seg = unfiltered_df.loc[(slice(seg_start, seg_end), slice(None)), :]
        filtered_seg = filtered_df.loc[(slice(seg_start, seg_end), slice(None)), :]

        base_rows = len(base_seg)
        filtered_rows = len(filtered_seg)
        removed_rows = base_rows - filtered_rows
        removed_ratio = (removed_rows / base_rows) if base_rows else 0.0

        base_limit_cnt = int((base_seg["LIMIT_STATUS"] == 1).sum())
        filtered_limit_cnt = int((filtered_seg["LIMIT_STATUS"] == 1).sum())

        print(
            f"[{seg_name}] rows(before/after)={base_rows}/{filtered_rows}, "
            f"removed={removed_rows} ({removed_ratio:.2%}), "
            f"limit_status_1(before/after)={base_limit_cnt}/{filtered_limit_cnt}"
        )

        if filtered_limit_cnt > 0:
            raise ValueError(
                f"验证失败：{seg_name} 分段过滤后仍存在 LIMIT_STATUS==1 样本（{filtered_limit_cnt} 条）。"
            )
        if base_limit_cnt > 0 and removed_rows <= 0:
            raise ValueError(
                f"验证失败：{seg_name} 分段存在涨停样本（{base_limit_cnt} 条），但过滤前后样本数无减少。"
            )

    print("✅ UnifiedLimitUpFilter 验证通过：train/valid/test 均已生效。\n")


def parse_train_cli(argv=None):
    """CLI for custom_train_backtest. --verify-filters gates the ~900s contrast handler."""
    parser = argparse.ArgumentParser(description="Qlib custom train/backtest (MyQuant)")
    parser.add_argument(
        "--verify-filters",
        action="store_true",
        help=(
            "Build a second contrast handler (exclude only) and run verify_limit_up_filter. "
            "Also enabled when env QLIB_VERIFY_FILTERS=1. Default path uses a single handler."
        ),
    )
    return parser.parse_args(argv)


def should_verify_filters(args=None) -> bool:
    if args is not None and getattr(args, "verify_filters", False):
        return True
    return os.environ.get("QLIB_VERIFY_FILTERS", "").strip().lower() in ("1", "true", "yes")
