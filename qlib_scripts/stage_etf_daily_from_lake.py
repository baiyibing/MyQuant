# -*- coding: utf-8 -*-
"""Hive ETF 日线 front → dump_bin staging（每只一个 parquet）。

不写 ~/.qlib。窗口锁定 2020-01-02..2026-10-13。
湖 time 是 UTC 毫秒，转到 Asia/Shanghai 再取日期。

VWAP：amount/(volume×100) 是未复权均价（front 的 amount/volume 与 none 相同，
OHLC 才是前复权）。写入的 vwap 再乘 front_close/none_close，使均价与前复权
收盘同一口径。证据由 build_etf_qlib 在灌库前核对。
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Sequence

import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
_MY_SCRIPTS = _SCRIPTS.parent / "my_scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
if str(_MY_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_MY_SCRIPTS))
from data_root import resolve_etf_1d_none  # noqa: E402
from stage_1min_from_lake import lake_partition_to_qlib_code, qlib_code_to_partition  # noqa: E402

WINDOW_START = "2020-01-02"
WINDOW_END = "2026-10-13"
DEFAULT_STAGING = Path(r"D:\qlib_data\_staging_etf_1d")
DEFAULT_MAX_WORKERS = 8
OHLCV = ("open", "high", "low", "close", "volume", "amount")
DUMP_FIELDS = ("open", "high", "low", "close", "volume", "amount", "vwap")
STATS_NAME = "_stage_stats.json"


def resolve_etf_front_root(explicit: str | Path | None = None) -> Path:
    """front 树。显式路径优先；否则取 resolve_etf_1d_none() 的同级 dividend_type=front。"""
    if explicit:
        return Path(explicit)
    none_root = resolve_etf_1d_none()
    if none_root.name != "dividend_type=none":
        raise ValueError(f"ETF none 根应为 dividend_type=none，收到: {none_root}")
    return none_root.parent / "dividend_type=front"


def shanghai_dates(time_values: pd.Series) -> pd.Series:
    """UTC 毫秒 → 上海日期（当日 08:00，归一到 00:00）。"""
    dates = pd.to_datetime(time_values, unit="ms", utc=True).dt.tz_convert("Asia/Shanghai")
    return dates.dt.normalize().dt.tz_localize(None)


def raw_vwap(amount: pd.Series, volume: pd.Series) -> pd.Series:
    denom = volume.astype("float64") * 100.0
    return (amount.astype("float64") / denom).where(denom > 0)


def scale_vwap_to_front(raw: pd.Series, front_close: pd.Series, none_close: pd.Series) -> pd.Series:
    """把未复权 VWAP 乘上当日 close 的前复权因子。"""
    factor = front_close.astype("float64") / none_close.astype("float64")
    return raw.astype("float64") * factor


def basis_evidence(
    front: pd.DataFrame,
    none: pd.DataFrame,
    *,
    start: str = WINDOW_START,
    end: str = WINDOW_END,
) -> dict:
    """front OHLC 与 none 的 amount/volume 是否同一复权口径。"""
    front_n = _normalize_lake(front)
    none_n = _normalize_lake(none)
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    front_v = front_n.loc[_valid_mask(front_n)]
    none_v = none_n.loc[_valid_mask(none_n), ["date", "close", "volume", "amount"]]
    front_v = front_v.loc[(front_v["date"] >= start_ts) & (front_v["date"] <= end_ts)]
    none_v = none_v.loc[(none_v["date"] >= start_ts) & (none_v["date"] <= end_ts)]
    merged = front_v.merge(none_v, on="date", suffixes=("_f", "_n"))
    if merged.empty:
        return {"rows": 0}
    amount_ratio = merged["amount_f"] / merged["amount_n"]
    volume_ratio = merged["volume_f"] / merged["volume_n"]
    price_ratio = merged["close_f"] / merged["close_n"]
    raw = raw_vwap(merged["amount_f"], merged["volume_f"])
    scaled = scale_vwap_to_front(raw, merged["close_f"], merged["close_n"])
    raw_gap = (raw / merged["close_f"] - 1.0).abs()
    scaled_gap = (scaled / merged["close_f"] - 1.0).abs()
    return {
        "rows": int(len(merged)),
        "px_start": float(price_ratio.iloc[0]),
        "px_end": float(price_ratio.iloc[-1]),
        "amt_ratio_median": float(amount_ratio.median()),
        "vol_ratio_median": float(volume_ratio.median()),
        "raw_gap_median": float(raw_gap.median()),
        "scaled_gap_median": float(scaled_gap.median()),
    }


def basis_passes(evidence: dict) -> bool:
    """amount/volume 未复权、缩放后的 VWAP 贴近 front 收盘。价格有漂移时，缩放必须把缺口缩小。"""
    if int(evidence.get("rows", 0)) < 2:
        return False
    if abs(float(evidence["amt_ratio_median"]) - 1.0) > 0.01:
        return False
    if abs(float(evidence["vol_ratio_median"]) - 1.0) > 0.01:
        return False
    if float(evidence["scaled_gap_median"]) >= 0.02:
        return False
    drifted = abs(float(evidence["px_start"]) - float(evidence["px_end"])) > 0.01
    if drifted and float(evidence["raw_gap_median"]) <= float(evidence["scaled_gap_median"]):
        return False
    return True


def _normalize_lake(frame: pd.DataFrame) -> pd.DataFrame:
    if "time" not in frame.columns:
        raise ValueError("湖 parquet 缺少 time 列")
    missing = [col for col in OHLCV if col not in frame.columns]
    if missing:
        raise ValueError(f"湖 parquet 缺少列: {missing}")
    out = pd.DataFrame({col: pd.to_numeric(frame[col], errors="coerce") for col in OHLCV})
    out.insert(0, "date", shanghai_dates(frame["time"]))
    out = out.dropna(subset=["date"])
    out = out.drop_duplicates("date", keep="last").sort_values("date")
    return out.reset_index(drop=True)


def _valid_mask(frame: pd.DataFrame) -> pd.Series:
    return frame["close"].gt(0) & frame["volume"].gt(0)


def prepare_frame(
    front: pd.DataFrame,
    none: pd.DataFrame,
    *,
    start: str = WINDOW_START,
    end: str = WINDOW_END,
) -> tuple[pd.DataFrame, dict]:
    """裁窗、丢占位 0、把 VWAP 对齐到 front 收盘。空结果表示这只不写文件。"""
    front_n = _normalize_lake(front)
    none_n = _normalize_lake(none)
    front_valid = front_n.loc[_valid_mask(front_n)].copy()
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    stats = {
        "before_window": int((front_valid["date"] < start_ts).sum()),
        "beyond_window": int((front_valid["date"] > end_ts).sum()),
        "dropped_placeholder": int((~_valid_mask(front_n)).sum()),
        "dropped_no_none": 0,
    }
    window = front_valid.loc[(front_valid["date"] >= start_ts) & (front_valid["date"] <= end_ts)].copy()
    none_valid = none_n.loc[_valid_mask(none_n), ["date", "close"]].rename(columns={"close": "none_close"})
    merged = window.merge(none_valid, on="date", how="left")
    stats["dropped_no_none"] = int(merged["none_close"].isna().sum() + merged["none_close"].le(0).sum())
    merged = merged.loc[merged["none_close"].gt(0)].copy()
    if merged.empty:
        return merged.iloc[0:0], stats
    merged["vwap"] = scale_vwap_to_front(
        raw_vwap(merged["amount"], merged["volume"]),
        merged["close"],
        merged["none_close"],
    )
    out = merged[["date", *DUMP_FIELDS]].reset_index(drop=True)
    return out, stats


def _none_partition(front_partition: Path, none_root: Path | None) -> Path:
    if none_root is not None:
        return Path(none_root) / front_partition.name
    return front_partition.parent.parent / "dividend_type=none" / front_partition.name


def stage_symbol(
    partition: Path,
    staging_dir: Path,
    *,
    start: str = WINDOW_START,
    end: str = WINDOW_END,
    none_root: Path | None = None,
) -> tuple[Path | None, dict]:
    """写 sh510300.parquet。无可写行时不留空文件。"""
    code = lake_partition_to_qlib_code(partition.name)
    front_path = partition / "data.parquet"
    none_path = _none_partition(partition, none_root) / "data.parquet"
    empty_stats = {"before_window": 0, "beyond_window": 0, "dropped_placeholder": 0, "dropped_no_none": 0, "code": code}
    if not front_path.is_file() or not none_path.is_file():
        if not none_path.is_file():
            empty_stats["missing_none"] = 1
        return None, empty_stats
    frame, stats = prepare_frame(
        pd.read_parquet(front_path),
        pd.read_parquet(none_path),
        start=start,
        end=end,
    )
    stats["code"] = code
    if frame.empty:
        return None, stats
    frame.insert(1, "symbol", code)
    dest = Path(staging_dir) / f"{code.lower()}.parquet"
    dest.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(dest, index=False)
    return dest, stats


def _stage_job(item: tuple[str, str, str, str, str | None]) -> tuple[str | None, dict]:
    partition, staging_dir, start, end, none_root = item
    dest, stats = stage_symbol(
        Path(partition),
        Path(staging_dir),
        start=start,
        end=end,
        none_root=Path(none_root) if none_root else None,
    )
    return (str(dest) if dest is not None else None), stats


def stage_lake(
    lake_root: Path,
    staging_dir: Path,
    *,
    start: str = WINDOW_START,
    end: str = WINDOW_END,
    none_root: Path | None = None,
    max_workers: int = 1,
) -> dict:
    root = Path(lake_root)
    partitions = sorted(p for p in root.glob("symbol=*") if (p / "data.parquet").is_file())
    staging = Path(staging_dir)
    staging.mkdir(parents=True, exist_ok=True)
    none_text = str(none_root) if none_root else None
    jobs = [(str(p), str(staging), start, end, none_text) for p in partitions]
    written: list[str] = []
    totals = {"before_window": 0, "beyond_window": 0, "dropped_placeholder": 0, "dropped_no_none": 0, "skipped_empty": 0}
    workers = max(1, min(DEFAULT_MAX_WORKERS, int(max_workers)))

    def _take(dest: str | None, stats: dict) -> None:
        if dest:
            written.append(dest)
        else:
            totals["skipped_empty"] += 1
        for key in ("before_window", "beyond_window", "dropped_placeholder", "dropped_no_none"):
            totals[key] += int(stats.get(key, 0))

    if workers == 1 or len(jobs) <= 1:
        for i, job in enumerate(jobs, 1):
            dest, stats = _stage_job(job)
            _take(dest, stats)
            if i % 200 == 0 or i == len(jobs):
                print(f"stage {i}/{len(jobs)} written={len(written)}", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for i, (dest, stats) in enumerate(pool.map(_stage_job, jobs, chunksize=8), 1):
                _take(dest, stats)
                if i % 200 == 0 or i == len(jobs):
                    print(f"stage {i}/{len(jobs)} written={len(written)}", flush=True)
    payload = {
        "written": len(written),
        "files": written,
        "window": [start, end],
        **totals,
    }
    (staging / STATS_NAME).write_text(json.dumps({k: v for k, v in payload.items() if k != "files"}), encoding="utf-8")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage ETF daily front parquet for qlib dump_bin")
    parser.add_argument("--lake-root", type=Path, default=None, help="dividend_type=front；缺省由 OSKH_SOURCE_PARQUET_ROOT 推导")
    parser.add_argument("--none-root", type=Path, default=None, help="dividend_type=none；缺省为 front 的同级目录")
    parser.add_argument("--staging-dir", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--start", default=WINDOW_START)
    parser.add_argument("--end", default=WINDOW_END)
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    lake_root = resolve_etf_front_root(args.lake_root)
    payload = stage_lake(
        lake_root,
        args.staging_dir,
        start=args.start,
        end=args.end,
        none_root=args.none_root,
        max_workers=args.max_workers,
    )
    print(
        f"staged {payload['written']} files → {args.staging_dir} "
        f"beyond_window={payload['beyond_window']} before_window={payload['before_window']} "
        f"skipped_empty={payload['skipped_empty']}",
        flush=True,
    )
    if payload["beyond_window"]:
        print(
            f"湖在 {args.end} 之后还有 {payload['beyond_window']} 根有效 K；v1 不延长窗口",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    raise SystemExit(main())
