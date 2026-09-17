"""Qlib train R3 wiring helpers (filter_pipe + verify).

Kept free of report/plotly/LGB imports so unit tests can import without
pulling the full custom_train_backtest entrypoint.

Note: ``verify_limit_up_filter`` is opt-in only (``--verify-filters`` /
``QLIB_VERIFY_FILTERS``). It full-fetches feature matrices and can OOM on
long windows; the default train path must never call it.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

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

# 静态黑名单默认空。ST 以 --st-daily-file 的 PIT 为准；要加名单用 --extra-exclude-file。
EXCLUDE_STOCKS_DEFAULT: list[str] = []


def build_exclude_name_filter(exclude_stocks):
    """NameDFilter regex that keeps instruments not in exclude_stocks.

    Empty list is a no-op (do not emit ``^(?!(|))``).
    """
    names = [str(c) for c in (exclude_stocks or []) if str(c).strip()]
    if not names:
        return None
    return NameDFilter(name_rule_re="^(?!(" + "|".join(names) + ")).*$")


def build_limit_up_filter():
    """Production limit-up filter: $zhangting field mode only (keep=False)."""
    return UnifiedLimitUpFilter(use_field="$zhangting", keep=False)


# 与交易所执行层同源的涨跌停阈值；--no-limit-threshold 时回测侧传 None（不拒单）。
DEFAULT_LIMIT_THRESHOLD = 0.095


def build_production_filter_pipe(exclude_stocks, use_exclude=True, limit_up=False):
    """Exclude blacklist then $zhangting limit-up. Order is part of the contract.

    use_exclude/limit_up 对应 --exclude-filter / --limit-filter
    （两层默认关；要进 pipe 须显式打开）。
    """
    pipe = []
    if use_exclude:
        exclude_filter = build_exclude_name_filter(exclude_stocks)
        if exclude_filter is not None:
            pipe.append(exclude_filter)
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
    limit_up=False,
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
        help="打开静态黑名单剔除（EXCLUDE_STOCKS_DEFAULT，现为空；可经 --extra-exclude-file 追加）。默认关闭。",
    )
    parser.add_argument(
        "--no-exclude-filter",
        action="store_true",
        help="已废弃：黑名单默认关闭，此开关保持关闭（兼容旧命令行）。",
    )
    parser.add_argument(
        "--limit-filter",
        action="store_true",
        help=(
            "打开第一层涨停出池（UnifiedLimitUpFilter / $zhangting）。"
            "默认关闭：不是 qlib 原生宇宙过滤。"
        ),
    )
    parser.add_argument(
        "--no-limit-filter",
        action="store_true",
        help="已废弃：涨停出池默认关闭，此开关保持关闭（兼容旧命令行）。",
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
        "--drop-limit-up-learn",
        action="store_true",
        help=(
            "训练帧剔除 LIMIT_STATUS==1（DropLimitUpLearn）。"
            "默认关闭：不是 qlib 原生 learn processor；不影响 infer / 出分。"
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
            "写后 size 超 OSKH_HANDLER_CACHE_WARN_MB（默认 4096；Win 分档 4096/8192）仅 WARN。"
        ),
    )
    parser.add_argument(
        "--tradable-universe",
        action="store_true",
        help=(
            "训练宇宙改用 instruments/all_tradable.txt（−ST、起始日顺延 60 交易日）。"
            "默认 all，不做宇宙层过滤。"
        ),
    )
    parser.add_argument(
        "--st-filter",
        action="store_true",
        help="策略买入时禁买 ST。给 --st-daily-file 则只认 parquet 当日 is_st（不读 st_coverage.json）；否则用 EXCLUDE_STOCKS_DEFAULT（现为空）。宇宙仍是 all。",
    )
    parser.add_argument(
        "--age-filter",
        action="store_true",
        help="策略买入时禁买上市不足 --age-days 个交易日的票。宇宙仍是 all，不影响训练。",
    )
    parser.add_argument(
        "--age-days",
        type=int,
        default=60,
        help="配合 --age-filter：上市年龄门槛（交易日，默认 60）。",
    )
    parser.add_argument(
        "--st-daily-file",
        default=None,
        help="st_daily.parquet：--st-filter 只读此表 is_st（与 BT 对齐，不读同目录 st_coverage.json）。",
    )
    parser.add_argument(
        "--buy-state-filter",
        action="store_true",
        help=(
            "策略级买入状态过滤：MA20/MA60 之下且 盈筹率<10% 可买，"
            "或站上 MA20 且 5 日线斜率>=-30° 可买。不含 5 日涨幅过滤。"
        ),
    )
    parser.add_argument(
        "--return-threshold-filter",
        action="store_true",
        help="策略买入时丢掉过去 5 日涨幅超过 15%% 的票。默认关，与 ST/年龄/买入状态独立。",
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
    parser.add_argument(
        "--no-export-analysis",
        action="store_true",
        help=(
            "跳过盘后分析包（持仓/成交/流水账/荐股 CSV）。"
            "默认在 PortAna 之后从已落盘 positions 导出，不重回测。"
        ),
    )
    parser.add_argument(
        "--timing-interval-steps",
        type=int,
        default=10,
        help=(
            "TopkDropoutStrategyWithFilter TimerRecorder 采样间隔（默认 10，生产保持）。"
            "短窗 bar 调用谱诊断用 1；仅在 --buy-state-filter（过滤策略）路径生效。"
            "always-on 计数器（df/tradable/deal_price/factor）不受此门控。"
        ),
    )
    parser.add_argument(
        "--topk",
        type=int,
        default=10,
        help="TopkDropout 目标持仓数（默认 10）。",
    )
    parser.add_argument(
        "--n-drop",
        dest="n_drop",
        type=int,
        default=3,
        help="每次调仓丢弃的最弱持仓数（默认 3）。",
    )
    parser.add_argument(
        "--num-boost-round",
        dest="num_boost_round",
        type=int,
        default=1000,
        help="LGB 最大轮数（默认 1000，与 qlib LGBModel 一致）。第三窗固定轮数时显式传入。",
    )
    parser.add_argument(
        "--early-stopping-rounds",
        dest="early_stopping_rounds",
        type=int,
        default=50,
        help="LGB 早停耐心（默认 50）。关早停时设为与 --num-boost-round 相同，使回调不会提前停。",
    )
    parser.add_argument(
        "--model",
        default="lgb",
        help=(
            "学习器名或配置文件路径。默认 lgb。"
            "名字对应 configs/models/<name>.yaml（也认 .yml/.json）。"
            "换模型：复制一份 YAML 改 class/kwargs，不必改训练脚本。"
        ),
    )
    parser.add_argument(
        "--model-config",
        dest="model_config",
        default=None,
        help="显式模型配置路径（yaml/yml/json），覆盖 --model 的名字查找。",
    )
    parser.add_argument(
        "--exp-name",
        dest="exp_name",
        default="alpha158_cost_kdj_lgb",
        help="MLflow / qlib 实验名（默认 alpha158_cost_kdj_lgb，与现役 recorder 同实验）。",
    )
    return parser.parse_args(argv)


MODEL_CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs" / "models"
_MODEL_SUFFIXES = (".yaml", ".yml", ".json")


def resolve_model_config_path(args) -> Path:
    """--model-config > 已有文件路径 > configs/models/<name>.{yaml,yml,json}."""
    explicit = getattr(args, "model_config", None)
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise FileNotFoundError(f"--model-config not found: {path}")
        return path
    raw = str(getattr(args, "model", "lgb") or "lgb")
    candidate = Path(raw)
    if candidate.suffix.lower() in _MODEL_SUFFIXES or candidate.is_file():
        if not candidate.is_file():
            raise FileNotFoundError(f"--model file not found: {candidate}")
        return candidate
    for suffix in _MODEL_SUFFIXES:
        named = MODEL_CONFIG_DIR / f"{raw}{suffix}"
        if named.is_file():
            return named
    known = ", ".join(sorted(p.stem for p in MODEL_CONFIG_DIR.glob("*.*") if p.suffix.lower() in _MODEL_SUFFIXES))
    raise FileNotFoundError(
        f"model config not found for --model {raw!r}. "
        f"Add configs/models/{raw}.yaml or pass --model-config. Available: {known or '(none)'}"
    )


def _load_model_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".json":
        spec = json.loads(text)
    elif suffix in (".yaml", ".yml"):
        import yaml

        spec = yaml.safe_load(text)
    else:
        raise ValueError(f"unsupported model config suffix: {path}")
    if not isinstance(spec, dict):
        raise ValueError(f"model config must be a mapping: {path}")
    return spec


def _render_placeholders(obj, mapping: dict):
    if isinstance(obj, dict):
        return {k: _render_placeholders(v, mapping) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_render_placeholders(v, mapping) for v in obj]
    if isinstance(obj, str) and obj in mapping:
        return mapping[obj]
    return obj


def _apply_cli_boost(spec: dict, args) -> dict:
    n_boost = int(args.num_boost_round)
    n_stop = int(args.early_stopping_rounds)
    out = dict(spec)
    for key in ("kwargs", "fit_kwargs"):
        block = out.get(key)
        if not isinstance(block, dict):
            continue
        block = dict(block)
        if "num_boost_round" in block:
            block["num_boost_round"] = n_boost
        if "early_stopping_rounds" in block:
            block["early_stopping_rounds"] = n_stop
        out[key] = block
    return out


def build_model_task(args, num_threads: int, n_features: int | None = None) -> dict:
    """Load qlib model task from YAML/JSON. New learner = new file, no code change."""
    path = resolve_model_config_path(args)
    spec = _apply_cli_boost(_load_model_file(path), args)
    spec = _render_placeholders(
        spec,
        {
            "$num_threads": int(num_threads),
            "$n_features": int(n_features) if n_features else 183,
        },
    )
    missing = [k for k in ("class", "module_path") if k not in spec]
    if missing:
        raise ValueError(f"model config {path} missing {missing}")
    fit_kwargs = spec.get("fit_kwargs") or {}
    if not isinstance(fit_kwargs, dict):
        raise ValueError(f"model config {path} fit_kwargs must be a mapping")
    args.fit_kwargs = dict(fit_kwargs)
    args.model_config_path = str(path)
    print(f"[model] source={path} class={spec['class']}", flush=True)
    return {
        "class": spec["class"],
        "module_path": spec["module_path"],
        "kwargs": dict(spec.get("kwargs") or {}),
    }


def resolve_train_timing_path(base_dir, exp_name: str, model: str, created_utc: str | None = None) -> Path:
    """Unique timing JSON so a model sweep does not overwrite the previous run."""
    ts = created_utc or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw = str(model or "lgb")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in Path(raw).stem)
    name = f"timing_{exp_name}_{safe}_{ts}.json"
    return Path(base_dir) / name


def extract_portana_metrics(analysis_df) -> dict:
    """Named cells from qlib ``port_analysis_1day.pkl`` (column ``risk``)."""
    keys = (
        ("excess_return_with_cost", "annualized_return", "excess_ann_with_cost"),
        ("excess_return_with_cost", "information_ratio", "excess_ir_with_cost"),
        ("excess_return_with_cost", "max_drawdown", "excess_mdd_with_cost"),
        ("excess_return_without_cost", "annualized_return", "excess_ann_without_cost"),
        ("excess_return_without_cost", "information_ratio", "excess_ir_without_cost"),
        ("excess_return_without_cost", "max_drawdown", "excess_mdd_without_cost"),
    )
    out: dict = {}
    if analysis_df is None:
        return out
    col = "risk" if hasattr(analysis_df, "columns") and "risk" in analysis_df.columns else None
    for group, stat, alias in keys:
        try:
            val = analysis_df.loc[(group, stat)]
            if col is not None:
                val = val[col] if hasattr(val, "__getitem__") and col in getattr(val, "index", []) else val
            out[alias] = float(val.iloc[0] if hasattr(val, "iloc") else val)
        except Exception:
            out[alias] = None
    return out


def build_fit_kwargs(args) -> dict:
    extra = getattr(args, "fit_kwargs", None)
    return dict(extra) if isinstance(extra, dict) else {}


def should_verify_filters(args=None) -> bool:
    if args is not None and getattr(args, "verify_filters", False):
        return True
    return os.environ.get("QLIB_VERIFY_FILTERS", "").strip().lower() in ("1", "true", "yes")


def unique_pred_export_names(
    recorder_id: str,
    topk: int,
    n_drop: int,
    *,
    created_utc: str | None = None,
) -> tuple[str, str]:
    """Stamp pred CSVs so a new train never overwrites ``预测结果.csv``.

    Example: ``预测结果_20260915T061116Z_907edbfb_10n3.csv``.
    """
    if created_utc:
        ts = created_utc.replace("-", "").replace(":", "")
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rid = (recorder_id or "norec")[:8]
    tag = f"{ts}_{rid}_{int(topk)}n{int(n_drop)}"
    return f"预测结果_{tag}.csv", f"预测结果和真实标签_{tag}.csv"
