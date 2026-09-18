# -*- coding: utf-8 -*-
"""收盘后：用已有 trained_model 对日历末日出分，导出次日 50/5+ST+年龄名单。

不重训、不写 recorder pred.pkl。T 日收盘分 → T+1 买入（pred_minus_one / shift=1）。

用法（仓库根，解释器钉 vanna312）::

    python my_scripts/export_next_day_pool.py
    # 默认：8a061ea4 / 50/5 / ST+年龄开 / 买入状态关 / 不重训
    # 已有出分 CSV 时：--skip-predict --pred-csv <path> --force
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import sys
from datetime import date, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import host_env  # noqa: E402,F401
import pandas as pd  # noqa: E402
from data_root import resolve_st_daily  # noqa: E402

DEFAULT_REC = "8a061ea428e04bb3a199a485ade49d0e"
DEFAULT_EXP = "alpha158_cost_kdj_lgb"
DEFAULT_PROVIDER = os.path.expanduser("~/.qlib/qlib_data/my_data")


def _as_date(value) -> date:
    return pd.Timestamp(value).date()


def next_calendar_date(pred_date, calendar: list) -> date:
    """日历上 pred_date 的下一交易日；日历未收录则退回下一自然日（周末再 +1/+2）。"""
    pred = _as_date(pred_date)
    dates = [_as_date(x) for x in calendar]
    for d in dates:
        if d > pred:
            return d
    nxt = pred + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def score_frame(pred) -> pd.DataFrame:
    if isinstance(pred, pd.DataFrame):
        score = pred["score"] if "score" in pred.columns else pred.iloc[:, 0]
    else:
        score = pred
    frame = score.rename("score").dropna().to_frame()
    out = frame.reset_index()
    out = out.rename(columns={out.columns[0]: "datetime", out.columns[1]: "instrument"})
    out["instrument"] = out["instrument"].astype(str).str.upper()
    out["score"] = pd.to_numeric(out["score"], errors="coerce")
    out = out.dropna(subset=["score"])
    out = out.sort_values(["score", "instrument"], ascending=[False, True]).reset_index(drop=True)
    out["raw_rank"] = out.index + 1
    return out


def plan_rebalance(
    held: pd.DataFrame,
    target: pd.DataFrame,
    ranked: pd.DataFrame,
    n_drop: int,
) -> dict[str, pd.DataFrame]:
    """对照收盘持仓与次日 TopK：新买 / 留仓 / 计划卖出（n_drop 最弱榜外仓）。"""
    held = held.copy()
    held["instrument"] = held["instrument"].astype(str).str.upper()
    held_set = set(held["instrument"])
    target_inst = set(target["instrument"].astype(str).str.upper())
    score_map = dict(zip(ranked["instrument"], ranked["score"]))
    rank_map = dict(zip(ranked["instrument"], ranked["raw_rank"]))

    held_in = held[held["instrument"].isin(target_inst)].copy()
    held_out = held[~held["instrument"].isin(target_inst)].copy()
    held_out["score"] = held_out["instrument"].map(score_map)
    held_out = held_out.sort_values(["score", "instrument"], ascending=[True, True])
    sell = held_out.head(max(int(n_drop), 0)).copy()
    keep_extra = held_out.iloc[max(int(n_drop), 0) :].copy()
    keep = pd.concat([held_in, keep_extra], ignore_index=True)
    new_buy = target[~target["instrument"].isin(held_set)].copy()

    pick_rows: list[dict] = []
    buy_date = str(target["buy_date"].iloc[0]) if "buy_date" in target.columns and len(target) else ""
    pred_date = str(target["pred_date"].iloc[0]) if "pred_date" in target.columns and len(target) else ""
    for r in target.itertuples(index=False):
        inst = str(r.instrument).upper()
        in_port = inst in held_set
        hd = 0
        if in_port and "holding_days" in held.columns:
            hd = int(held.loc[held["instrument"] == inst, "holding_days"].iloc[0])
        pick_rows.append(
            {
                "trade_date": buy_date,
                "pred_date": pred_date,
                "rank": int(getattr(r, "buy_rank", 0) or 0),
                "instrument": inst,
                "score": float(r.score),
                "held": in_port,
                "holding_days": hd,
                "action": "held" if in_port else "new_buy",
            }
        )
    for inst in keep_extra["instrument"]:
        hd = 0
        if "holding_days" in held.columns:
            hd = int(held.loc[held["instrument"] == inst, "holding_days"].iloc[0])
        pick_rows.append(
            {
                "trade_date": buy_date,
                "pred_date": pred_date,
                "rank": rank_map.get(inst),
                "instrument": inst,
                "score": score_map.get(inst),
                "held": True,
                "holding_days": hd,
                "action": "held_not_topk",
            }
        )
    for inst in sell["instrument"]:
        hd = 0
        if "holding_days" in held.columns:
            hd = int(held.loc[held["instrument"] == inst, "holding_days"].iloc[0])
        pick_rows.append(
            {
                "trade_date": buy_date,
                "pred_date": pred_date,
                "rank": rank_map.get(inst),
                "instrument": inst,
                "score": score_map.get(inst),
                "held": True,
                "holding_days": hd,
                "action": "plan_sell",
            }
        )
    return {
        "new_buy": new_buy,
        "hold": keep,
        "sell": sell,
        "daily_picks": pd.DataFrame(pick_rows),
    }


def write_suite(
    out_dir: Path,
    *,
    ranked: pd.DataFrame,
    target: pd.DataFrame,
    held: pd.DataFrame | None,
    n_drop: int,
    meta: dict,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    ranked.to_csv(out_dir / "pred_ranked_all.csv", index=False, encoding="utf-8-sig")
    target.to_csv(out_dir / "target_topk.csv", index=False, encoding="utf-8-sig")
    blocked = ranked[(ranked["raw_rank"] <= 80) & (~ranked["eligible"])] if "eligible" in ranked.columns else pd.DataFrame()
    blocked.to_csv(out_dir / "blocked_head80.csv", index=False, encoding="utf-8-sig")
    if held is None or held.empty:
        target.to_csv(out_dir / "new_buy.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame().to_csv(out_dir / "hold.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame().to_csv(out_dir / "sell.csv", index=False, encoding="utf-8-sig")
        target.assign(action="new_buy").to_csv(out_dir / "daily_picks.csv", index=False, encoding="utf-8-sig")
        meta.update({"new_buy": int(len(target)), "plan_sell": 0, "held_eod": 0})
    else:
        held.to_csv(out_dir / "positions_eod.csv", index=False, encoding="utf-8-sig")
        parts = plan_rebalance(held, target, ranked, n_drop)
        parts["new_buy"].to_csv(out_dir / "new_buy.csv", index=False, encoding="utf-8-sig")
        parts["hold"].to_csv(out_dir / "hold.csv", index=False, encoding="utf-8-sig")
        parts["sell"].to_csv(out_dir / "sell.csv", index=False, encoding="utf-8-sig")
        parts["daily_picks"].to_csv(out_dir / "daily_picks.csv", index=False, encoding="utf-8-sig")
        meta.update(
            {
                "new_buy": int(len(parts["new_buy"])),
                "plan_sell": int(len(parts["sell"])),
                "held_eod": int(len(held)),
                "hold_including_inertia": int(len(parts["hold"])),
            }
        )
    meta["blocked_in_raw_top80"] = int(len(blocked))
    (out_dir / "suite.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def _predict_last_day(args) -> pd.DataFrame:
    import qlib
    from qlib.config import REG_CN
    from qlib.data.dataset import DatasetH
    from qlib.workflow import R

    from custom_handler import Alpha158CostKDJ, build_learn_processors
    from custom_utils import TimerRecorder, install_features_probe, set_global_timer_recorder
    from handler_frame_cache import (
        attach_calendar_fingerprint,
        load_or_build_handler,
        make_handler_cache_payload,
    )
    from train_wiring import EXCLUDE_STOCKS_DEFAULT, build_filtered_instruments

    pred_d = args.pred_date
    t_rec = TimerRecorder()
    set_global_timer_recorder(t_rec)
    qlib.init(
        provider_uri=args.provider_uri,
        region=REG_CN,
        kernels=int(os.environ.get("QLIB_KERNELS", "1")),
        exp_manager={
            "class": "MLflowExpManager",
            "module_path": "qlib.workflow.expm",
            "kwargs": {"uri": "mlruns", "default_exp_name": "MyExperiment"},
        },
    )
    uninstall = install_features_probe(t_rec)
    start_time, end_time = "2020-01-01", pred_d
    segments = {
        "train": ("2020-01-01", "2024-12-31"),
        "valid": ("2025-01-01", "2025-12-31"),
        "test": (pred_d, pred_d),
    }
    instruments = build_filtered_instruments(
        start_time=start_time,
        end_time=end_time,
        exclude_stocks=EXCLUDE_STOCKS_DEFAULT,
        use_exclude=False,
        limit_up=False,
        market="all",
    )
    handler_cfg = {
        "start_time": start_time,
        "end_time": end_time,
        "fit_start_time": segments["train"][0],
        "fit_end_time": segments["train"][1],
        "infer_processors": [
            {"class": "ProcessInf"},
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature"}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        "learn_processors": build_learn_processors(drop_limit_up=False),
        "instruments": instruments,
        "include_alpha158": True,
        "include_cost_kdj": True,
        "include_signal": False,
        "include_lz": True,
        "drop_raw": True,
    }
    payload = attach_calendar_fingerprint(
        make_handler_cache_payload(
            start_time=start_time,
            end_time=end_time,
            fit_start_time=segments["train"][0],
            fit_end_time=segments["train"][1],
            segments={**segments, "test": ("2026-01-01", pred_d)},
            include_alpha158=True,
            include_cost_kdj=True,
            include_signal=False,
            include_lz=True,
            drop_raw=True,
            exclude_filter_on=False,
            limit_up_filter_on=False,
            tradable_universe_on=False,
            drop_limit_up_learn_on=False,
            provider_uri=args.provider_uri,
        )
    )
    print(f"[next-day] handler digest={payload.get('digest', '')}", flush=True)
    handler, hit, obs = load_or_build_handler(
        payload=payload,
        builder=lambda: Alpha158CostKDJ(**handler_cfg),
        enabled=True,
    )
    print(f"[next-day] handler cache_hit={hit} key={obs.get('digest')}", flush=True)
    dataset = DatasetH(handler=handler, segments=dict(segments))
    rec = R.get_recorder(recorder_id=args.recorder_id, experiment_name=args.exp_name)
    model = rec.load_object("trained_model")
    print("[next-day] predict last day; recorder pred.pkl not written", flush=True)
    pred = model.predict(dataset, "test")
    try:
        uninstall()
        t_rec.print_summary()
    except Exception:
        pass
    return score_frame(pred)


def parse_cli(argv=None):
    p = argparse.ArgumentParser(description="收盘后次日名单：已有模型出分 + ST/年龄 + 对照持仓")
    p.add_argument("--recorder-id", default=DEFAULT_REC)
    p.add_argument("--exp-name", default=DEFAULT_EXP)
    p.add_argument("--provider-uri", default=DEFAULT_PROVIDER)
    p.add_argument("--pred-date", default=None, help="出分日，默认 qlib 日历末日")
    p.add_argument("--buy-date", default=None, help="买入日，默认出分日的下一交易日")
    p.add_argument("--topk", type=int, default=50)
    p.add_argument("--n-drop", dest="n_drop", type=int, default=5)
    p.add_argument("--st-filter", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--age-filter", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--age-days", type=int, default=60)
    p.add_argument(
        "--st-daily-file",
        default="",
        help="ST parquet；缺省 {OSKH_SOURCE_PARQUET_ROOT}/vendor_wind_st_status/st_daily.parquet",
    )
    p.add_argument("--analysis-dir", default=str(_ROOT / "exports" / "analysis" / "8a061ea4_50n5_st_age"))
    p.add_argument("--out-dir", default=None)
    p.add_argument("--pred-csv", default=None, help="已有出分 CSV 时跳过 predict")
    p.add_argument("--skip-predict", action="store_true")
    p.add_argument("--force", action="store_true", help="允许覆盖 out-dir")
    return p.parse_args(argv)


def load_pred_csv(path: Path | str) -> pd.DataFrame:
    raw = pd.read_csv(path)
    if "instrument" not in raw.columns:
        return score_frame(raw.set_index(list(raw.columns[:2]))[raw.columns[2]])
    raw["instrument"] = raw["instrument"].astype(str).str.upper()
    raw = raw.sort_values(["score", "instrument"], ascending=[False, True]).reset_index(drop=True)
    raw["raw_rank"] = raw.index + 1
    return raw


def main(argv=None) -> int:
    args = parse_cli(argv)
    if args.skip_predict and not args.pred_csv:
        raise SystemExit("--skip-predict 需要 --pred-csv")

    import qlib
    from qlib.config import REG_CN
    from qlib.data import D

    from buy_eligibility import BuyEligibilityFilter, load_age_map
    from train_wiring import EXCLUDE_STOCKS_DEFAULT

    qlib.init(
        provider_uri=args.provider_uri,
        region=REG_CN,
        kernels=int(os.environ.get("QLIB_KERNELS", "1")),
        exp_manager={
            "class": "MLflowExpManager",
            "module_path": "qlib.workflow.expm",
            "kwargs": {"uri": "mlruns", "default_exp_name": "MyExperiment"},
        },
    )
    cal = list(D.calendar(start_time="2020-01-01", end_time="2099-12-31", future=True))
    if not cal:
        raise SystemExit("qlib calendar empty")
    pred_date = args.pred_date or str(_as_date(cal[-1]))
    args.pred_date = pred_date
    buy_date = args.buy_date or str(next_calendar_date(pred_date, cal))
    out_dir = Path(args.out_dir) if args.out_dir else _ROOT / "exports" / "live_pool" / buy_date.replace("-", "")
    if out_dir.exists() and any(out_dir.iterdir()) and not args.force:
        raise SystemExit(f"out-dir not empty (pass --force): {out_dir}")

    ranked = load_pred_csv(args.pred_csv) if args.skip_predict else _predict_last_day(args)

    cal_elig = list(D.calendar(start_time="2020-01-01", end_time=buy_date, future=True))
    filt_kwargs = {
        "st_codes": set(EXCLUDE_STOCKS_DEFAULT) if args.st_filter else None,
        "age_map": load_age_map(Path(args.provider_uri)) if args.age_filter else None,
        "age_days": args.age_days,
        "check_buy_state": False,
        "calendar": cal_elig,
        "st_daily_file": (args.st_daily_file or str(resolve_st_daily())) if args.st_filter else None,
    }
    filt = BuyEligibilityFilter(**filt_kwargs)
    codes = ranked["instrument"].tolist()
    if args.st_filter or args.age_filter:
        ok = set(filt.eligible(codes, buy_date))
        banned = filt.st_codes_of_date(buy_date) if args.st_filter else set()
        ranked["is_st"] = ranked["instrument"].isin(banned)
        ranked["eligible"] = ranked["instrument"].isin(ok)
    else:
        ranked["is_st"] = False
        ranked["eligible"] = True
    kept = ranked.loc[ranked["eligible"]].copy().reset_index(drop=True)
    kept["buy_rank"] = kept.index + 1
    target = kept.head(args.topk).copy()
    target.insert(0, "buy_date", buy_date)
    target.insert(1, "pred_date", pred_date)

    held = None
    pos_path = Path(args.analysis_dir) / "positions_daily.csv"
    if pos_path.is_file():
        pos = pd.read_csv(pos_path)
        pos["date"] = pd.to_datetime(pos["date"]).dt.strftime("%Y-%m-%d")
        eod = pos[pos["date"] == pred_date]
        if eod.empty:
            last = pos["date"].max()
            eod = pos[pos["date"] == last]
            print(f"[next-day] no positions on {pred_date}; using {last}", flush=True)
        held = eod.copy()

    pred_csv = out_dir / f"pred_{pred_date.replace('-', '')}.csv"
    out_dir.mkdir(parents=True, exist_ok=True)
    ranked.to_csv(pred_csv, index=False, encoding="utf-8-sig")
    meta = {
        "retrain": False,
        "recorder_id": args.recorder_id,
        "pred_date": pred_date,
        "buy_date": buy_date,
        "topk": args.topk,
        "n_drop": args.n_drop,
        "st_filter": bool(args.st_filter),
        "age_filter": bool(args.age_filter),
        "st_note": "st_daily as-of buy_date; if parquet lags, uses last available day",
        "analysis_dir": args.analysis_dir,
        "out_dir": str(out_dir),
        "pred_csv": str(pred_csv),
        "pred_rows": int(len(ranked)),
        "eligible_rows": int(len(kept)),
    }
    write_suite(out_dir, ranked=ranked, target=target, held=held, n_drop=args.n_drop, meta=meta)
    print(json.dumps(meta, ensure_ascii=False, indent=2), flush=True)
    print(f"[next-day] suite {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
