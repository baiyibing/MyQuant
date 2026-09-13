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
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# 共享 mlflow 逃生口 / 静音（须在任何 qlib import 之前）
import host_env  # noqa: E402,F401
from run_manifest import capture_git_provenance  # noqa: E402

_STATE: dict[str, Any] = {}

# 与 custom_train_backtest.py 同窗同配置（缺省三月窗；改默认时两处同步）
SEGMENTS = {
    "train": ("2026-01-01", "2026-01-31"),
    "valid": ("2026-02-01", "2026-02-28"),
    "test": ("2026-03-01", "2026-03-23"),
}

# 当前生效段（set_segments 写入；缺省 = SEGMENTS 拷贝，不污染常量）
_ACTIVE_SEGMENTS: dict[str, tuple[str, str]] = {
    k: (v[0], v[1]) for k, v in SEGMENTS.items()
}


def get_segments() -> dict[str, tuple[str, str]]:
    """当前生效 train/valid/test 窗口（拷贝）。"""
    return {k: (v[0], v[1]) for k, v in _ACTIVE_SEGMENTS.items()}


def _validate_pair(key: str, val: Any) -> tuple[str, str]:
    if isinstance(val, str):
        raw = val.strip()
        if raw.count(":") != 1:
            raise ValueError(f"illegal {key} format {val!r}; expected START:END or (start, end)")
        start, end = (part.strip() for part in raw.split(":", 1))
    elif isinstance(val, (list, tuple)) and len(val) == 2:
        start, end = str(val[0]).strip(), str(val[1]).strip()
    else:
        raise ValueError(f"segment {key} must be (start, end)")
    if not start or not end:
        raise ValueError(f"illegal {key} dates: empty start/end")
    try:
        d0 = date.fromisoformat(start)
        d1 = date.fromisoformat(end)
    except ValueError as exc:
        raise ValueError(f"illegal {key} dates: {start!r} {end!r}") from exc
    if d0 > d1:
        raise ValueError(f"{key} start > end: {start} > {end}")
    return start, end


def set_segments(segments: Mapping[str, Any]) -> None:
    """校验并切换生效窗口。须三段齐全、起止合法、train.start <= valid.start <= test.start。

    切窗后清掉 pred/label 缓存，避免沿用上一窗的 handler 结果。
    """
    if not isinstance(segments, Mapping):
        raise ValueError("segments must be a mapping with train/valid/test")
    missing = [k for k in ("train", "valid", "test") if k not in segments]
    if missing:
        raise ValueError(f"segments missing {missing}")
    parsed: dict[str, tuple[str, str]] = {}
    for key in ("train", "valid", "test"):
        parsed[key] = _validate_pair(key, segments[key])
    if not (parsed["train"][0] <= parsed["valid"][0] <= parsed["test"][0]):
        raise ValueError("require train.start <= valid.start <= test.start")
    _ACTIVE_SEGMENTS.clear()
    _ACTIVE_SEGMENTS.update(parsed)
    _STATE.pop("pred", None)
    _STATE.pop("label", None)


def _handler_span(segments: Mapping[str, tuple[str, str]]) -> tuple[str, str]:
    """handler start/end = 三段最小 start / 最大 end。"""
    start_time = min(segments[k][0] for k in ("train", "valid", "test"))
    end_time = max(segments[k][1] for k in ("train", "valid", "test"))
    return start_time, end_time


def _predict_once() -> tuple[pd.Series, pd.Series]:
    """构建 handler/dataset/model 一次，产出 (pred, label)（MultiIndex 对齐）。"""
    if "pred" in _STATE:
        return _STATE["pred"], _STATE["label"]

    # handler_init 之前一次性取 git 溯源（整次 sweep 共用）
    if "git_prov" not in _STATE:
        repo_root = _SCRIPT_DIR.parent
        _STATE["git_prov"] = capture_git_provenance(repo_root)

    import qlib
    from qlib.data import D
    from qlib.data.dataset import DatasetH
    from qlib.contrib.model import LGBModel

    from custom_handler import Alpha158CostKDJ
    from train_wiring import build_filtered_instruments

    qlib.init(provider_uri="C:/Users/Thinkpad/.qlib/qlib_data/my_data", region="cn")

    segs = get_segments()
    # handler 覆盖三段 min start / max end。label 用 Ref($close,-2)，
    # 末尾 1-2 天 label 为 NaN 会被 dropna——与三月窗现行为一致。
    start_time, end_time = _handler_span(segs)
    fit_start, fit_end = segs["train"]

    instruments = build_filtered_instruments(
        start_time=start_time, end_time=end_time, exclude_stocks=["SZ000004", "SH600107"]
    )
    handler = Alpha158CostKDJ(
        instruments=instruments,
        start_time=start_time,
        end_time=end_time,
        fit_start_time=fit_start,
        fit_end_time=fit_end,
        infer_processors=[
            {"class": "ProcessInf"},
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature"}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        learn_processors=[
            {
                "class": "DropLimitUpLearn",
                "module_path": "custom_handler",
                "kwargs": {"col": "LIMIT_STATUS", "value": 1},
            },
            {"class": "DropnaLabel"},
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "label"}},
        ],
        include_alpha158=True,
        include_cost_kdj=True,
        include_lz=True,
    )
    dataset = DatasetH(handler=handler, segments=dict(segs))
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
    git_prov = _STATE.get("git_prov") or {}
    segs = get_segments()
    return {
        "ic": ic,
        "ir": ir,
        "notes": f"ic=日命中率; ir=名单等权次日收益年化(未扣费); days={len(series)}",
        "pred_path": "",
        "git_commit": git_prov.get("git_commit"),
        "git_branch": git_prov.get("git_branch"),
        "git_dirty": git_prov.get("git_dirty"),
        # 生效窗口写入 payload.config，manifest 才能区分三月窗 vs OOS 窗
        "config": {
            "segments": {
                "train": [segs["train"][0], segs["train"][1]],
                "valid": [segs["valid"][0], segs["valid"][1]],
                "test": [segs["test"][0], segs["test"][1]],
            }
        },
    }
