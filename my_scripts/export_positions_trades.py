"""导出回测逐日持仓 / 买卖 / 流水账 / 每日荐股（默认不重回测）。

默认 ``--from-recorder``：读 recorder 里 PortAna 已落的
``positions_normal_1day.pkl`` + ``pred.pkl``，只做表展开。
训练收尾也会调同一套 ``analysis_export.write_analysis_bundle``。

只有换成本档 / topk / n_drop / 资格闸门时才加 ``--replay`` 重跑一遍
``backtest_daily``（那才是第二遍，且仍不重训）。

用法（在 my_scripts 目录下）::

    # 与实验当时同一套持仓（推荐，秒级）
    python export_positions_trades.py --recorder-id <id>

    # 换档重放（分钟～小时，视过滤开关）
    python export_positions_trades.py --recorder-id <id> --replay \\
        --test 2026-01-01:2026-09-14 --cost-tier realistic --topk 50
"""

import argparse
import multiprocessing
import os

# 共享 mlflow 逃生口 / 静音（须在任何 qlib import 之前）
import host_env  # noqa: F401

import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.contrib.evaluate import backtest_daily

from analysis_export import (
    filter_positions_by_window,
    print_bundle_summary,
    write_analysis_bundle,
)
from custom_utils import (
    TimerRecorder,
    install_features_probe,
    set_global_timer_recorder,
)
from custom_ops import SMA
from rebacktest_cost_tiers import (
    COST_TIERS,
    EXECUTOR_CONFIG,
    build_exchange_kwargs,
    build_strategy_config,
    load_pred,
)
from run_manifest import capture_git_provenance, write_export_manifest
from train_wiring import parse_segment

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def parse_cli(argv=None):
    parser = argparse.ArgumentParser(
        description="导出持仓/买卖/流水账/荐股。默认从 recorder 提取，不重回测。"
    )
    parser.add_argument("--exp-name", default="alpha158_cost_kdj_lgb")
    parser.add_argument("--recorder-id", default=None, help="train manifest 里的 recorder_id；缺省取实验最近一次")
    parser.add_argument(
        "--test",
        default=None,
        help="窗 START:END。--replay 必填；提取模式可选（裁剪已落盘持仓的日期）",
    )
    parser.add_argument("--benchmark", default="SH000300")
    parser.add_argument("--account", type=float, default=1e8)
    parser.add_argument("--topk", type=int, default=10)
    parser.add_argument("--n-drop", dest="n_drop", type=int, default=3)
    parser.add_argument("--hold-thresh", dest="hold_thresh", type=int, default=1)
    parser.add_argument("--no-limit-threshold", action="store_true", help="与训练侧同语义：limit_threshold=None")
    parser.add_argument("--buy-state-filter", action="store_true")
    parser.add_argument("--st-filter", action="store_true")
    parser.add_argument("--age-filter", action="store_true")
    parser.add_argument("--age-days", type=int, default=60)
    parser.add_argument("--extra-exclude-file", default=None)
    parser.add_argument("--winner-ratio-file", default=None)
    parser.add_argument("--st-daily-file", default=None)
    parser.add_argument("--cost-tier", choices=sorted(COST_TIERS), default="qlib_default")
    parser.add_argument(
        "--replay",
        action="store_true",
        help="用 pred.pkl 再跑一遍 backtest_daily（换成本/topk/闸门时才需要）",
    )
    parser.add_argument(
        "--tag",
        default=None,
        help="输出子目录名；默认 <recorder8> 或 replay_<tag>",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="分析包根目录；默认 <repo>/exports/analysis/<tag>",
    )
    return parser.parse_args(argv)


def _qlib_init():
    print(qlib.__version__)
    _kernels = int(os.environ.get("QLIB_KERNELS", "1"))
    qlib.init(
        provider_uri="~/.qlib/qlib_data/my_data",
        region=REG_CN,
        kernels=_kernels,
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


def _load_report(recorder):
    try:
        return recorder.load_object("portfolio_analysis/report_normal_1day.pkl")
    except Exception as exc:
        print(f"[export] report_normal_1day missing: {exc}")
        return None


def _load_positions(recorder):
    try:
        return recorder.load_object("portfolio_analysis/positions_normal_1day.pkl")
    except Exception as exc:
        raise SystemExit(
            f"recorder 没有 positions_normal_1day.pkl，无法提取。"
            f"加 --replay 重跑回测，或重新训练。原因: {exc}"
        )


def main():
    args = parse_cli()
    if args.replay and not args.test:
        raise SystemExit("--replay 需要 --test START:END")
    if args.test:
        args.test_window = parse_segment(args.test, "test")
    else:
        args.test_window = None

    replay_only = []
    if args.buy_state_filter:
        replay_only.append("--buy-state-filter")
    if args.st_filter:
        replay_only.append("--st-filter")
    if args.age_filter:
        replay_only.append("--age-filter")
    if args.no_limit_threshold:
        replay_only.append("--no-limit-threshold")
    if args.topk != 10:
        replay_only.append(f"--topk {args.topk}")
    if args.n_drop != 3:
        replay_only.append(f"--n-drop {args.n_drop}")
    if replay_only and not args.replay:
        print(
            f"[export] 未加 --replay，策略参数 {replay_only} 不影响持仓"
            f"（持仓来自 recorder；--cost-tier 仍用于估算手续费）",
            flush=True,
        )

    t_rec = TimerRecorder()
    set_global_timer_recorder(t_rec)
    uninstall_probe = None
    with t_rec.timer("qlib.init"):
        _qlib_init()
    uninstall_probe = install_features_probe(t_rec)
    with t_rec.timer("load_pred"):
        recorder, pred = load_pred(args.exp_name, args.recorder_id)
    pred_score = pred["score"] if isinstance(pred, pd.DataFrame) else pred
    report = None

    if args.replay:
        args.pred_score = pred_score
        strategy_config = build_strategy_config(args)
        print(f"[export] replay backtest (tier={args.cost_tier}) ...", flush=True)
        with t_rec.timer("replay.backtest"):
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
        source = "replay"
    else:
        print("[export] extract positions from recorder (no replay)", flush=True)
        with t_rec.timer("extract.positions"):
            positions = _load_positions(recorder)
            report = _load_report(recorder)
            if args.test_window:
                positions = filter_positions_by_window(positions, args.test_window[0], args.test_window[1])
                if report is not None and len(report):
                    idx = pd.to_datetime(report.index)
                    mask = (idx >= args.test_window[0]) & (idx <= args.test_window[1])
                    report = report.loc[mask]
        source = "recorder"

    rid = recorder.id
    tag = args.tag
    if tag is None:
        tag = f"replay_{args.cost_tier}" if args.replay else rid
    out_dir = args.out_dir or os.path.join(_REPO_ROOT, "exports", "analysis", tag)
    os.makedirs(out_dir, exist_ok=True)

    tier = COST_TIERS[args.cost_tier]
    with t_rec.timer("export_analysis"):
        bundle = write_analysis_bundle(
        positions=positions,
        out_dir=out_dir,
        open_rate=tier["open_cost"],
        close_rate=tier["close_cost"],
        account=args.account,
        pred=pred,
        report=report,
        topk=args.topk,
        use_qlib_close=True,
        extra_summary={
            "source": source,
            "exp_name": args.exp_name,
            "recorder_id": rid,
            "cost_tier": args.cost_tier,
            "replay": bool(args.replay),
        },
    )
    print_bundle_summary(bundle)

    try:
        write_export_manifest(
            manifests_dir=os.path.join(_REPO_ROOT, "manifests"),
            config={
                "kind": "analysis_bundle",
                "source": source,
                "exp_name": args.exp_name,
                "recorder_id": rid,
                "test": list(args.test_window) if args.test_window else None,
                "benchmark": args.benchmark,
                "account": args.account,
                "topk": args.topk,
                "n_drop": args.n_drop,
                "hold_thresh": args.hold_thresh,
                "cost_tier": args.cost_tier,
                "limit_threshold": None if args.no_limit_threshold else 0.095,
                "replay": bool(args.replay),
                **{k: bundle["summary"][k] for k in ("position_rows", "trades_rows", "pnl_rows", "pnl_total")},
            },
            out_dir=out_dir,
            output_file_count=len(bundle["paths"]),
            timings=t_rec.as_timings(),
            repo_root=_REPO_ROOT,
            git_commit_sha=capture_git_provenance(_REPO_ROOT).get("git_commit"),
        )
    except Exception as exc:
        print(f"[export] manifest skipped: {exc}")
    try:
        if uninstall_probe is not None:
            uninstall_probe()
        t_rec.print_summary()
        t_rec.dump_json(os.path.join(out_dir, "timing.json"), extra={"source": source, "recorder_id": rid})
        print(f"=== Timing saved: {os.path.join(out_dir, 'timing.json')} ===")
    except Exception as exc:
        print(f"[export] timing dump skipped: {exc}")
    set_global_timer_recorder(None)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
