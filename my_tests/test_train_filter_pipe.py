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
    EXCLUDE_STOCKS_DEFAULT,
    build_exclude_name_filter,
    build_filtered_instruments,
    build_limit_up_filter,
    build_production_filter_pipe,
    extract_portana_metrics,
    parse_segment,
    parse_train_cli,
    resolve_segments,
    resolve_train_timing_path,
    should_verify_filters,
    unique_pred_export_names,
    verify_limit_up_filter,
)


EXCLUDE_SAMPLE = ["SZ000004", "SH600107"]


def test_exclude_stocks_default_is_empty():
    assert EXCLUDE_STOCKS_DEFAULT == []
    assert build_exclude_name_filter([]) is None
    assert build_production_filter_pipe([], use_exclude=True, limit_up=False) == []


def test_production_filter_pipe_order_and_length():
    pipe = build_production_filter_pipe(EXCLUDE_SAMPLE, limit_up=True)
    assert len(pipe) == 2
    # Order: exclude NameDFilter → UnifiedLimitUpFilter($zhangting)
    assert pipe[0].__class__.__name__ == "NameDFilter"
    assert isinstance(pipe[1], UnifiedLimitUpFilter)
    assert pipe[1].rule_expression == "$zhangting == 0"
    assert pipe[1].keep is False
    # Default: $zhangting 出池关，只留显式打开的黑名单层
    default_pipe = build_production_filter_pipe(EXCLUDE_SAMPLE)
    assert len(default_pipe) == 1
    assert default_pipe[0].__class__.__name__ == "NameDFilter"


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
        limit_up=True,
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
    """未开 --exclude-filter / 未开 --limit-filter 时对应层不进 pipe，全关时 pipe 为空。"""
    # 只开涨停出池
    pipe = build_production_filter_pipe(EXCLUDE_SAMPLE, use_exclude=False, limit_up=True)
    assert len(pipe) == 1
    assert isinstance(pipe[0], UnifiedLimitUpFilter)
    # 默认：黑名单开、涨停出池关
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
    assert args.limit_filter is False
    assert args.no_limit_filter is False
    assert args.drop_limit_up_learn is False
    assert args.st_filter is False
    assert args.age_filter is False
    assert args.return_threshold_filter is False
    assert args.no_limit_threshold is False
    assert args.dataset_cache is False
    assert args.expr_cache is False
    assert args.handler_cache is False
    assert args.no_export_analysis is False
    assert args.topk == 10
    assert args.n_drop == 3
    assert args.num_boost_round == 1000
    assert args.early_stopping_rounds == 50
    assert args.model == "lgb"
    assert args.exp_name == "alpha158_cost_kdj_lgb"
    args_xgb = parse_train_cli(["--model", "xgb"])
    assert args_xgb.model == "xgb"
    args_cat = parse_train_cli(["--model", "cat"])
    assert args_cat.model == "cat"
    from train_wiring import build_model_task

    lgb_task = build_model_task(args, 20)
    assert lgb_task["class"] == "LGBModel"
    assert lgb_task["kwargs"]["num_threads"] == 20
    xgb_task = build_model_task(args_xgb, 20)
    assert xgb_task["class"] == "XGBModel"
    assert "num_leaves" not in xgb_task["kwargs"]
    cat_task = build_model_task(args_cat, 20)
    assert cat_task["class"] == "CatBoostModel"
    assert "num_leaves" not in cat_task["kwargs"]
    assert "rsm" not in cat_task["kwargs"]
    assert cat_task["kwargs"]["bootstrap_type"] == "Bernoulli"
    args_dnn = parse_train_cli(["--model", "dnn"])
    assert args_dnn.model == "dnn"
    dnn_task = build_model_task(args_dnn, 20, n_features=183)
    assert dnn_task["class"] == "DNNModelPytorch"
    assert dnn_task["kwargs"]["optimizer"] == "adam"
    assert dnn_task["kwargs"]["pt_model_kwargs"]["input_dim"] == 183
    from train_wiring import MODEL_CONFIG_DIR, build_fit_kwargs, resolve_model_config_path

    assert resolve_model_config_path(args).name == "lgb.yaml"
    assert build_fit_kwargs(args_xgb)["num_boost_round"] == 1000
    assert build_fit_kwargs(args_dnn) == {}
    args_cfg = parse_train_cli(["--model-config", str(MODEL_CONFIG_DIR / "cat.yaml")])
    cat_from_cfg = build_model_task(args_cfg, 20)
    assert cat_from_cfg["class"] == "CatBoostModel"
    missing = parse_train_cli(["--model", "not-a-real-learner"])
    try:
        resolve_model_config_path(missing)
    except FileNotFoundError as exc:
        assert "not-a-real-learner" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError for unknown --model")
    extra = {
        "ridge": "LinearModel",
        "lasso": "LinearModel",
        "tabnet": "TabnetModel",
        "gru": "GRU",
        "lstm": "LSTM",
        "alstm": "ALSTM",
        "tcn": "TCN",
        "densemble": "DEnsembleModel",
    }
    for name, cls_name in extra.items():
        extra_args = parse_train_cli(["--model", name])
        extra_task = build_model_task(extra_args, 8, n_features=183)
        assert extra_task["class"] == cls_name, name
        assert resolve_model_config_path(extra_args).stem == name
    args_wide = parse_train_cli(["--topk", "50", "--n-drop", "5"])
    assert args_wide.topk == 50
    assert args_wide.n_drop == 5
    args_on = parse_train_cli(["--exclude-filter"])
    assert args_on.exclude_filter is True
    args_limit = parse_train_cli(["--limit-filter"])
    assert args_limit.limit_filter is True
    args_drop = parse_train_cli(["--drop-limit-up-learn"])
    assert args_drop.drop_limit_up_learn is True
    args_st = parse_train_cli(["--st-filter"])
    assert args_st.st_filter is True
    assert args_st.age_filter is False
    assert args_st.return_threshold_filter is False
    args_age = parse_train_cli(["--age-filter"])
    assert args_age.age_filter is True
    assert args_age.st_filter is False
    args_ret = parse_train_cli(["--return-threshold-filter"])
    assert args_ret.return_threshold_filter is True
    assert args_ret.st_filter is False
    assert args_ret.buy_state_filter is False
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


def test_resolve_train_timing_path_is_unique_per_model():
    a = resolve_train_timing_path("D:/x", "alpha158_cost_kdj_lgb", "ridge", "20260915T133000Z")
    b = resolve_train_timing_path("D:/x", "alpha158_cost_kdj_lgb", "lasso", "20260915T133000Z")
    assert a.name == "timing_alpha158_cost_kdj_lgb_ridge_20260915T133000Z.json"
    assert b.name == "timing_alpha158_cost_kdj_lgb_lasso_20260915T133000Z.json"
    assert a != b
    yaml = resolve_train_timing_path("D:/x", "exp", "configs/models/tcn.yaml", "20260916T000000Z")
    assert yaml.name == "timing_exp_tcn_20260916T000000Z.json"


def test_extract_portana_metrics_named_cells():
    import pandas as pd

    idx = pd.MultiIndex.from_tuples(
        [
            ("excess_return_with_cost", "annualized_return"),
            ("excess_return_with_cost", "information_ratio"),
            ("excess_return_with_cost", "max_drawdown"),
            ("excess_return_without_cost", "annualized_return"),
            ("excess_return_without_cost", "information_ratio"),
            ("excess_return_without_cost", "max_drawdown"),
        ]
    )
    df = pd.DataFrame({"risk": [0.118, 0.55, -0.20, 0.20, 0.8, -0.15]}, index=idx)
    got = extract_portana_metrics(df)
    assert abs(got["excess_ann_with_cost"] - 0.118) < 1e-9
    assert abs(got["excess_ir_with_cost"] - 0.55) < 1e-9
    assert abs(got["excess_mdd_with_cost"] + 0.20) < 1e-9
    assert abs(got["excess_ann_without_cost"] - 0.20) < 1e-9
    empty = extract_portana_metrics(None)
    assert empty == {}
