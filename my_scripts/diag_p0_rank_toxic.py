# -*- coding: utf-8 -*-
"""P0-3 有效秩深 + P0-4 头部分段毒尾（锁定单 recorder pred）。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import host_env  # noqa: F401

import numpy as np
import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.data import D
from qlib.workflow import R

from analysis_export import pred_score_frame

REPO = Path(__file__).resolve().parents[1]
K_REQ = 50
SEGMENTS = (("1-10", 1, 10), ("11-20", 11, 20), ("21-50", 21, 50))


def _init_qlib() -> None:
    qlib.init(
        provider_uri=os.path.expanduser("~/.qlib/qlib_data/my_data"),
        region=REG_CN,
        kernels=1,
        exp_manager={
            "class": "MLflowExpManager",
            "module_path": "qlib.workflow.expm",
            "kwargs": {"uri": str(Path(__file__).resolve().parent / "mlruns"), "default_exp_name": "MyExperiment"},
        },
    )


def _load_frame(obj, value_name: str) -> pd.DataFrame:
    if isinstance(obj, pd.Series):
        frame = obj.rename(value_name).reset_index()
    elif isinstance(obj, pd.DataFrame):
        frame = obj.reset_index() if isinstance(obj.index, pd.MultiIndex) else obj.copy()
    else:
        raise TypeError(type(obj))
    if value_name not in frame.columns:
        num = [c for c in frame.columns if c not in {"datetime", "instrument"}]
        if not num:
            raise ValueError(f"no {value_name} column")
        frame = frame.rename(columns={num[0]: value_name})
    if "datetime" not in frame.columns or "instrument" not in frame.columns:
        leftover = [c for c in frame.columns if c != value_name]
        frame = frame.rename(columns={leftover[0]: "datetime", leftover[1]: "instrument"})
    out = frame.loc[:, ["datetime", "instrument", value_name]].copy()
    out["datetime"] = pd.to_datetime(out["datetime"]).dt.normalize()
    out["instrument"] = out["instrument"].astype(str)
    out[value_name] = pd.to_numeric(out[value_name], errors="coerce")
    return out


def rank_pred(pred) -> pd.DataFrame:
    scores = pred_score_frame(pred)
    parts = []
    for pred_date, day in scores.groupby("datetime", sort=True):
        ranked = day.sort_values(["score", "instrument"], ascending=[False, True], kind="mergesort")
        ranked = ranked.drop_duplicates("instrument", keep="first").reset_index(drop=True)
        ranked = ranked.assign(pred_date=pred_date, rank=np.arange(1, len(ranked) + 1))
        parts.append(ranked)
    return pd.concat(parts, ignore_index=True)


def _pct(s: pd.Series, q: float) -> float:
    return float(s.quantile(q)) if len(s) else float("nan")


def build_p03(ranked: pd.DataFrame, picks: pd.DataFrame, pos: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """rank_max / k_fill 只看「补齐名义 50 的成交集」：new_buy + held（rank<=k）。

    held_not_topk 是 n_drop 留仓惯性，另列 port_rank_max，不进 P0-3 门检。
    回填 = 当日 new_buy 且 pred rank>k_req（涨停拒单后 walk-down）。
    """
    rows = []
    for trade_date, day in picks.groupby("trade_date", sort=True):
        fill = day[day["action"].isin(["new_buy", "held"])].copy()
        fill_ranks = pd.to_numeric(fill["rank"], errors="coerce").dropna()
        walkdown = fill[
            (fill["action"] == "new_buy") & (pd.to_numeric(fill["rank"], errors="coerce") > K_REQ)
        ]
        inertia = day[day["action"] == "held_not_topk"]
        missed = day[day["action"] == "missed"]
        port = day[day["held"]]
        port_ranks = pd.to_numeric(port["rank"], errors="coerce").dropna()
        k_fill = int(len(fill))
        rows.append(
            {
                "trade_date": trade_date,
                "pred_date": day["pred_date"].iloc[0],
                "k_req": K_REQ,
                "k_fill": k_fill,
                "k_fill_lt_k_req": int(k_fill < K_REQ),
                "rank_max": float(fill_ranks.max()) if len(fill_ranks) else float("nan"),
                "rank_p50_fill": _pct(fill_ranks, 0.50),
                "rank_p90_fill": _pct(fill_ranks, 0.90),
                "port_n": int(len(port)),
                "port_rank_max": float(port_ranks.max()) if len(port_ranks) else float("nan"),
                "n_walkdown_new": int(len(walkdown)),
                "n_held_not_topk": int(len(inertia)),
                "n_missed_topk": int(len(missed)),
                "refill_walkdown": int(len(walkdown) > 0),
                "universe_n": int((ranked["pred_date"] == pd.Timestamp(day["pred_date"].iloc[0])).sum()),
            }
        )
    daily = pd.DataFrame(rows)
    refill_days = int(daily["refill_walkdown"].sum()) if len(daily) else 0
    short_days = int(daily["k_fill_lt_k_req"].sum()) if len(daily) else 0
    n = max(len(daily), 1)
    rank_max_p50 = _pct(daily["rank_max"], 0.50)
    rank_max_p90 = _pct(daily["rank_max"], 0.90)
    refill_pct = refill_days / n
    short_pct = short_days / n
    degrade = bool(rank_max_p90 > 80 or refill_pct > 0.10)
    summary = {
        "recorder_filter": "OFF",
        "k_req": K_REQ,
        "trade_days": int(len(daily)),
        "k_fill_median": _pct(daily["k_fill"], 0.50),
        "k_fill_min": float(daily["k_fill"].min()) if len(daily) else float("nan"),
        "rank_max_p50": rank_max_p50,
        "rank_max_p90": rank_max_p90,
        "port_rank_max_p90": _pct(daily["port_rank_max"], 0.90),
        "refill_walkdown_days": refill_days,
        "refill_walkdown_pct": refill_pct,
        "k_fill_lt_k_req_days": short_days,
        "k_fill_lt_k_req_pct": short_pct,
        "missed_topk_days": int((daily["n_missed_topk"] > 0).sum()) if len(daily) else 0,
        "width_sweep_degrade": degrade,
        "degrade_reason": (
            "rank_max P90>80" if rank_max_p90 > 80 else ("回填日>10%" if refill_pct > 0.10 else "none")
        ),
        "note": (
            "本 recorder 训练未开 buy-state/ST/age。门检 rank_max 只含 new_buy+held；"
            "回填=new_buy 且 rank>50。held_not_topk 记 port_rank_max，不进门检。"
        ),
    }
    return daily, summary


def load_fwd_from_close(instruments: list[str], start: str, end: str) -> pd.DataFrame:
    """次日收益 = close[t+1]/close[t]-1，按 instrument 对齐 pred_date=t。"""
    codes = sorted(set(instruments))
    print(f"[p04] D.features $close n={len(codes)} {start}..{end}", flush=True)
    raw = D.features(codes, ["$close"], start_time=start, end_time=end)
    if raw is None or raw.empty:
        raise RuntimeError("D.features $close empty")
    frame = raw.reset_index()
    frame["datetime"] = pd.to_datetime(frame["datetime"]).dt.normalize()
    frame["instrument"] = frame["instrument"].astype(str)
    frame = frame.sort_values(["instrument", "datetime"])
    frame["fwd"] = frame.groupby("instrument")["$close"].pct_change().shift(-1)
    bench = D.features(["SH000300"], ["$close"], start_time=start, end_time=end).reset_index()
    bench["datetime"] = pd.to_datetime(bench["datetime"]).dt.normalize()
    bench = bench.sort_values("datetime")
    bench["mkt"] = bench["$close"].pct_change().shift(-1)
    out = frame[["datetime", "instrument", "fwd"]].merge(bench[["datetime", "mkt"]], on="datetime", how="left")
    out["excess"] = out["fwd"] - out["mkt"]
    return out


def build_p04(ranked: pd.DataFrame, labels: pd.DataFrame, picks: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    head = ranked[ranked["rank"] <= K_REQ].copy()
    merged = head.merge(
        labels,
        left_on=["pred_date", "instrument"],
        right_on=["datetime", "instrument"],
        how="left",
    )
    if "excess" not in merged.columns:
        mkt = merged.groupby("pred_date")["fwd"].transform("mean")
        merged["excess"] = merged["fwd"] - mkt
    merged["hit"] = merged["fwd"] > 0
    merged["neg"] = merged["fwd"] < 0

    def bucket(rank: float) -> str:
        if rank <= 10:
            return "1-10"
        if rank <= 20:
            return "11-20"
        return "21-50"

    merged["bucket"] = merged["rank"].map(bucket)
    picks_key = picks.assign(
        pred_date=pd.to_datetime(picks["pred_date"]),
        trade_date=picks["trade_date"].astype(str),
    )
    merged = merged.merge(
        picks_key[["pred_date", "instrument", "action", "held", "holding_days"]],
        on=["pred_date", "instrument"],
        how="left",
    )
    merged["path"] = np.where(
        merged["action"].isin(["new_buy"]),
        "new_buy",
        np.where(merged["action"].isin(["held", "held_not_topk"]), "held", "not_held"),
    )

    def agg(df: pd.DataFrame, extra: dict) -> dict:
        fwd = df["fwd"].dropna()
        exc = df["excess"].dropna()
        return {
            **extra,
            "n": int(len(df)),
            "n_with_label": int(fwd.size),
            "hit_rate": float((fwd > 0).mean()) if len(fwd) else float("nan"),
            "mean_fwd": float(fwd.mean()) if len(fwd) else float("nan"),
            "mean_excess": float(exc.mean()) if len(exc) else float("nan"),
            "neg_share": float((fwd < 0).mean()) if len(fwd) else float("nan"),
            "neg_tail_p10": float(fwd.quantile(0.10)) if len(fwd) else float("nan"),
            "neg_mean": float(fwd[fwd < 0].mean()) if (fwd < 0).any() else float("nan"),
        }

    rows = []
    for name, lo, hi in SEGMENTS:
        rows.append(agg(merged[(merged["rank"] >= lo) & (merged["rank"] <= hi)], {"bucket": name, "path": "all"}))
        for path in ("new_buy", "held", "not_held"):
            rows.append(
                agg(
                    merged[(merged["rank"] >= lo) & (merged["rank"] <= hi) & (merged["path"] == path)],
                    {"bucket": name, "path": path},
                )
            )
    table = pd.DataFrame(rows)
    # next-cut heuristic
    b10 = table[(table["bucket"] == "1-10") & (table["path"] == "all")].iloc[0]
    b50 = table[(table["bucket"] == "21-50") & (table["path"] == "all")].iloc[0]
    new10 = table[(table["bucket"] == "1-10") & (table["path"] == "new_buy")]
    held10 = table[(table["bucket"] == "1-10") & (table["path"] == "held")]
    widen_ok = float(b50["mean_excess"]) > float(b10["mean_excess"]) and float(b50["neg_share"]) < float(b10["neg_share"])
    path_gap = 0.0
    if len(new10) and len(held10) and new10.iloc[0]["n_with_label"] and held10.iloc[0]["n_with_label"]:
        path_gap = abs(float(new10.iloc[0]["mean_excess"]) - float(held10.iloc[0]["mean_excess"]))
    if path_gap >= 0.002:
        next_cut = "持仓路径"
        why = f"头部新买 vs 留仓超额差 {path_gap:.4f}，排序段差可能被持仓惯性主导"
    elif widen_ok:
        next_cut = "加宽"
        why = "21–50 超额高于 1–10 且负尾更轻：毒在头、稀释有效"
    else:
        next_cut = "改信号"
        why = "21–50 并未稳定好于 1–10，宽度稀释解释不足，优先看排序/信号"
    verdict = {
        "next_cut": next_cut,
        "why": why,
        "bucket_1_10_excess": float(b10["mean_excess"]),
        "bucket_21_50_excess": float(b50["mean_excess"]),
        "bucket_1_10_neg_share": float(b10["neg_share"]),
        "bucket_21_50_neg_share": float(b50["neg_share"]),
        "new_vs_held_excess_gap": path_gap,
    }
    return merged, table, verdict


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--recorder-id", default="8a061ea428e04bb3a199a485ade49d0e")
    p.add_argument("--exp-name", default="alpha158_cost_kdj_lgb")
    p.add_argument(
        "--analysis-dir",
        default=str(REPO / "exports/analysis/8a061ea428e04bb3a199a485ade49d0e"),
    )
    p.add_argument(
        "--out-dir",
        default=str(REPO / "docs/reviews/2026-09-15-qlib-perf-brainstorm/runs"),
    )
    args = p.parse_args(argv)

    _init_qlib()
    rec = R.get_recorder(recorder_id=args.recorder_id, experiment_name=args.exp_name)
    pred = rec.load_object("pred.pkl")
    label = None
    missing = []
    try:
        label = _load_frame(rec.load_object("label.pkl"), "fwd")
    except Exception as exc:
        missing.append(f"label.pkl ({type(exc).__name__}: {exc})")

    ranked = rank_pred(pred)
    analysis = Path(args.analysis_dir)
    picks = pd.read_csv(analysis / "daily_picks.csv")
    pos = pd.read_csv(analysis / "positions_daily.csv")
    if label is None:
        insts = ranked.loc[ranked["rank"] <= K_REQ, "instrument"].astype(str).tolist()
        start = str(ranked["pred_date"].min().date())
        end = "2026-09-21"
        try:
            label = load_fwd_from_close(insts, start, end)
        except Exception as exc:
            missing.append(f"D.features $close ({type(exc).__name__}: {exc})")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    daily, p03 = build_p03(ranked, picks, pos)
    daily_path = out / "2026-09-15-p0-3-rank-depth-50n5.csv"
    daily.to_csv(daily_path, index=False)
    (out / "2026-09-15-p0-3-rank-depth-50n5.summary.json").write_text(
        json.dumps(p03, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    p04_table = None
    verdict = None
    if label is not None:
        _detail, p04_table, verdict = build_p04(ranked, label, picks)
        table_path = out / "2026-09-15-p0-4-toxic-tail-50n5.csv"
        p04_table.to_csv(table_path, index=False)
        (out / "2026-09-15-p0-4-toxic-tail-50n5.summary.json").write_text(
            json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    else:
        missing.append("label.pkl for P0-4 forward returns")

    print(json.dumps({"p03": p03, "p04": verdict, "missing": missing}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
