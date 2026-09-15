"""Qlib train R3 wiring helpers (filter_pipe + verify).

Kept free of report/plotly/LGB imports so unit tests can import without
pulling the full custom_train_backtest entrypoint.

Note: ``verify_limit_up_filter`` is opt-in only (``--verify-filters`` /
``QLIB_VERIFY_FILTERS``). It full-fetches feature matrices and can OOM on
long windows; the default train path must never call it.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime

import pandas as pd

from qlib.data import D
from qlib.data.filter import NameDFilter

from custom_filter import UnifiedLimitUpFilter

# 缺省三月窗 = 现役 m5r2 窗；--train/--valid/--test 全缺省时维持向后兼容。
DEFAULT_SEGMENTS = {
    "train": ("2026-01-01", "2026-01-31"),
    "valid": ("2026-02-01", "2026-02-28"),
    "test": ("2026-03-01", "2026-03-23"),
}

# ST/风险股静态黑名单（非 PIT；来源为仓库历史维护清单，QMT 可用时可经
# qlib_scripts/list_st.py 重新生成全量后经 --extra-exclude-file 追加）。
# 消费方：训练宇宙过滤、build_tradable_universe.py、buy_eligibility 策略级 ST 过滤。
EXCLUDE_STOCKS_DEFAULT = ['SZ000004', 'SZ000430', 'SZ000488', 'SZ000504', 'SZ000518', 'SZ000595', 'SZ000608', 'SZ000609', 'SZ000615', 'SZ000638', 'SZ000656', 'SZ000668', 'SZ000669', 'SZ000691', 'SZ000697', 'SZ000698', 'SZ000711', 'SZ000736', 'SZ000752', 'SZ000793', 'SZ000820', 'SZ000903', 'SZ000908', 'SZ000909', 'SZ000929', 'SZ000972', 'SZ001270', 'SZ002005', 'SZ002024', 'SZ002047', 'SZ002058', 'SZ002076', 'SZ002122', 'SZ002168', 'SZ002197', 'SZ002199', 'SZ002200', 'SZ002211', 'SZ002214', 'SZ002231', 'SZ002253', 'SZ002289', 'SZ002305', 'SZ002306', 'SZ002388', 'SZ002425', 'SZ002485', 'SZ002496', 'SZ002528', 'SZ002529', 'SZ002569', 'SZ002581', 'SZ002586', 'SZ002592', 'SZ002620', 'SZ002630', 'SZ002647', 'SZ002650', 'SZ002656', 'SZ002693', 'SZ002713', 'SZ002717', 'SZ002742', 'SZ002762', 'SZ002789', 'SZ002808', 'SZ002816', 'SZ002822', 'SZ002848', 'SZ002868', 'SZ002872', 'SZ002898', 'SZ003004', 'SZ003032', 'SZ300020', 'SZ300029', 'SZ300044', 'SZ300052', 'SZ300093', 'SZ300096', 'SZ300097', 'SZ300125', 'SZ300137', 'SZ300147', 'SZ300152', 'SZ300159', 'SZ300165', 'SZ300167', 'SZ300175', 'SZ300198', 'SZ300205', 'SZ300211', 'SZ300225', 'SZ300237', 'SZ300268', 'SZ300301', 'SZ300311', 'SZ300313', 'SZ300326', 'SZ300338', 'SZ300343', 'SZ300344', 'SZ300366', 'SZ300376', 'SZ300379', 'SZ300391', 'SZ300419', 'SZ300462', 'SZ300472', 'SZ300477', 'SZ300506', 'SZ300527', 'SZ300555', 'SZ300561', 'SZ300716', 'SZ300899', 'SZ301288', 'SH600107', 'SH600130', 'SH600136', 'SH600165', 'SH600169', 'SH600193', 'SH600200', 'SH600228', 'SH600238', 'SH600243', 'SH600265', 'SH600289', 'SH600355', 'SH600358', 'SH600360', 'SH600365', 'SH600381', 'SH600421', 'SH600525', 'SH600568', 'SH600599', 'SH600608', 'SH600624', 'SH600636', 'SH600696', 'SH600735', 'SH600753', 'SH600777', 'SH600892', 'SH603007', 'SH603021', 'SH603261', 'SH603268', 'SH603377', 'SH603388', 'SH603389', 'SH603398', 'SH603517', 'SH603557', 'SH603559', 'SH603580', 'SH603595', 'SH603721', 'SH603789', 'SH603813', 'SH603825', 'SH603828', 'SH603838', 'SH603843', 'SH603869', 'SH605081', 'SH605199', 'SH688053', 'SH688076', 'SH688184', 'SH688287', 'SH688511', 'SH688646', 'BJ920305', 'BJ920680']


def build_exclude_name_filter(exclude_stocks):
    """NameDFilter regex that keeps instruments not in exclude_stocks."""
    return NameDFilter(name_rule_re="^(?!(" + "|".join(exclude_stocks) + ")).*$")


def build_limit_up_filter():
    """Production limit-up filter: $zhangting field mode only (keep=False)."""
    return UnifiedLimitUpFilter(use_field="$zhangting", keep=False)


# 与交易所执行层同源的涨跌停阈值；--no-limit-threshold 时回测侧传 None（不拒单）。
DEFAULT_LIMIT_THRESHOLD = 0.095


def build_production_filter_pipe(exclude_stocks, use_exclude=True, limit_up=True):
    """Exclude blacklist then $zhangting limit-up. Order is part of the contract.

    use_exclude/limit_up 对应 --exclude-filter / --no-limit-filter
    （黑名单默认关，需 --exclude-filter 才进 pipe；涨停层默认开）。
    """
    pipe = []
    if use_exclude:
        pipe.append(build_exclude_name_filter(exclude_stocks))
    if limit_up:
        pipe.append(build_limit_up_filter())
    return pipe


def build_filtered_instruments(
    start_time,
    end_time,
    exclude_stocks,
    market="all",
    instruments_fn=None,
    use_exclude=True,
    limit_up=True,
):
    """Production instruments: D.instruments(..., filter_pipe=[exclude, limit_up]).

    Returns the instruments config object (dict with market + filter_pipe).
    Does not hang filter_pipe on the handler dict — that key is not the live path.
    instruments_fn is injectable for unit tests (defaults to D.instruments).
    """
    filter_pipe = build_production_filter_pipe(
        exclude_stocks, use_exclude=use_exclude, limit_up=limit_up
    )
    fn = D.instruments if instruments_fn is None else instruments_fn
    return fn(
        market=market,
        start_time=start_time,
        end_time=end_time,
        filter_pipe=filter_pipe,
    )


def verify_limit_up_filter(filtered_handler, unfiltered_handler, segments):
    """验证 UnifiedLimitUpFilter 是否在 train/valid/test 三段生效。

    OPT-IN ONLY (``--verify-filters`` / ``QLIB_VERIFY_FILTERS``).
    Performs two full ``handler.fetch(col_set="feature")`` loads — can OOM
    on long windows / full-market. Do not call from the default train path.
    """
    print(
        "[WARN] verify_limit_up_filter: opt-in full handler.fetch(col_set='feature') "
        "×2 — OOM risk on long windows",
        flush=True,
    )
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


def parse_segment(value: str, name: str) -> tuple[str, str]:
    """'2026-01-01:2026-03-23' -> ("2026-01-01", "2026-03-23")；非法格式/倒序直接 SystemExit。"""
    try:
        start, end = value.split(":", 1)
        start, end = start.strip(), end.strip()
        if not start or not end:
            raise ValueError
        datetime.strptime(start, "%Y-%m-%d")
        datetime.strptime(end, "%Y-%m-%d")
    except ValueError:
        raise SystemExit(f"--{name} 需要 START:END 格式（YYYY-MM-DD:YYYY-MM-DD），收到: {value!r}")
    if start > end:
        raise SystemExit(f"--{name} 起始晚于截止: {value!r}")
    return start, end


def resolve_segments(args) -> dict[str, tuple[str, str]]:
    """三段全缺省 = DEFAULT_SEGMENTS（向后兼容）；任一给出则三段必须齐全且段序合法。"""
    given = {n: getattr(args, n) for n in ("train", "valid", "test") if getattr(args, n)}
    if not given:
        return dict(DEFAULT_SEGMENTS)
    missing = [n for n in ("train", "valid", "test") if n not in given]
    if missing:
        raise SystemExit(f"--train/--valid/--test 必须三段齐全给出，缺少: {', '.join(missing)}")
    segs = {n: parse_segment(v, n) for n, v in given.items()}
    if not (segs["train"][0] <= segs["valid"][0] <= segs["test"][0]):
        raise SystemExit(f"段序非法，要求 train.start <= valid.start <= test.start: {segs}")
    return segs


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
    parser.add_argument(
        "--train",
        default=None,
        help="训练窗 START:END（YYYY-MM-DD:YYYY-MM-DD）。三段全缺省=现役三月窗；任一给出则三段必填。",
    )
    parser.add_argument(
        "--valid",
        default=None,
        help="验证窗 START:END（YYYY-MM-DD:YYYY-MM-DD）。",
    )
    parser.add_argument(
        "--test",
        default=None,
        help="测试/回测窗 START:END（YYYY-MM-DD:YYYY-MM-DD）。",
    )
    parser.add_argument(
        "--exclude-filter",
        action="store_true",
        help="打开静态黑名单剔除（EXCLUDE_STOCKS_DEFAULT 177 只挂 NameDFilter）。默认关闭，不使用黑名单。",
    )
    parser.add_argument(
        "--no-exclude-filter",
        action="store_true",
        help="已废弃：黑名单默认关闭，此开关保持关闭（兼容旧命令行）。",
    )
    parser.add_argument(
        "--no-limit-filter",
        action="store_true",
        help=(
            "关掉第一层涨停过滤：filter_pipe 不再剔除 T 日涨停股"
            "（黑名单剔除保留）。默认开启过滤。"
        ),
    )
    parser.add_argument(
        "--no-limit-threshold",
        action="store_true",
        help=(
            "关掉第四层涨跌停拒单：交易所 limit_threshold 置 None，"
            "涨停可买、跌停可卖。默认 0.095 拒单。"
        ),
    )
    parser.add_argument(
        "--dataset-cache",
        action="store_true",
        help=(
            "启用 qlib SimpleDatasetCache（~/.cache/qlib_simple_cache）。"
            "Windows 上只在「确认同配置复跑」时开；闸门/宇宙一变即 miss，"
            "16 worker 读几十万小文件会比裸读更慢（见 runbook / perf N3）。"
            "优先用 --handler-cache。"
        ),
    )
    parser.add_argument(
        "--expr-cache",
        action="store_true",
        help=(
            "启用 qlib DiskExpressionCache（<provider_uri>/features_cache，约 95 万小文件）。"
            "冷填在 NTFS 上比裸读慢；只在同配置复跑时划算。优先 --handler-cache。"
            "Redis 不可用时 qlib 自动降级关闭。"
        ),
    )
    parser.add_argument(
        "--handler-cache",
        action="store_true",
        help=(
            "项目级单文件 handler 缓存（to_pickle dump_all，默认 ~/.cache/qlib_handler_cache；"
            "OSKH_HANDLER_CACHE_DIR 可改）。键含窗/闸门/特征开关/日历指纹。"
            "同配置二次运行跳过 handler_init；换配置或刷新 my_data 自动 miss。"
        ),
    )
    parser.add_argument(
        "--tradable-universe",
        action="store_true",
        help=(
            "训练宇宙改用 instruments/all_tradable.txt（build_tradable_universe.py 生成："
            "−ST 黑名单、起始日顺延 60 交易日）。ST/新股从源头不进训练与预测。缺省 all。"
        ),
    )
    parser.add_argument(
        "--buy-state-filter",
        action="store_true",
        help=(
            "策略级买入状态过滤（开关①）：MA20/MA60 之下且 盈筹率<10% 可买，"
            "或站上 MA20 且 5 日线斜率>=-30° 可买；过滤后从后排得分回补（开关④）。"
        ),
    )
    parser.add_argument(
        "--preview-rows",
        type=int,
        default=0,
        help=(
            "特征列预览行数（默认 0）。即使 >0 也禁止全量 handler.fetch(col_set='feature')；"
            "仅对 get_feature_config() 表达式列名做前 N 切片打印（零 IO）。"
        ),
    )
    return parser.parse_args(argv)


def should_verify_filters(args=None) -> bool:
    if args is not None and getattr(args, "verify_filters", False):
        return True
    return os.environ.get("QLIB_VERIFY_FILTERS", "").strip().lower() in ("1", "true", "yes")
