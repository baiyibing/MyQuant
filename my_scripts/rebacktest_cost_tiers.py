"""成本敏感性重回测：复用已训练 recorder 的 pred.pkl，不重训。

一次训练 → 三档成本各回测一遍（零成本 / qlib 默认 / 现实含滑点），
并自算全市场等权基准，输出双基准超额对比。产出为普通结果 JSON
（非 run-manifest——schema 的 stage 枚举只收 train/export/refresh）。

用法（在 my_scripts 目录下，Phase 1 跑完之后）::

    python rebacktest_cost_tiers.py --recorder-id <manifest 里的 recorder_id> \
        --test 2026-01-01:2026-09-08

不传 --recorder-id 时取该实验最近一次 recorder（打印 id 供与 manifest 核对）。
"""

import argparse
import json
import multiprocessing
import os
from datetime import datetime, timezone

# 共享 mlflow 逃生口 / 静音（须在任何 qlib import 之前）
import host_env  # noqa: F401

import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.contrib.evaluate import backtest_daily, risk_analysis
from qlib.data import D
from qlib.workflow import R

from custom_ops import SMA
from train_wiring import parse_segment

# 三档成本（open_cost=买入费率，close_cost=卖出费率含印花）。
# realistic ≈ 佣金 0.03% 双边 + 印花 0.05% 卖出 + 滑点约 0.05~0.1%，方向性校准用，非精确。
COST_TIERS = {
    "zero": {"open_cost": 0.0, "close_cost": 0.0},
    "qlib_default": {"open_cost": 0.0005, "close_cost": 0.0015},
    "realistic": {"open_cost": 0.001, "close_cost": 0.002},
}

EXECUTOR_CONFIG = {
    "class": "SimulatorExecutor",
    "module_path": "qlib.backtest.executor",
    "kwargs": {"time_per_step": "day", "generate_portfolio_metrics": True},
}


def build_exchange_kwargs(tier_costs: dict, no_limit_threshold: bool = False) -> dict:
    """与主线 custom_train_backtest 的 exchange 同构，只差成本两档参数。

    no_limit_threshold=True（--no-limit-threshold）时 limit_threshold 置 None：
    涨停可买、跌停可卖，与主线的执行端开关同语义。
    """
    return {
        "freq": "day",
        "limit_threshold": None if no_limit_threshold else 0.095,  # 近似涨跌停不可成交
        "deal_price": "close",
        "min_cost": 5,
        **tier_costs,
    }


def equal_weight_daily_returns(start_time: str, end_time: str) -> pd.Series:
    """全市场等权日收益：$close/Ref($close,1)-1 的逐日横截面均值。

    与 report_normal_df["return"] 同口径（t 日持有期收益）；
    停牌/上市首日缺前收的股票当日自动缺权（mean 跳过 NaN）。
    """
    instruments = D.instruments(market="all", start_time=start_time, end_time=end_time)
    codes = D.list_instruments(instruments, start_time=start_time, end_time=end_time, as_list=True)
    print(f"[rebacktest] equal-weight universe: {len(codes)} instruments", flush=True)
    df = D.features(codes, ["$close/Ref($close,1)-1"], start_time=start_time, end_time=end_time)
    df.columns = ["ret"]
    return df.groupby(level="datetime")["ret"].mean()


def metrics(returns: pd.Series) -> dict:
    row = risk_analysis(returns)["risk"]
    return {
        "mean": float(row["mean"]),
        "std": float(row["std"]),
        "annualized_return": float(row["annualized_return"]),
        "information_ratio": float(row["information_ratio"]),
        "max_drawdown": float(row["max_drawdown"]),
    }


def load_pred(exp_name: str, recorder_id: str | None):
    if recorder_id:
        recorder = R.get_recorder(recorder_id=recorder_id, experiment_name=exp_name)
    else:
        recorder = R.get_recorder(experiment_name=exp_name)
        print(f"[rebacktest] --recorder-id 未给，取最近 recorder: {recorder.id}（请与 manifest 核对）")
    pred = recorder.load_object("pred.pkl")
    print(f"[rebacktest] recorder={recorder.id} pred rows={len(pred)}", flush=True)
    return recorder, pred


def run_tiers(args) -> dict:
    pred_score = args.pred_score
    start_time, end_time = args.test_window

    ew = equal_weight_daily_returns(start_time, end_time)

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

    summary = {
        "exp_name": args.exp_name,
        "recorder_id": args.recorder_id,
        "test": list(args.test_window),
        "benchmark": args.benchmark,
        "account": args.account,
        "topk": args.topk,
        "n_drop": args.n_drop,
        "hold_thresh": args.hold_thresh,
        "limit_threshold": None if args.no_limit_threshold else 0.095,
        # qlib report["return"] 列是加回成本的毛收益（account.py: return_rate=(earning+cost)/last_value），
        # 净收益 = return - cost；三档毛收益几乎相同（决策不看成本），差异全在 cost 列
        "note": "abs_net=return-cost（真净值口径）；gross=return（未扣费）；成本拖累单列",
        "tiers": {},
    }
    for tier, costs in COST_TIERS.items():
        print(f"[rebacktest] tier={tier} costs={costs} backtesting ...", flush=True)
        report, _positions = backtest_daily(
            start_time=start_time,
            end_time=end_time,
            strategy=strategy_config,
            executor=EXECUTOR_CONFIG,
            account=args.account,
            benchmark=args.benchmark,
            exchange_kwargs=build_exchange_kwargs(costs, no_limit_threshold=args.no_limit_threshold),
        )
        net = report["return"] - report["cost"]
        ew_aligned = ew.reindex(report.index)
        summary["tiers"][tier] = {
            "abs_net_after_cost": metrics(net),
            "abs_gross_before_cost": metrics(report["return"]),
            "excess_vs_bench_net": metrics(net - report["bench"]),
            "excess_vs_equal_weight_net": metrics(net - ew_aligned),
            "annualized_cost_drag": float(report["cost"].mean() * 252),
            "total_cost_rate": float(report["cost"].sum()),
            "total_turnover": float(report["turnover"].sum()),
            "trading_days": int(len(report)),
        }
        print(json.dumps(summary["tiers"][tier], indent=2, ensure_ascii=False), flush=True)
    return summary


def parse_cli(argv=None):
    parser = argparse.ArgumentParser(description="成本敏感性重回测（复用 pred.pkl，不重训）")
    parser.add_argument("--exp-name", default="alpha158_cost_kdj_lgb")
    parser.add_argument("--recorder-id", default=None, help="train manifest 里的 recorder_id；缺省取实验最近一次")
    parser.add_argument("--test", required=True, help="回测窗 START:END（YYYY-MM-DD:YYYY-MM-DD）")
    parser.add_argument("--benchmark", default="SH000300")
    parser.add_argument("--account", type=float, default=1e8)
    parser.add_argument("--topk", type=int, default=10)
    parser.add_argument("--n-drop", dest="n_drop", type=int, default=3)
    parser.add_argument("--hold-thresh", dest="hold_thresh", type=int, default=1)
    parser.add_argument(
        "--no-limit-threshold",
        action="store_true",
        help="关掉执行端涨跌停拒单（limit_threshold=None）：涨停可买、跌停可卖。默认 0.095 拒单。",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    multiprocessing.freeze_support()  # Windows spawn 惯例
    args = parse_cli()

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
    _recorder, pred = load_pred(args.exp_name, args.recorder_id)
    args.recorder_id = _recorder.id
    args.pred_score = pred["score"] if isinstance(pred, pd.DataFrame) else pred

    summary = run_tiers(args)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary_path = os.path.abspath(f"rebacktest_cost_tiers_summary_{stamp}.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"=== Rebacktest summary saved: {summary_path} ===")
