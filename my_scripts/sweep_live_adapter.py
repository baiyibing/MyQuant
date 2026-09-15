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

    python sweep_ranking.py --topk 5,10,20 --n-drop 2,3 --hold 1 \
        --out-dir sweep_out_20260913 --adapter sweep_live_adapter

阶段机（eng-perf P1-5）：``predict_extended|train → pred 产物 → export /
sweep --pred-from``。二次 sweep 用 ``--pred-from`` / ``--label-from`` 只读产物，
跳过 handler_init+fit+predict；``--pred-out`` 在 INIT_ONCE 落盘供续跑。

注意：config 须与 custom_train_backtest.py 保持同步（分段/过滤/processors）。
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
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
from run_manifest import capture_git_provenance, config_hash, md5_file  # noqa: E402
from handler_frame_cache import resolve_qlib_kernels  # noqa: E402

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
    # 跨窗禁止硬共享：清 pred/label 与 shared cache 标记
    _STATE.pop("pred", None)
    _STATE.pop("label", None)
    _STATE.pop("shared_handler_cache_key", None)
    _STATE.pop("arm_mode", None)
    _STATE.pop("last_timings", None)
    _STATE.pop("pred_path", None)
    _STATE.pop("pred_md5", None)


def _handler_span(segments: Mapping[str, tuple[str, str]]) -> tuple[str, str]:
    """handler start/end = 三段最小 start / 最大 end。"""
    start_time = min(segments[k][0] for k in ("train", "valid", "test"))
    end_time = max(segments[k][1] for k in ("train", "valid", "test"))
    return start_time, end_time


# 与 _build_pred_label 内 handler 旋钮对齐的稳定键材料（不做磁盘 handler-cache）
_HANDLER_KEY_KNOBS: dict[str, Any] = {
    "handler_class": "Alpha158CostKDJ",
    "include_alpha158": True,
    "include_cost_kdj": True,
    "include_lz": True,
    "exclude_stocks": ["SZ000004", "SH600107"],
    "model": "LGBModel",
    "loss": "mse",
    "num_boost_round": 200,
}


def make_shared_handler_cache_key(segments: Mapping[str, tuple[str, str]] | None = None) -> str:
    """Stable short digest over segments span + key handler knobs (eng-perf P0-2)."""
    segs = dict(segments) if segments is not None else get_segments()
    start_time, end_time = _handler_span(segs)
    fit_start, fit_end = segs["train"]
    material = {
        **_HANDLER_KEY_KNOBS,
        "start_time": start_time,
        "end_time": end_time,
        "fit_start_time": fit_start,
        "fit_end_time": fit_end,
        "segments": {
            k: [segs[k][0], segs[k][1]] for k in ("train", "valid", "test")
        },
    }
    return config_hash(material)


def configure_pred_handoff(
    *,
    pred_from: Path | str | None = None,
    label_from: Path | str | None = None,
    pred_out: Path | str | None = None,
) -> None:
    """Opt-in pred artifact handoff (eng-perf P1-5).

    ``pred_from`` / ``label_from`` enable offline continuation (skip
    ``_build_pred_label``). ``pred_out`` writes on INIT_ONCE (atomic rename).
    Clears in-process pred cache so the next arm re-resolves.
    """
    _STATE["pred_from"] = Path(pred_from).expanduser() if pred_from else None
    _STATE["label_from"] = Path(label_from).expanduser() if label_from else None
    _STATE["pred_out"] = Path(pred_out).expanduser() if pred_out else None
    for key in (
        "pred",
        "label",
        "shared_handler_cache_key",
        "arm_mode",
        "last_timings",
        "pred_path",
        "pred_md5",
    ):
        _STATE.pop(key, None)


def _pred_meta_path(pred_path: Path) -> Path:
    return Path(str(pred_path) + ".meta.json")


def _label_sidecar_path(pred_path: Path) -> Path:
    return pred_path.with_name(f"{pred_path.stem}.label{pred_path.suffix}")


def _frame_to_mi_series(frame: pd.DataFrame, value_col: str) -> pd.Series:
    work = frame.loc[:, ["datetime", "instrument", value_col]].copy()
    work["datetime"] = pd.to_datetime(work["datetime"], errors="raise").dt.normalize()
    work["instrument"] = work["instrument"].astype(str)
    work[value_col] = pd.to_numeric(work[value_col], errors="raise")
    work = work.dropna(subset=[value_col])
    if work.empty:
        raise ValueError("prediction/label table is empty after dropna")
    idx = pd.MultiIndex.from_arrays(
        [work["datetime"], work["instrument"]],
        names=["datetime", "instrument"],
    )
    return pd.Series(work[value_col].to_numpy(), index=idx, name=value_col)


def load_pred_series(path: Path | str) -> pd.Series:
    """Load pred as MultiIndex Series; CSV/pkl contract matches export_daily_pool."""
    from export_daily_pool import load_predictions

    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"pred file does not exist: {p}")
    frame = load_predictions(p)
    if frame.empty:
        raise ValueError(f"pred file is empty: {p}")
    return _frame_to_mi_series(frame, "score")


def load_label_series(path: Path | str) -> pd.Series:
    """Load label MultiIndex Series (CSV with label|score, or MultiIndex pickle)."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"label file does not exist: {p}")
    suffix = p.suffix.lower()
    if suffix == ".csv":
        frame = pd.read_csv(p, dtype={"instrument": str})
        if "label" in frame.columns:
            value_col = "label"
        elif "score" in frame.columns:
            value_col = "score"
        else:
            raise ValueError("label CSV needs a 'label' or 'score' column")
        need = {"datetime", "instrument", value_col}
        missing = sorted(need.difference(frame.columns))
        if missing:
            raise ValueError(f"label CSV missing column(s): {', '.join(missing)}")
        return _frame_to_mi_series(frame, value_col)
    if suffix in {".pkl", ".pickle"}:
        obj = pd.read_pickle(p)
        if isinstance(obj, pd.Series):
            if not isinstance(obj.index, pd.MultiIndex) or obj.index.nlevels != 2:
                raise ValueError(
                    "label pickle Series must be MultiIndex (datetime, instrument)"
                )
            series = obj.dropna()
            if series.empty:
                raise ValueError(f"label file is empty: {p}")
            series = series.copy()
            series.index = series.index.set_names(["datetime", "instrument"])
            series.name = series.name or "label"
            return series
        if isinstance(obj, pd.DataFrame):
            if not isinstance(obj.index, pd.MultiIndex) or obj.index.nlevels != 2:
                raise ValueError(
                    "label pickle must have MultiIndex (datetime, instrument)"
                )
            frame = obj.reset_index()
            index_columns = list(frame.columns[:2])
            frame = frame.rename(
                columns={
                    index_columns[0]: "datetime",
                    index_columns[1]: "instrument",
                }
            )
            if "label" in frame.columns:
                value_col = "label"
            elif "score" in frame.columns:
                value_col = "score"
            else:
                candidates = [
                    c for c in frame.columns if c not in {"datetime", "instrument"}
                ]
                if not candidates:
                    raise ValueError("label pickle DataFrame has no value column")
                value_col = candidates[0]
            return _frame_to_mi_series(frame, value_col)
        raise ValueError("label pickle must contain a pandas Series or DataFrame")
    raise ValueError("label path must end in .csv, .pkl, or .pickle")


def series_to_pred_frame(series: pd.Series) -> pd.DataFrame:
    """MultiIndex Series → datetime,instrument,score DataFrame (export contract)."""
    s = series.dropna()
    if not isinstance(s.index, pd.MultiIndex) or s.index.nlevels != 2:
        raise ValueError("pred series must have MultiIndex (datetime, instrument)")
    frame = s.rename("score").reset_index()
    frame = frame.rename(
        columns={
            frame.columns[0]: "datetime",
            frame.columns[1]: "instrument",
            frame.columns[2]: "score",
        }
    )
    frame["datetime"] = pd.to_datetime(frame["datetime"], errors="raise").dt.normalize()
    frame["instrument"] = frame["instrument"].astype(str)
    frame["score"] = pd.to_numeric(frame["score"], errors="raise")
    return frame.loc[:, ["datetime", "instrument", "score"]]


def _atomic_write_csv(frame: pd.DataFrame, dest: Path) -> None:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    frame.to_csv(tmp, index=False, encoding="utf-8", lineterminator="\n")
    os.replace(tmp, dest)


def write_pred_artifact(
    pred: pd.Series,
    path: Path | str,
    *,
    label: pd.Series | None = None,
    segments: Mapping[str, tuple[str, str]] | None = None,
    shared_handler_cache_key: str | None = None,
) -> tuple[Path, str]:
    """Write pred CSV (+ optional label sidecar + meta) with temp→rename.

    Returns ``(pred_path, pred_md5)``. Meta is written *after* the pred bytes
    land so a partial write never looks complete.
    """
    dest = Path(path).expanduser()
    frame = series_to_pred_frame(pred)
    if frame.empty:
        raise ValueError("refusing to write empty pred artifact")
    _atomic_write_csv(frame, dest)
    digest = md5_file(dest)

    label_path: str | None = None
    if label is not None:
        lab_dest = _label_sidecar_path(dest)
        lab_frame = series_to_pred_frame(label).rename(columns={"score": "label"})
        _atomic_write_csv(lab_frame, lab_dest)
        label_path = str(lab_dest)

    segs = dict(segments) if segments is not None else get_segments()
    meta = {
        "pred_md5": digest,
        "shared_handler_cache_key": shared_handler_cache_key
        or make_shared_handler_cache_key(segs),
        "segments": {
            k: [segs[k][0], segs[k][1]] for k in ("train", "valid", "test")
        },
        "label_path": label_path,
        "rows": int(len(frame)),
    }
    meta_path = _pred_meta_path(dest)
    meta_tmp = meta_path.with_name(meta_path.name + ".tmp")
    if meta_tmp.exists():
        meta_tmp.unlink()
    meta_tmp.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(meta_tmp, meta_path)
    return dest, digest


def _log_pred_from(status: str, *, reason: str, **fields: Any) -> None:
    parts = [f"PRED_FROM {status}", f"reason={reason}"]
    for key, val in fields.items():
        if val is None:
            continue
        parts.append(f"{key}={val}")
    print(" ".join(parts), flush=True)


def _validate_pred_meta(pred_path: Path, meta_path: Path) -> None:
    """Optional sidecar: key/md5 mismatch → hard MISS (no silent dirty reuse)."""
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _log_pred_from(
            "MISS", reason="meta_unreadable", path=str(pred_path), detail=str(exc)
        )
        raise ValueError(f"pred meta unreadable: {meta_path}: {exc}") from exc
    if not isinstance(meta, dict):
        _log_pred_from("MISS", reason="meta_invalid", path=str(pred_path))
        raise ValueError(f"pred meta must be a JSON object: {meta_path}")

    file_md5 = md5_file(pred_path)
    recorded = meta.get("pred_md5")
    if recorded is not None and str(recorded) != file_md5:
        _log_pred_from(
            "MISS",
            reason="md5_mismatch",
            path=str(pred_path),
            expected=recorded,
            actual=file_md5,
        )
        raise ValueError(
            f"pred md5 mismatch for {pred_path}: meta={recorded} file={file_md5}"
        )

    segs = get_segments()
    current_key = make_shared_handler_cache_key(segs)
    recorded_key = meta.get("shared_handler_cache_key")
    if recorded_key is not None and str(recorded_key) != current_key:
        _log_pred_from(
            "MISS",
            reason="key_mismatch",
            path=str(pred_path),
            expected=recorded_key,
            actual=current_key,
        )
        raise ValueError(
            f"pred shared_handler_cache_key mismatch for {pred_path}: "
            f"meta={recorded_key} current={current_key}"
        )

    recorded_segs = meta.get("segments")
    if isinstance(recorded_segs, Mapping):
        for part in ("train", "valid", "test"):
            got = recorded_segs.get(part)
            if got is None:
                continue
            if list(got) != [segs[part][0], segs[part][1]]:
                _log_pred_from(
                    "MISS",
                    reason="segments_mismatch",
                    path=str(pred_path),
                    part=part,
                    expected=got,
                    actual=[segs[part][0], segs[part][1]],
                )
                raise ValueError(
                    f"pred segments mismatch ({part}) for {pred_path}: "
                    f"meta={got} current={[segs[part][0], segs[part][1]]}"
                )


def _load_pred_from_disk() -> tuple[pd.Series, pd.Series]:
    """Load ``--pred-from`` (+ optional label). Raises on MISS; never builds."""
    pred_path = _STATE.get("pred_from")
    if pred_path is None:
        raise RuntimeError("pred_from not configured")
    pred_path = Path(pred_path)
    if not pred_path.is_file():
        _log_pred_from("MISS", reason="missing_file", path=str(pred_path))
        raise FileNotFoundError(f"PRED_FROM MISS reason=missing_file path={pred_path}")

    meta_path = _pred_meta_path(pred_path)
    if meta_path.is_file():
        _validate_pred_meta(pred_path, meta_path)

    try:
        pred = load_pred_series(pred_path)
    except Exception as exc:
        _log_pred_from(
            "MISS", reason="unreadable", path=str(pred_path), detail=str(exc)
        )
        raise

    if pred.empty:
        _log_pred_from("MISS", reason="empty", path=str(pred_path))
        raise ValueError(f"PRED_FROM MISS reason=empty path={pred_path}")

    label_path = _STATE.get("label_from")
    if label_path is None and meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(meta, dict) and meta.get("label_path"):
                label_path = Path(str(meta["label_path"]))
        except (OSError, json.JSONDecodeError):
            label_path = None
    if label_path is None:
        sibling = _label_sidecar_path(pred_path)
        if sibling.is_file():
            label_path = sibling

    if label_path is None:
        _log_pred_from("MISS", reason="missing_label", path=str(pred_path))
        raise ValueError(
            "PRED_FROM MISS reason=missing_label: offline IC/IR needs --label-from "
            f"(or {pred_path.stem}.label{pred_path.suffix} sidecar)"
        )

    label_path = Path(label_path)
    try:
        label = load_label_series(label_path)
    except Exception as exc:
        _log_pred_from(
            "MISS",
            reason="label_unreadable",
            path=str(pred_path),
            label=str(label_path),
            detail=str(exc),
        )
        raise

    if label.empty:
        _log_pred_from("MISS", reason="label_empty", path=str(label_path))
        raise ValueError(f"PRED_FROM MISS reason=label_empty path={label_path}")

    digest = md5_file(pred_path)
    _STATE["pred_path"] = str(pred_path)
    _STATE["pred_md5"] = digest
    _log_pred_from(
        "HIT",
        reason="ok",
        path=str(pred_path),
        pred_md5=digest,
        rows=len(pred),
        label=str(label_path),
    )
    return pred, label


def _build_pred_label() -> tuple[pd.Series, pd.Series]:
    """Heavy path: qlib init + handler + fit + predict. Separated so tests can mock."""
    # handler_init 之前一次性取 git 溯源（整次 sweep 共用）
    if "git_prov" not in _STATE:
        repo_root = _SCRIPT_DIR.parent
        _STATE["git_prov"] = capture_git_provenance(repo_root)

    import qlib
    from qlib.data.dataset import DatasetH
    from qlib.contrib.model import LGBModel

    from custom_handler import Alpha158CostKDJ
    from train_wiring import build_filtered_instruments

    _kernels = resolve_qlib_kernels()
    print(f"[qlib] kernels={_kernels} (QLIB_KERNELS, default 1)", flush=True)
    qlib.init(
        provider_uri="C:/Users/Thinkpad/.qlib/qlib_data/my_data",
        region="cn",
        kernels=_kernels,
    )

    segs = get_segments()
    # handler 覆盖三段 min start / max end。label 用 Ref($close,-2)，
    # 末尾 1-2 天 label 为 NaN 会被 dropna——与三月窗现行为一致。
    start_time, end_time = _handler_span(segs)
    fit_start, fit_end = segs["train"]

    instruments = build_filtered_instruments(
        start_time=start_time,
        end_time=end_time,
        exclude_stocks=list(_HANDLER_KEY_KNOBS["exclude_stocks"]),
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
        include_alpha158=bool(_HANDLER_KEY_KNOBS["include_alpha158"]),
        include_cost_kdj=bool(_HANDLER_KEY_KNOBS["include_cost_kdj"]),
        include_lz=bool(_HANDLER_KEY_KNOBS["include_lz"]),
    )
    dataset = DatasetH(handler=handler, segments=dict(segs))
    model = LGBModel(
        loss=str(_HANDLER_KEY_KNOBS["loss"]),
        num_boost_round=int(_HANDLER_KEY_KNOBS["num_boost_round"]),
        learning_rate=0.05,
        max_depth=6,
    )
    model.fit(dataset)

    pred = model.predict(dataset, "test")
    if isinstance(pred, pd.DataFrame):
        pred = pred.iloc[:, 0]
    label = dataset.prepare("test", col_set="label")
    if isinstance(label, pd.DataFrame):
        label = label.iloc[:, 0]
    pred = pred.dropna()
    label = label.dropna()
    print(
        f"[adapter] pred={len(pred)} label={len(label)} "
        f"days={pred.index.get_level_values(0).nunique()}",
        flush=True,
    )
    return pred, label


def _predict_once() -> tuple[pd.Series, pd.Series]:
    """构建 handler/dataset/model 一次，产出 (pred, label)（MultiIndex 对齐）。

    进程内缓存：首次 INIT_ONCE，后续同窗 ARM_ONLY。set_segments 清缓存防跨窗硬共享。
    """
    if "pred" in _STATE:
        key = _STATE.get("shared_handler_cache_key") or make_shared_handler_cache_key()
        _STATE["shared_handler_cache_key"] = key
        _STATE["arm_mode"] = "ARM_ONLY"
        _STATE["last_timings"] = {
            "total_seconds": 0.0,
            "nodes": [{"name": "arm_only", "seconds": 0.0}],
        }
        print(f"[adapter] ARM_ONLY key={key}", flush=True)
        return _STATE["pred"], _STATE["label"]

    key = make_shared_handler_cache_key()
    t0 = time.perf_counter()
    pred, label = _build_pred_label()
    elapsed = time.perf_counter() - t0
    _STATE["pred"], _STATE["label"] = pred, label
    _STATE["shared_handler_cache_key"] = key
    _STATE["arm_mode"] = "INIT_ONCE"
    # Node names init_once / handler_init are stable — sweep parent (P0-5) peels them.
    _STATE["last_timings"] = {
        "total_seconds": float(elapsed),
        "nodes": [
            {"name": "handler_init", "seconds": float(elapsed)},
            {"name": "init_once", "seconds": float(elapsed)},
        ],
    }
    print(f"[adapter] INIT_ONCE key={key}", flush=True)
    return _STATE["pred"], _STATE["label"]


def _predict_once() -> tuple[pd.Series, pd.Series]:
    """构建 handler/dataset/model 一次，产出 (pred, label)（MultiIndex 对齐）。

    进程内缓存：首次 INIT_ONCE，后续同窗 ARM_ONLY。set_segments 清缓存防跨窗硬共享。
    ``--pred-from`` HIT 跳过 ``_build_pred_label``；MISS 明确失败（不 dirty 回落）。
    """
    if "pred" in _STATE:
        key = _STATE.get("shared_handler_cache_key") or make_shared_handler_cache_key()
        _STATE["shared_handler_cache_key"] = key
        _STATE["arm_mode"] = "ARM_ONLY"
        _STATE["last_timings"] = {
            "total_seconds": 0.0,
            "nodes": [{"name": "arm_only", "seconds": 0.0}],
        }
        print(f"[adapter] ARM_ONLY key={key}", flush=True)
        return _STATE["pred"], _STATE["label"]

    key = make_shared_handler_cache_key()
    pred_from = _STATE.get("pred_from")
    if pred_from is not None:
        t0 = time.perf_counter()
        pred, label = _load_pred_from_disk()
        elapsed = time.perf_counter() - t0
        _STATE["pred"], _STATE["label"] = pred, label
        _STATE["shared_handler_cache_key"] = key
        _STATE["arm_mode"] = "PRED_FROM"
        _STATE["last_timings"] = {
            "total_seconds": float(elapsed),
            "nodes": [{"name": "pred_from", "seconds": float(elapsed)}],
        }
        print(f"[adapter] PRED_FROM key={key}", flush=True)
        return _STATE["pred"], _STATE["label"]

    t0 = time.perf_counter()
    pred, label = _build_pred_label()
    elapsed = time.perf_counter() - t0
    _STATE["pred"], _STATE["label"] = pred, label
    _STATE["shared_handler_cache_key"] = key
    _STATE["arm_mode"] = "INIT_ONCE"
    # Node names init_once / handler_init are stable — sweep parent (P0-5) peels them.
    _STATE["last_timings"] = {
        "total_seconds": float(elapsed),
        "nodes": [
            {"name": "handler_init", "seconds": float(elapsed)},
            {"name": "init_once", "seconds": float(elapsed)},
        ],
    }
    pred_out = _STATE.get("pred_out")
    if pred_out is not None:
        written, digest = write_pred_artifact(
            pred,
            pred_out,
            label=label,
            segments=get_segments(),
            shared_handler_cache_key=key,
        )
        _STATE["pred_path"] = str(written)
        _STATE["pred_md5"] = digest
        print(
            f"[adapter] pred_out path={written} pred_md5={digest}",
            flush=True,
        )
    print(f"[adapter] INIT_ONCE key={key}", flush=True)
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
    arm_mode = _STATE.get("arm_mode") or "ARM_ONLY"
    cache_key = _STATE.get("shared_handler_cache_key") or make_shared_handler_cache_key(segs)
    timings = _STATE.get("last_timings") or {
        "total_seconds": None,
        "nodes": [],
        "unknown": True,
    }
    pred_path = _STATE.get("pred_path") or ""
    pred_md5 = _STATE.get("pred_md5")
    data: dict[str, Any] = {
        "arm_mode": arm_mode,
        "shared_handler_cache_key": cache_key,
    }
    if pred_md5:
        data["pred_md5"] = pred_md5
    return {
        "ic": ic,
        "ir": ir,
        "notes": f"ic=日命中率; ir=名单等权次日收益年化(未扣费); days={len(series)}",
        "pred_path": pred_path,
        "pred_md5": pred_md5 or "",
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
        "data": data,
        "timings": timings,
    }
