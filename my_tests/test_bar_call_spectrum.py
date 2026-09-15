"""eng-perf P1-6: always-on bar call-spectrum counters (measure-only)."""

from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)


class _Infra:
    def __init__(self, **kwargs):
        self._d = kwargs

    def get(self, key):
        return self._d.get(key)


def _mock_exchange():
    ex = MagicMock()
    ex.is_stock_tradable.return_value = True
    ex.get_deal_price.return_value = 10.0
    ex.get_factor.return_value = 1.0
    ex.round_amount_by_trade_unit.side_effect = lambda amount, factor: amount
    ex.check_order.return_value = True
    ex.deal_order.return_value = (0.0, 0.0, 10.0)
    return ex


def _bare_strategy(*, timing_interval_steps: int = 10, only_tradable: bool = False):
    from custom_strategy import TopkDropoutStrategyWithFilter
    from qlib.backtest.position import Position

    strat = TopkDropoutStrategyWithFilter.__new__(TopkDropoutStrategyWithFilter)
    strat.max_return_threshold = 0.15
    strat.lookback_days = 5
    strat.timing_interval_steps = timing_interval_steps
    strat._close_wide = None
    strat._bar_close_scratch = None
    strat.df_calls = 0
    strat.tradable_calls = 0
    strat.deal_price_calls = 0
    strat.factor_calls = 0
    strat.cache_hit = 0
    strat.n_stocks = 0
    strat.logger = MagicMock()
    strat._trade_exchange = _mock_exchange()
    strat.only_tradable = only_tradable
    strat.method_buy = "top"
    strat.method_sell = "bottom"
    strat.topk = 2
    strat.n_drop = 1
    strat.hold_thresh = 1
    strat.risk_degree = 0.95
    strat.forbid_all_trade_at_limit = True
    strat.signal = MagicMock()
    scores = pd.Series(
        {
            "SH600000": 0.9,
            "SZ000001": 0.8,
            "SH600519": 0.7,
            "SZ000002": 0.6,
            "SH601318": 0.5,
        }
    )
    strat.signal.get_signal.return_value = scores
    strat._step = 0

    cal = MagicMock()

    def _trade_step():
        return strat._step

    def _step_time(step=None, shift=0):
        if step is None:
            step = strat._step
        day = 10 + int(step) - int(shift)
        # Keep day in 01..28 for Timestamp safety across multi-step loops.
        day = ((day - 1) % 28) + 1
        ts = pd.Timestamp(f"2026-01-{day:02d}")
        return ts, ts

    cal.get_trade_step.side_effect = _trade_step
    cal.get_step_time.side_effect = _step_time
    cal.get_freq.return_value = "day"
    strat.level_infra = _Infra(trade_calendar=cal)
    pos = Position(cash=1_000_000.0)
    strat.common_infra = _Infra(trade_account=SimpleNamespace(current_position=pos))

    # Skip return-gate IO in decision-path tests.
    strat._filter_stocks_by_return_threshold = (
        lambda stocks, trade_start_time, initial_required_count: list(stocks)[:initial_required_count]
    )
    return strat


def test_spectrum_dict_and_reset():
    strat = _bare_strategy()
    strat.df_calls = 2
    strat.tradable_calls = 3
    strat.deal_price_calls = 4
    strat.factor_calls = 5
    strat.cache_hit = 1
    strat.n_stocks = 9
    spec = strat.bar_call_spectrum()
    assert spec == {
        "df_calls": 2,
        "tradable_calls": 3,
        "deal_price_calls": 4,
        "factor_calls": 5,
        "cache_hit": 1,
        "n_stocks": 9,
        "timing_interval_steps": 10,
    }
    json.dumps(spec)
    strat.reset_bar_call_spectrum()
    z = strat.bar_call_spectrum()
    assert z["df_calls"] == 0
    assert z["tradable_calls"] == 0
    assert z["deal_price_calls"] == 0
    assert z["factor_calls"] == 0
    assert z["cache_hit"] == 0
    assert z["n_stocks"] == 0
    assert z["timing_interval_steps"] == 10


def test_exchange_wrappers_increment():
    strat = _bare_strategy()
    assert strat._ex_is_stock_tradable(stock_id="SH600000") is True
    assert strat.tradable_calls == 1
    assert strat._ex_get_deal_price(stock_id="SH600000") == 10.0
    assert strat.deal_price_calls == 1
    assert strat._ex_get_factor(stock_id="SH600000") == 1.0
    assert strat.factor_calls == 1
    strat.trade_exchange.is_stock_tradable.assert_called_once()
    strat.trade_exchange.get_deal_price.assert_called_once()
    strat.trade_exchange.get_factor.assert_called_once()


def test_generate_trade_decision_counts_grow_across_steps():
    strat = _bare_strategy(timing_interval_steps=10, only_tradable=False)
    before = strat.bar_call_spectrum()
    for step in range(3):
        strat._step = step
        decision = strat.generate_trade_decision()
        assert decision is not None
    after = strat.bar_call_spectrum()
    assert after["tradable_calls"] > before["tradable_calls"]
    assert after["deal_price_calls"] > before["deal_price_calls"]
    assert after["factor_calls"] > before["factor_calls"]
    assert after["deal_price_calls"] >= 3
    assert after["factor_calls"] >= 3
    assert after["tradable_calls"] >= 3


def test_always_on_counts_while_timer_respects_interval():
    """timing_interval_steps=10: spectrum still rises every bar; Timer only on %10."""
    from custom_utils import TimerRecorder, set_global_timer_recorder

    rec = TimerRecorder()
    set_global_timer_recorder(rec)
    try:
        strat = _bare_strategy(timing_interval_steps=10, only_tradable=False)
        counts = []
        for step in range(12):
            strat._step = step
            strat.generate_trade_decision()
            counts.append(strat.bar_call_spectrum())
        assert counts[0]["deal_price_calls"] > 0
        assert counts[11]["deal_price_calls"] > counts[0]["deal_price_calls"]
        assert counts[5]["tradable_calls"] > counts[0]["tradable_calls"]
        signal_nodes = [n for n in rec.nodes if n["name"] == "strategy.signal.get_signal"]
        assert len(signal_nodes) == 2
    finally:
        set_global_timer_recorder(None)


def test_oskh_bar_spectrum_stdout(capsys, monkeypatch):
    monkeypatch.setenv("OSKH_BAR_SPECTRUM", "1")
    strat = _bare_strategy(timing_interval_steps=10, only_tradable=False)
    strat._step = 3  # not a sample step; env still forces print
    strat.generate_trade_decision()
    out = capsys.readouterr().out
    assert "BAR_SPECTRUM step=3" in out
    assert "tradable_calls" in out


def test_cli_timing_interval_steps_help():
    from train_wiring import parse_train_cli

    args = parse_train_cli([])
    assert args.timing_interval_steps == 10
    args1 = parse_train_cli(["--timing-interval-steps", "1"])
    assert args1.timing_interval_steps == 1
