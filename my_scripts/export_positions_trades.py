"""导出回测逐日持仓与买卖记录（复用已训练 recorder 的 pred.pkl，不重训）。

与 rebacktest_cost_tiers.py 同构：同样的 TopkDropout 回测一次，但不丢 positions，
从 hist_positions 展开三样东西：

1. positions_daily_<tag>.csv —— 逐日持仓快照（收盘后，含当日成交）：
   date / instrument / holding_days（qlib Position.count，连续持有交易日数）/
   amount / price / value / weight / cash
2. trades_daily_<tag>.csv —— 买卖记录（相邻两日 amount 差分，精度为整笔持仓变动）：
   date / instrument / side(buy|sell) / delta_amount / price / value / est_cost
   （est_cost = max(value×费率, 5)，费率取所选成本档；价格取成交当日收盘）
3. export run-manifest（stage=export，记 config 与产出文件数）

用法（在 my_scripts 目录下）::

    python export_positions_trades.py --recorder-id <id> --test 2026-01-01:2026-09-08 \
        [--no-limit-threshold] [--cost-tier realistic] [--tag noguards]

注意：买卖由持仓差分推得。TopkDropout 按整笔调仓，差分即逐笔成交；
若某笔当日买+卖对冲（本策略不会），差分只能看到净额。
"""

import argparse
import multiprocessing
import os
from datetime import datetime, timezone

# 共享 mlflow 逃生口 / 静音（须在任何 qlib import 之前）
import host_env  # noqa: F401

import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.contrib.evaluate import backtest_daily
from qlib.workflow import R

from custom_ops import SMA
from rebacktest_cost_tiers import (
    COST_TIERS,
    EXECUTOR_CONFIG,
    build_exchange_kwargs,
    load_pred,
)
from run_manifest import capture_git_provenance, write_export_manifest
from train_wiring import parse_segment


_POSITION_SPECIAL_KEYS = {"cash", "now_account_value", "cash_delay"}


def positions_frame(positions: dict) -> tuple[pd.DataFrame, dict]:
    """hist_positions → 逐日持仓 DataFrame + {date: {inst: (amount, price, count)}} 快照。

    Position.position 混装：{stock_id: {amount/price/count/...}, 'cash': f, 'now_account_value': f}。
    股票键 = 全部键 - 特殊键（与 qlib Position.get_stock_list 同口径）。
    """
    rows = []
    snapshots = {}
    streak = {}  # inst -> 连续持有交易日数（当日买入=1；中断重置）
    for day in sorted(positions.keys()):
        pdict = dict(getattr(positions[day], "position", {}) or {})
        cash = float(pdict.get("cash", 0.0) or 0.0) + float(pdict.get("cash_delay", 0.0) or 0.0)
        stock_items = {k: v for k, v in pdict.items() if k not in _POSITION_SPECIAL_KEYS}
        total = float(pdict.get("now_account_value", 0.0) or 0.0)
        if total <= 0:
            total = cash + sum(
                float(item.get("amount", 0)) * float(item.get("price", 0.0) or 0.0)
                for item in stock_items.values()
                if isinstance(item, dict)
            )
        day_snap = {}
        for inst in stock_items:
            streak[inst] = streak.get(inst, 0) + 1
        streak = {k: v for k, v in streak.items() if k in stock_items}
        for inst, item in stock_items.items():
            if not isinstance(item, dict):
                item = {"amount": item}
            amount = float(item.get("amount", 0))
            price = float(item.get("price", 0.0) or 0.0)
            value = amount * price
            day_snap[inst] = (amount, price, streak[inst])
            rows.append(
                {
                    "date": pd.Timestamp(day).date().isoformat(),
                    "instrument": inst,
                    "holding_days": streak[inst],
                    "bought_today": streak[inst] == 1,
                    "amount": amount,
                    "price": price,
                    "value": value,
                    "weight": (value / total) if total > 0 else None,
                    "cash": cash,
                    "total_value": total,
                }
            )
        snapshots[pd.Timestamp(day)] = day_snap
    return pd.DataFrame(rows), snapshots


def trades_frame(snapshots: dict, tier: str) -> pd.DataFrame:
    """相邻交易日 amount 差分 → 买卖记录。"""
    open_rate = COST_TIERS[tier]["open_cost"]
    close_rate = COST_TIERS[tier]["close_cost"]
    rows = []
    days = sorted(snapshots.keys())
    prev = {}
    for day in days:
        cur = snapshots[day]
        for inst in sorted(set(prev) | set(cur)):
            cur_amt = cur.get(inst, (0.0,))[0]
            prev_amt = prev.get(inst, (0.0,))[0]
            delta = cur_amt - prev_amt
            if abs(delta) < 1e-9:
                continue
            side = "buy" if delta > 0 else "sell"
            # 成交价：买入/减仓取当日价；清仓卖出当日已无报价，取前一日持仓价
            price = cur.get(inst, (0.0, prev.get(inst, (0.0, 0.0, 0))[1]))[1]
            value = abs(delta) * price
            rate = open_rate if side == "buy" else close_rate
            # 持有天数：卖出=本次连续持有了几天（前一日快照的 streak）；买入=1（新开仓）
            held = prev.get(inst, (0.0, 0.0, 0))[2] if side == "sell" else 1
            rows.append(
                {
                    "date": day.date().isoformat(),
                    "instrument": inst,
                    "side": side,
                    "delta_amount": abs(delta),
                    "price": price,
                    "value": value,
                    "est_cost": max(value * rate, 5.0) if value > 0 else 0.0,
                    "held_days": held,
                }
            )
        prev = cur
    return pd.DataFrame(rows)


def parse_cli(argv=None):
    parser = argparse.ArgumentParser(description="导出回测逐日持仓/买卖记录（复用 pred.pkl，不重训）")
    parser.add_argument("--exp-name", default="alpha158_cost_kdj_lgb")
    parser.add_argument("--recorder-id", default=None, help="train manifest 里的 recorder_id；缺省取实验最近一次")
    parser.add_argument("--test", required=True, help="回测窗 START:END（YYYY-MM-DD:YYYY-MM-DD）")
    parser.add_argument("--benchmark", default="SH000300")
    parser.add_argument("--account", type=float, default=1e8)
    parser.add_argument("--topk", type=int, default=10)
    parser.add_argument("--n-drop", dest="n_drop", type=int, default=3)
    parser.add_argument("--hold-thresh", dest="hold_thresh", type=int, default=1)
    parser.add_argument("--no-limit-threshold", action="store_true", help="与训练侧同语义：limit_threshold=None")
    parser.add_argument("--cost-tier", choices=sorted(COST_TIERS), default="qlib_default")
    parser.add_argument("--tag", default=None, help="输出文件名后缀；默认 guards{on|off}_<cost-tier>")
    parser.add_argument("--out-dir", default="exports")
    return parser.parse_args(argv)


def main():
    args = parse_cli()
    tag = args.tag or f"guards{'off' if args.no_limit_threshold else 'on'}_{args.cost_tier}"

    print(qlib.__version__)
    qlib.init(
        provider_uri="~/.qlib/qlib_data/my_data",
        region=REG_CN,
        kernels=16,
        redis_host="127.0.0.1",
        redis_port=6379,
        redis_password="123456",
        redis_task_db=1,
        custom_ops=[SMA],
        exp_manager={
            "class": "MLflowExpManager",
            "module_path": "qlib.workflow.expm",
            "kwargs": {"uri": "mlruns", "default_exp_name": "MyExperiment"},
        },
        logging_level=__import__("logging").INFO,
    )

    args.test_window = parse_segment(args.test, "test")
    recorder, pred = load_pred(args.exp_name, args.recorder_id)
    pred_score = pred["score"] if isinstance(pred, pd.DataFrame) else pred

    strategy_config = {
        "class": "TopkDropoutStrategy",
        "module_path": "qlib.contrib.strategy.signal_strategy",
        "kwargs": {
            "signal": pred_score,
            "topk": args.topk,
            "n_drop": args.n_drop,
            "hold_thresh": args.hold_thresh,
        },
    }
    print(f"[export] backtesting for positions (tier={args.cost_tier}) ...", flush=True)
    report, positions = backtest_daily(
        start_time=args.test_window[0],
        end_time=args.test_window[1],
        strategy=strategy_config,
        executor=EXECUTOR_CONFIG,
        account=args.account,
        benchmark=args.benchmark,
        exchange_kwargs=build_exchange_kwargs(
            COST_TIERS[args.cost_tier], no_limit_threshold=args.no_limit_threshold
        ),
    )

    pos_df, snapshots = positions_frame(positions)
    trd_df = trades_frame(snapshots, args.cost_tier)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    pos_path = os.path.join(out_dir, f"positions_daily_{tag}_{stamp}.csv")
    trd_path = os.path.join(out_dir, f"trades_daily_{tag}_{stamp}.csv")
    pos_df.to_csv(pos_path, index=False, encoding="utf-8-sig")
    trd_df.to_csv(trd_path, index=False, encoding="utf-8-sig")

    n_days = len(snapshots)
    buys = int((trd_df["side"] == "buy").sum()) if len(trd_df) else 0
    sells = int((trd_df["side"] == "sell").sum()) if len(trd_df) else 0
    avg_hold = pos_df["holding_days"].mean() if len(pos_df) else float("nan")
    print(
        f"[export] days={n_days} position_rows={len(pos_df)} trades={len(trd_df)} "
        f"(buy={buys} sell={sells}) avg_holding_days={avg_hold:.2f}",
        flush=True,
    )
    print(f"=== Positions saved: {pos_path} ===")
    print(f"=== Trades saved: {trd_path} ===")

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    try:
        write_export_manifest(
            manifests_dir=os.path.join(base_dir, "manifests"),
            config={
                "kind": "positions_trades",
                "exp_name": args.exp_name,
                "recorder_id": recorder.id,
                "test": list(args.test_window),
                "benchmark": args.benchmark,
                "account": args.account,
                "topk": args.topk,
                "n_drop": args.n_drop,
                "hold_thresh": args.hold_thresh,
                "cost_tier": args.cost_tier,
                "limit_threshold": None if args.no_limit_threshold else 0.095,
                "positions_rows": int(len(pos_df)),
                "trades_rows": int(len(trd_df)),
            },
            out_dir=out_dir,
            output_file_count=2,
            repo_root=base_dir,
            git_commit_sha=capture_git_provenance(base_dir).get("git_commit"),
        )
    except Exception as exc:  # manifest 失败不拦导出本体
        print(f"[export] manifest skipped: {exc}")


if __name__ == "__main__":
    multiprocessing.freeze_support()  # Windows spawn 惯例
    main()
