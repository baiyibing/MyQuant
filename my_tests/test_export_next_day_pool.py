# -*- coding: utf-8 -*-
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from export_next_day_pool import (
    load_pred_csv,
    next_calendar_date,
    parse_cli,
    plan_rebalance,
    score_frame,
    write_suite,
)


def test_cli_defaults_lock_live_50n5_st_age():
    args = parse_cli([])
    assert args.topk == 50
    assert args.n_drop == 5
    assert args.st_filter is True
    assert args.age_filter is True
    assert args.skip_predict is False
    assert args.recorder_id == "8a061ea428e04bb3a199a485ade49d0e"


def test_cli_can_turn_gates_off():
    args = parse_cli(["--no-st-filter", "--no-age-filter", "--topk", "10", "--n-drop", "3"])
    assert args.st_filter is False
    assert args.age_filter is False
    assert args.topk == 10
    assert args.n_drop == 3


def test_skip_predict_without_csv_exits_before_qlib():
    from export_next_day_pool import main

    with pytest.raises(SystemExit, match="--pred-csv"):
        main(["--skip-predict"])


def test_next_calendar_date_uses_next_session():
    cal = ["2026-09-14", "2026-09-15", "2026-09-16"]
    assert next_calendar_date("2026-09-15", cal) == date(2026, 9, 16)


def test_next_calendar_date_skips_weekend_when_calendar_ends():
    assert next_calendar_date("2026-09-11", ["2026-09-11"]) == date(2026, 9, 14)


def test_score_frame_ranks_score_desc_then_instrument():
    pred = pd.Series(
        [0.2, 0.9, 0.9],
        index=pd.MultiIndex.from_tuples(
            [
                ("2026-09-15", "SZ000002"),
                ("2026-09-15", "SZ000001"),
                ("2026-09-15", "SH600000"),
            ],
            names=["datetime", "instrument"],
        ),
        name="score",
    )
    out = score_frame(pred)
    assert out["instrument"].tolist() == ["SH600000", "SZ000001", "SZ000002"]
    assert out["raw_rank"].tolist() == [1, 2, 3]


def test_load_pred_csv_accepts_plain_score_table(tmp_path: Path):
    path = tmp_path / "pred.csv"
    path.write_text(
        "datetime,instrument,score\n"
        "2026-09-15,SZ000002,0.1\n"
        "2026-09-15,SH600000,0.3\n",
        encoding="utf-8",
    )
    out = load_pred_csv(path)
    assert out["instrument"].tolist() == ["SH600000", "SZ000002"]
    assert out["raw_rank"].tolist() == [1, 2]


def test_plan_rebalance_drops_weakest_out_of_target():
    held = pd.DataFrame(
        {
            "instrument": ["AAA", "BBB", "CCC", "DDD", "EEE"],
            "holding_days": [2, 3, 4, 5, 6],
        }
    )
    ranked = pd.DataFrame(
        {
            "instrument": ["AAA", "FFF", "GGG", "EEE", "BBB", "DDD", "CCC"],
            "score": [10.0, 9.0, 8.0, 4.0, 3.0, 2.0, 1.0],
            "raw_rank": [1, 2, 3, 4, 5, 6, 7],
        }
    )
    target = pd.DataFrame(
        {
            "buy_date": ["2026-09-16"] * 3,
            "pred_date": ["2026-09-15"] * 3,
            "instrument": ["AAA", "FFF", "GGG"],
            "score": [10.0, 9.0, 8.0],
            "buy_rank": [1, 2, 3],
        }
    )

    parts = plan_rebalance(held, target, ranked, n_drop=1)

    assert parts["new_buy"]["instrument"].tolist() == ["FFF", "GGG"]
    assert parts["sell"]["instrument"].tolist() == ["CCC"]
    assert set(parts["hold"]["instrument"]) == {"AAA", "BBB", "DDD", "EEE"}
    actions = dict(zip(parts["daily_picks"]["instrument"], parts["daily_picks"]["action"]))
    assert actions["FFF"] == "new_buy"
    assert actions["AAA"] == "held"
    assert actions["BBB"] == "held_not_topk"
    assert actions["CCC"] == "plan_sell"


def test_write_suite_emits_csv_and_meta(tmp_path: Path):
    ranked = pd.DataFrame(
        {
            "instrument": ["AAA", "BBB", "ST1"],
            "score": [3.0, 2.0, 1.0],
            "raw_rank": [1, 2, 3],
            "eligible": [True, True, False],
        }
    )
    target = pd.DataFrame(
        {
            "buy_date": ["2026-09-16", "2026-09-16"],
            "pred_date": ["2026-09-15", "2026-09-15"],
            "instrument": ["AAA", "BBB"],
            "score": [3.0, 2.0],
            "buy_rank": [1, 2],
        }
    )
    held = pd.DataFrame({"instrument": ["AAA", "CCC"], "holding_days": [5, 2]})
    ranked_full = pd.concat(
        [
            ranked,
            pd.DataFrame(
                {"instrument": ["CCC"], "score": [0.1], "raw_rank": [4], "eligible": [True]}
            ),
        ],
        ignore_index=True,
    )
    meta = write_suite(
        tmp_path,
        ranked=ranked_full,
        target=target,
        held=held,
        n_drop=1,
        meta={"buy_date": "2026-09-16"},
    )
    assert (tmp_path / "new_buy.csv").is_file()
    assert (tmp_path / "hold.csv").is_file()
    assert (tmp_path / "sell.csv").is_file()
    assert (tmp_path / "daily_picks.csv").is_file()
    assert (tmp_path / "suite.meta.json").is_file()
    assert meta["new_buy"] == 1
    assert meta["plan_sell"] == 1
    assert meta["blocked_in_raw_top80"] == 1
    assert pd.read_csv(tmp_path / "new_buy.csv")["instrument"].tolist() == ["BBB"]
    assert pd.read_csv(tmp_path / "sell.csv")["instrument"].tolist() == ["CCC"]
