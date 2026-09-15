"""Q3-R3/R4: production filter_pipe wiring and $zhangting limit-up rule."""

from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from custom_filter import UnifiedLimitUpFilter  # noqa: E402
from train_wiring import (  # noqa: E402
    DEFAULT_SEGMENTS,
    build_filtered_instruments,
    build_limit_up_filter,
    build_production_filter_pipe,
    parse_segment,
    parse_train_cli,
    resolve_segments,
    should_verify_filters,
    unique_pred_export_names,
    verify_limit_up_filter,
)


EXCLUDE_SAMPLE = ["SZ000004", "SH600107"]


def test_production_filter_pipe_order_and_length():
    pipe = build_production_filter_pipe(EXCLUDE_SAMPLE)
    assert len(pipe) == 2
    # Order: exclude NameDFilter → UnifiedLimitUpFilter($zhangting)
    assert pipe[0].__class__.__name__ == "NameDFilter"
    assert isinstance(pipe[1], UnifiedLimitUpFilter)
    assert pipe[1].rule_expression == "$zhangting == 0"
    assert pipe[1].keep is False


def test_build_filtered_instruments_not_bare_all():
    """Unit-testable without market fetch: inject instruments_fn."""
    captured = {}

    def fake_instruments(market="all", filter_pipe=None, start_time=None, end_time=None):
        captured["market"] = market
        captured["filter_pipe"] = filter_pipe
        captured["start_time"] = start_time
        captured["end_time"] = end_time
        return {"market": market, "filter_pipe": list(filter_pipe or [])}

    instruments = build_filtered_instruments(
        start_time="2026-01-01",
        end_time="2026-03-23",
        exclude_stocks=EXCLUDE_SAMPLE,
        instruments_fn=fake_instruments,
    )

    assert instruments != "all"
    assert isinstance(instruments, dict)
    assert instruments["market"] == "all"
    assert len(instruments["filter_pipe"]) == 2
    assert len(captured["filter_pipe"]) == 2
    assert captured["filter_pipe"][0].__class__.__name__ == "NameDFilter"
    assert isinstance(captured["filter_pipe"][1], UnifiedLimitUpFilter)


def test_limit_up_filter_keeps_zhangting_zero():
    f = build_limit_up_filter()
    assert f.rule_expression == "$zhangting == 0"
    assert f.keep is False
    # Explicit field mode — never silent 0.095 price fallback for production helper
    f2 = UnifiedLimitUpFilter(use_field="$zhangting", keep=False)
    assert f2.rule_expression == "$zhangting == 0"
    assert "0.095" not in f2.rule_expression
    assert "$close" not in f2.rule_expression


def test_filter_pipe_switches_drop_layers():
    """未开 --exclude-filter / 开了 --no-limit-filter 时对应层不进 pipe，全关时 pipe 为空。"""
    # 只关黑名单
    pipe = build_production_filter_pipe(EXCLUDE_SAMPLE, use_exclude=False)
    assert len(pipe) == 1
    assert isinstance(pipe[0], UnifiedLimitUpFilter)
    # 只关涨停过滤
    pipe = build_production_filter_pipe(EXCLUDE_SAMPLE, limit_up=False)
    assert len(pipe) == 1
    assert pipe[0].__class__.__name__ == "NameDFilter"
    # 全关
    assert build_production_filter_pipe(EXCLUDE_SAMPLE, use_exclude=False, limit_up=False) == []


def test_filtered_instruments_switches_passthrough():
    captured = {}

    def fake_instruments(market="all", filter_pipe=None, start_time=None, end_time=None):
        captured["filter_pipe"] = list(filter_pipe or [])
        return {"market": market, "filter_pipe": list(filter_pipe or [])}

    instruments = build_filtered_instruments(
        start_time="2026-01-01",
        end_time="2026-03-23",
        exclude_stocks=EXCLUDE_SAMPLE,
        instruments_fn=fake_instruments,
        use_exclude=False,
        limit_up=False,
    )
    assert instruments["filter_pipe"] == []
    assert captured["filter_pipe"] == []


def test_guard_and_cache_cli_flags_default_off():
    args = parse_train_cli([])
    assert args.exclude_filter is False
    assert args.no_exclude_filter is False
    assert args.no_limit_filter is False
    assert args.no_limit_threshold is False
    assert args.dataset_cache is False
    assert args.expr_cache is False
    assert args.handler_cache is False
    assert args.no_export_analysis is False
    args_on = parse_train_cli(["--exclude-filter"])
    assert args_on.exclude_filter is True
    args_off = parse_train_cli(
        [
            "--no-exclude-filter",
            "--no-limit-filter",
            "--no-limit-threshold",
            "--dataset-cache",
            "--expr-cache",
            "--handler-cache",
            "--no-export-analysis",
        ]
    )
    assert args_off.no_exclude_filter is True
    assert args_off.no_limit_filter is True
    assert args_off.no_limit_threshold is True
    assert args_off.dataset_cache is True
    assert args_off.expr_cache is True
    assert args_off.handler_cache is True
    assert args_off.no_export_analysis is True


def test_verify_missing_zhangting_error_mentions_field():
    class _FakeHandler:
        def fetch(self, col_set="feature"):
            import pandas as pd

            return pd.DataFrame({"OTHER": [1, 2]})

    with pytest.raises(ValueError) as exc:
        verify_limit_up_filter(_FakeHandler(), _FakeHandler(), {"train": ("2026-01-01", "2026-01-31")})
    assert "$zhangting" in str(exc.value)


def test_verify_filters_cli_default_off():
    args = parse_train_cli([])
    assert args.verify_filters is False
    assert should_verify_filters(args) is False
    args_on = parse_train_cli(["--verify-filters"])
    assert args_on.verify_filters is True
    assert should_verify_filters(args_on) is True


def test_verify_filters_env(monkeypatch):
    monkeypatch.setenv("QLIB_VERIFY_FILTERS", "1")
    assert should_verify_filters(parse_train_cli([])) is True
    monkeypatch.setenv("QLIB_VERIFY_FILTERS", "0")
    assert should_verify_filters(parse_train_cli([])) is False


def test_parse_segment_valid_and_invalid():
    assert parse_segment("2026-01-01:2026-03-23", "train") == ("2026-01-01", "2026-03-23")
    assert parse_segment(" 2026-01-01 : 2026-03-23 ", "train") == ("2026-01-01", "2026-03-23")
    with pytest.raises(SystemExit):
        parse_segment("2026-01-01", "train")  # 缺 END
    with pytest.raises(SystemExit):
        parse_segment("2026-1-1:2026-03-23", "train")  # 非 YYYY-MM-DD
    with pytest.raises(SystemExit):
        parse_segment("2026-03-23:2026-01-01", "train")  # 起始晚于截止


def test_resolve_segments_default_backward_compatible():
    """三段全缺省 = 现役三月窗（向后兼容硬要求）。"""
    segs = resolve_segments(parse_train_cli([]))
    assert segs == DEFAULT_SEGMENTS


def test_resolve_segments_requires_all_three():
    with pytest.raises(SystemExit):
        resolve_segments(parse_train_cli(["--train", "2020-01-01:2024-12-31"]))
    with pytest.raises(SystemExit):
        resolve_segments(
            parse_train_cli(["--train", "2020-01-01:2024-12-31", "--test", "2026-01-01:2026-09-14"])
        )


def test_resolve_segments_long_window_ordering():
    segs = resolve_segments(
        parse_train_cli(
            [
                "--train", "2020-01-01:2024-12-31",
                "--valid", "2025-01-01:2025-12-31",
                "--test", "2026-01-01:2026-09-14",
            ]
        )
    )
    assert segs["train"] == ("2020-01-01", "2024-12-31")
    assert segs["valid"] == ("2025-01-01", "2025-12-31")
    assert segs["test"] == ("2026-01-01", "2026-09-14")


def test_resolve_segments_rejects_bad_ordering():
    with pytest.raises(SystemExit):
        resolve_segments(
            parse_train_cli(
                [
                    "--train", "2026-01-01:2026-01-31",
                    "--valid", "2025-01-01:2025-12-31",  # valid.start < train.start
                    "--test", "2026-03-01:2026-03-23",
                ]
            )
        )


def test_unique_pred_export_names_never_bare():
    pred, labeled = unique_pred_export_names(
        "907edbfbd9ae48b0b5d8828626ec4476",
        10,
        3,
        created_utc="2026-09-15T06:11:16Z",
    )
    assert pred == "预测结果_20260915T061116Z_907edbfb_10n3.csv"
    assert labeled == "预测结果和真实标签_20260915T061116Z_907edbfb_10n3.csv"
    assert pred != "预测结果.csv"
    assert labeled != "预测结果和真实标签.csv"
