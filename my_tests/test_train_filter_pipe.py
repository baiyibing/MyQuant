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
    build_filtered_instruments,
    build_limit_up_filter,
    build_production_filter_pipe,
    parse_train_cli,
    should_verify_filters,
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
