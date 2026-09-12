# -*- coding: utf-8 -*-
"""M3-B 宿主适配器：给 sweep_ranking 注入真 train_predict_fn。

设计（成本模型）：pred/label **每进程只算一次**（一次 handler_init ~18min +
model fit ~5s），模块级缓存；网格每个格子只做「TopN 名单构建 + 轻量指标」，
所以整个真网格的总成本 ≈ 一次重训。

指标语义（宿主定义，结果表必须带此注释）：
  ic  = 日命中率——每个交易日选中名单中次日 label>0 的比例，对日取均值
  ir  = 名单等权次日收益序列的 mean/std × sqrt(252)（年化、未扣费）
label 沿用 Alpha158 口径 Ref($close,-2)/Ref($close,-1)-1。

名单策略（近似 Qlib TopkDropout，host 简化版）：
  每日按 pred 降序取候选；持有池先按「持有天数>=hold_thresh 才可被淘汰」
  保护，再从池中淘汰 pred 最低的 n_drop 只，最后从候选补足 topk。

用法（在 my_scripts/ 下、run 5 等训练进程结束后串行执行）::

    python sweep_ranking.py --topk 5,10,20 --n-drop 2,3 --hold 1 \\
        --out-dir sweep_out_20260913 --adapter sweep_live_adapter

注意：config 须与 custom_train_backtest.py 保持同步（分段/过滤/processors）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

_STATE: dict[str, Any] = {}

# 与 custom_train_backtest.py 同窗同配置（改窗时两处同步）
SEGMENTS = {
    "train": ("2026-01-01", "2026-01-31"),
    "valid": ("2026-02-01", "2026-02-28"),
    "test": ("2026-03-01", "2026-03-23"),
}


def _predict_once() -> tuple[pd.Series, pd.Series]:
    """构建 handler/dataset/model 一次，产出 (pred, label)（MultiIndex 对齐）。"""
    if "pred" in _STATE:
        return _STATE["pred"], _STATE["label"]

    import qlib
    from qlib.data import D
    from qlib.data.dataset import DatasetH
    from qlib.contrib.model import LGBModel

    from custom_handler import Alpha158CostKDJ
    from train_wiring import build_filtered_instruments

    qlib.init(provider_uri="C:/Users/Thinkpad/.qlib/qlib_data/my_data", region="cn")

    instruments = build_filtered_instruments(
        start_time="2026-01-01", end_time="2026-03-23", exclude_stocks=["SZ000004", "SH600107"]
    )
    handler = Alpha158CostKDJ(
        instruments=instruments,
        start_time="2026-01-01",
        end_time="2026-03-23",
        fit_start_time="2026-01-01",
        fit_end_time="2026-01-31",
        infer_processors=[
            {"class": "ProcessInf"},
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature"}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        learn_processors=[
            {"class": "DropLimitUpLearn"},
            {"class": "DropnaLabel"},
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "label"}},
        ],
        include_alpha158=True,
        include_cost_kdj=True,
        include_lz=True,
    )
    dataset = DatasetH(handler=handler, segments=dict(SEGMENTS))
    model = LGBModel(loss="mse", num_boost_round=200, learning_rate=0.05, max_depth=6)
    model.fit(dataset)

    pred = model.predict(dataset, "test")
    if isinstance(pred, pd.DataFrame):
        pred = pred.iloc[:, 0]
    label = dataset.prepare("test", col_set="label")
    if isinstance(label, pd.DataFrame):
        label = label.iloc[:, 0]
    _STATE["pred"], _STATE["label"] = pred.dropna(), label.dropna()
    print(f"[adapter] pred={len(_STATE['pred'])} label={len(_STATE['label'])} "
          f"days={_STATE['pred'].index.get_level_values(0).nunique()}", flush=True)
    return _STATE["pred"], _STATE["label"]


def _simulate_list(pred: pd.Series, label: pd.Series, topk: int, n_drop: int, hold_thresh: int) -> pd.Series:
    """TopkDropout 近似：返回每个交易日的持有名单等权次日收益（index=日期）。"""
    held: dict[str, int] = {}
    daily: dict[pd.Timestamp, float] = {}
    dates = sorted(pred.index.get_level_values(0).unique())
    for day in dates:
        # 结算前一日名单的收益
        scored = pred.xs(day).sort_values(ascending=False)
        # 淘汰：持有满 hold_thresh 的里面，pred 最低的 n_drop 只
        ranked_pos = {inst: i for i, inst in enumerate(scored.index)}
        droppable = [s for s in held if held[s] >= hold_thresh and s in ranked_pos]
        droppable.sort(key=lambda s: ranked_pos[s], reverse=True)
        for s in droppable[:n_drop]:
            del held[s]
        # 买入：pred 最高且未持有的补足 topk
        for inst in scored.index:
            if len(held) >= topk:
                break
            held.setdefault(inst, 0)
        # 记账：当日持有名单的次日收益（label 即次日口径）
        rets = [label.get((day, s)) for s in held]
        rets = [r for r in rets if r == r and r is not None]
        if rets:
            daily[day] = float(np.mean(rets))
        for s in list(held):
            held[s] += 1
    return pd.Series(daily, name="list_ret").sort_index()


def train_predict_fn(config) -> Mapping[str, Any]:
    """sweep_ranking 的注入点。"""
    pred, label = _predict_once()
    cfg = config.with_id()
    series = _simulate_list(pred, label, cfg.topk, cfg.n_drop, cfg.hold_thresh)
    hit = series > 0
    ic = float(hit.mean())
    ir = float(series.mean() / (series.std() + 1e-12) * math.sqrt(252))
    return {
        "ic": ic,
        "ir": ir,
        "notes": f"ic=日命中率; ir=名单等权次日收益年化(未扣费); days={len(series)}",
        "pred_path": "",
    }
