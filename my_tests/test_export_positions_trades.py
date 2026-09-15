# -*- coding: utf-8 -*-
"""盘后分析包：持仓/成交/流水账/荐股（不触发 qlib.init / 回测）。"""

from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace

import pandas as pd

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from analysis_export import (  # noqa: E402
    attach_portfolio_context,
    daily_picks_frame,
    filter_positions_by_window,
    ledger_frame,
    pnl_from_ledger,
    positions_frame,
    pred_score_frame,
    trades_frame,
    write_analysis_bundle,
)
from export_positions_trades import parse_cli  # noqa: E402
from train_wiring import parse_train_cli  # noqa: E402


def _pos(cash, total, stocks):
    body = {"cash": cash, "now_account_value": total}
    body.update(stocks)
    return SimpleNamespace(position=body)


def _book():
    """3 日两只股票：D1 买 A，D2 持 A 买 B，D3 清 A 持 B。"""
    d1 = pd.Timestamp("2026-03-02")
    d2 = pd.Timestamp("2026-03-03")
    d3 = pd.Timestamp("2026-03-04")
    return {
        d1: _pos(8995, 9995, {"SH600000": {"amount": 100, "price": 10.0}}),
        d2: _pos(
            7990,
            10090,
            {
                "SH600000": {"amount": 100, "price": 11.0},
                "SZ000001": {"amount": 50, "price": 20.0},
            },
        ),
        d3: _pos(9185, 10235, {"SZ000001": {"amount": 50, "price": 21.0}}),
    }


def test_positions_and_trades_diff():
    pos_df, snapshots = positions_frame(_book())
    assert list(pos_df["instrument"]) == ["SH600000", "SH600000", "SZ000001", "SZ000001"]
    assert list(pos_df["holding_days"]) == [1, 2, 1, 2]
    assert list(pos_df["bought_today"]) == [True, False, True, False]

    trades = trades_frame(snapshots, open_rate=0.001, close_rate=0.002, min_cost=5.0)
    assert list(trades["side"]) == ["buy", "buy", "sell"]
    assert list(trades["instrument"]) == ["SH600000", "SZ000001", "SH600000"]
    sell = trades[trades["side"] == "sell"].iloc[0]
    # 清仓当日 snapshot 无该股，无 close_of 时退回前日价 11
    assert sell["price"] == 11.0
    assert sell["delta_amount"] == 100
    assert sell["est_cost"] == 5.0


def test_ledger_average_cost_and_pnl():
    _, snapshots = positions_frame(_book())

    def close_of(inst, day):
        if inst == "SH600000" and pd.Timestamp(day) == pd.Timestamp("2026-03-04"):
            return 12.0
        return None

    led = ledger_frame(snapshots, 0.001, 0.002, min_cost=5.0, close_of=close_of)
    a = led[led["instrument"] == "SH600000"]
    assert list(a["event"]) == ["buy", "hold", "sell"]
    sell = a[a["event"] == "sell"].iloc[0]
    assert sell["price"] == 12.0
    assert sell["amount_after"] == 0.0
    # 100*(12-10) - 卖费5 - 摊回买费5
    assert abs(sell["realized_pnl"] - 190.0) < 1e-9
    assert abs(sell["cum_realized_pnl"] - 190.0) < 1e-9

    b = led[led["instrument"] == "SZ000001"]
    last = b.iloc[-1]
    assert last["event"] == "hold"
    assert abs(last["unrealized_pnl"] - 45.0) < 1e-9  # 50*(21-20)-5

    pnl = pnl_from_ledger(led)
    by = pnl.set_index("instrument")
    assert abs(by.loc["SH600000", "realized_pnl"] - 190.0) < 1e-9
    assert not bool(by.loc["SH600000", "still_held"])
    assert abs(by.loc["SZ000001", "unrealized_pnl"] - 45.0) < 1e-9
    assert bool(by.loc["SZ000001", "still_held"])
    assert abs(float(pnl["total_pnl"].sum()) - 235.0) < 1e-9


def test_daily_picks_minus_one_vs_held():
    _, snapshots = positions_frame(_book())
    pred = pd.DataFrame(
        {
            "datetime": ["2026-03-02"] * 3 + ["2026-03-03"] * 3,
            "instrument": ["SZ000002", "SH600000", "SZ000001"] * 2,
            "score": [3.0, 2.0, 1.0, 0.5, 2.0, 3.0],
        }
    )
    picks = daily_picks_frame(pred, snapshots, topk=2, asof="pred_minus_one")
    day = picks[picks["trade_date"] == "2026-03-03"]
    actions = dict(zip(day["instrument"], day["action"]))
    assert actions["SH600000"] == "held"
    assert actions["SZ000002"] == "missed"
    assert actions["SZ000001"] == "held_not_topk"
    assert set(day.loc[day["action"] == "held_not_topk", "instrument"]) == {"SZ000001"}


def test_daily_picks_identity_new_buy():
    _, snapshots = positions_frame(_book())
    pred = pd.DataFrame(
        {
            "datetime": ["2026-03-02", "2026-03-02"],
            "instrument": ["SZ000002", "SH600000"],
            "score": [3.0, 2.0],
        }
    )
    picks = daily_picks_frame(pred, snapshots, topk=2, asof="identity")
    day = picks[picks["trade_date"] == "2026-03-02"]
    actions = dict(zip(day["instrument"], day["action"]))
    assert actions["SH600000"] == "new_buy"
    assert actions["SZ000002"] == "missed"


def test_write_bundle_and_window_filter(tmp_path):
    book = _book()
    clipped = filter_positions_by_window(book, "2026-03-03", "2026-03-04")
    assert len(clipped) == 2

    pred = pd.DataFrame(
        {
            "datetime": ["2026-03-02", "2026-03-02", "2026-03-03", "2026-03-03"],
            "instrument": ["SH600000", "SZ000001", "SH600000", "SZ000001"],
            "score": [2.0, 1.0, 1.0, 2.0],
        }
    )
    report = pd.DataFrame(
        {"account": [9995.0, 10090.0, 10235.0], "return": [0.0, 0.01, 0.01]},
        index=pd.to_datetime(["2026-03-02", "2026-03-03", "2026-03-04"]),
    )
    bundle = write_analysis_bundle(
        positions=book,
        out_dir=tmp_path / "rid1",
        open_rate=0.001,
        close_rate=0.002,
        account=10000.0,
        pred=pred,
        report=report,
        topk=1,
    )
    for name in (
        "positions_daily",
        "trades_daily",
        "ledger_by_stock",
        "pnl_by_stock",
        "daily_picks",
        "nav_daily",
        "summary",
    ):
        assert name in bundle["paths"]
        assert os.path.isfile(bundle["paths"][name])
    summary = json.loads((tmp_path / "rid1" / "summary.json").read_text(encoding="utf-8"))
    assert summary["days"] == 3
    assert summary["buys"] == 2
    assert summary["sells"] == 1
    assert summary["files"]["ledger_by_stock"] == "ledger_by_stock.csv"
    nav = pd.read_csv(bundle["paths"]["nav_daily"])
    assert list(nav["date"]) == ["2026-03-02", "2026-03-03", "2026-03-04"]

    pos_df, _ = positions_frame(book)
    led = attach_portfolio_context(
        ledger_frame(positions_frame(book)[1], 0.001, 0.002, min_cost=5.0),
        pos_df,
    )
    held_row = led[(led["instrument"] == "SH600000") & (led["event"] == "hold")].iloc[0]
    assert held_row["cash"] == 7990
    assert held_row["total_value"] == 10090


def test_pred_score_frame_series_and_cli_defaults():
    idx = pd.MultiIndex.from_product(
        [pd.to_datetime(["2026-03-02"]), ["SH600000"]],
        names=["datetime", "instrument"],
    )
    series = pd.Series([0.4], index=idx, name="score")
    frame = pred_score_frame(series)
    assert list(frame.columns) == ["datetime", "instrument", "score"]
    assert frame["score"].iloc[0] == 0.4

    args = parse_cli(["--recorder-id", "abc"])
    assert args.replay is False
    assert args.test is None
    replay = parse_cli(["--recorder-id", "abc", "--replay", "--test", "2026-01-01:2026-03-01"])
    assert replay.replay is True
    assert replay.test == "2026-01-01:2026-03-01"

    train = parse_train_cli([])
    assert train.no_export_analysis is False
    assert parse_train_cli(["--no-export-analysis"]).no_export_analysis is True
