"""Qlib train R3 wiring helpers (filter_pipe + verify).

Kept free of report/plotly/LGB imports so unit tests can import without
pulling the full custom_train_backtest entrypoint.
"""

from __future__ import annotations

import argparse
import os

import pandas as pd

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


def check_pred_report_alignment(pred_dates, report_dates):
    """走查优先级5：pred.pkl 与 report_normal_1day 首尾对齐自检。

    TopkDropoutStrategy 取信号 shift=1：交易日 T 用 T-1 的 pred。因此预期
    report 首日 == pred 首日（首日无前日 pred、空仓属正常），report 交易日
    应落在 pred 日期集合内。只对明显错位报错（report 早于 pred / 完全不相交），
    其余打印观察值供人工核对。
    """
    pred_index = pd.DatetimeIndex(pd.unique(pd.to_datetime(list(pred_dates)))).sort_values()
    report_index = pd.DatetimeIndex(pd.unique(pd.to_datetime(list(report_dates)))).sort_values()
    if len(pred_index) == 0 or len(report_index) == 0:
        raise ValueError("对齐自检失败：pred 或 report 日期为空。")

    missing = report_index.difference(pred_index)
    print(
        f"[alignment] pred[{pred_index.min().date()}..{pred_index.max().date()}] "
        f"({len(pred_index)}d) vs report[{report_index.min().date()}..{report_index.max().date()}] "
        f"({len(report_index)}d), report 日期不在 pred 集合内: {len(missing)}"
    )
    if report_index.min() < pred_index.min():
        raise ValueError(
            f"对齐自检失败：report 首日 {report_index.min().date()} 早于 pred 首日 "
            f"{pred_index.min().date()}，存在无信号先交易的风险。"
        )
    if len(missing) == len(report_index):
        raise ValueError("对齐自检失败：report 与 pred 日期完全不相交。")
    if len(missing) > 0:
        print(
            f"[alignment] 警告：{len(missing)} 个 report 交易日无对应 pred 日期"
            f"（前3个: {[str(d.date()) for d in missing[:3]]}），请核对 segments 与回测区间。"
        )
    return {
        "pred_first": pred_index.min(),
        "pred_last": pred_index.max(),
        "report_first": report_index.min(),
        "report_last": report_index.max(),
        "report_days_missing_from_pred": int(len(missing)),
    }


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
