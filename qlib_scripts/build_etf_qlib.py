# -*- coding: utf-8 -*-
"""ETF 日线 front → 独立 qlib provider ~/.qlib/qlib_data/my_data_etf。

不调用 refresh_mydata.py / patch_index_data.py，不写股票 my_data。
dump 只用 dump_all，max_workers 钉死 8。日历门禁在 dump 之前。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
_REPO = _SCRIPTS.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from stage_etf_daily_from_lake import (  # noqa: E402
    DUMP_FIELDS,
    STATS_NAME,
    WINDOW_END,
    WINDOW_START,
    basis_evidence,
    basis_passes,
    lake_partition_to_qlib_code,
    qlib_code_to_partition,
    resolve_etf_front_root,
)

DUMP_BIN = _SCRIPTS / "dump_bin.py"
STAGE_SCRIPT = _SCRIPTS / "stage_etf_daily_from_lake.py"
REQUIRED_WORKERS = 8
CALENDAR_STEM = "sh510300"
VWAP_STEMS = ("sh510300", "sh510050", "sz159915", "sh518880")
READBACK_CODES = ("SH510050", "SH510300", "SZ159915", "SH518880")
EARLY_END_CODE = "SH512390"
ETF_FULL_MAX_START = "2022-01-01"
ETF_FULL_MIN_BARS = 500
ETF_FULL_MIN_END = "2026-10-01"
VWAP_MEDIAN_MAX = 0.02
VWAP_DRIFT_MAX = 0.02
CLOSE_TOL = 1e-4
SURVIVORSHIP_NOTE = (
    "etf_full 要求 2022-01-01 前已上市、窗口内至少 500 根、末日仍在 2026-10-01 及之后。"
    "更晚上市和更早停止交易的 ETF 被排除，末日条件带来幸存者偏差。"
)


class BuildEtfError(RuntimeError):
    """编排或门禁失败。失败发生在清空和 dump 之前时，不得改动目标目录。"""


def default_qlib_dir() -> Path:
    return Path.home() / ".qlib" / "qlib_data" / "my_data_etf"


def default_protected() -> tuple[Path, ...]:
    base = Path.home() / ".qlib" / "qlib_data"
    return (base / "my_data", base / "my_data_1min")


def default_meta_dir(qlib_dir: Path) -> Path:
    return Path(qlib_dir).expanduser().resolve().parent / "my_data_etf_meta"


def realpath(path: Path) -> Path:
    text = os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(str(path)))))
    return Path(text)


def path_relation(target: Path, protected: Path) -> str | None:
    """equal / ancestor / descendant。my_data_etf 与 my_data 不是前缀关系。"""
    left = realpath(target)
    right = realpath(protected)
    if left == right:
        return "equal"
    try:
        left.relative_to(right)
        return "descendant"
    except ValueError:
        pass
    try:
        right.relative_to(left)
        return "ancestor"
    except ValueError:
        return None


def assert_target_allowed(target: Path, protected: Sequence[Path]) -> None:
    for item in protected:
        relation = path_relation(target, item)
        if relation is not None:
            raise BuildEtfError(
                f"拒绝目标 {target}：与受保护目录 {item} 的关系是 {relation}。"
                "清空尚未执行。"
            )


def dir_nonempty(path: Path) -> bool:
    return path.exists() and any(path.iterdir())


@dataclass
class BuildConfig:
    lake_root: Path | None = None
    staging_dir: Path = field(default_factory=lambda: Path(r"D:\qlib_data\_staging_etf_1d"))
    qlib_dir: Path = field(default_factory=default_qlib_dir)
    meta_dir: Path | None = None
    max_workers: int = REQUIRED_WORKERS
    dry_run: bool = False
    wipe_qlib_dir: bool = False
    verify: bool = False
    protected: tuple[Path, ...] = ()
    python: str = field(default_factory=lambda: sys.executable)

    def resolved_protected(self) -> tuple[Path, ...]:
        return self.protected or default_protected()

    def resolved_lake(self) -> Path:
        return resolve_etf_front_root(self.lake_root)

    def resolved_meta(self) -> Path:
        return self.meta_dir if self.meta_dir is not None else default_meta_dir(self.qlib_dir)


def dump_argv(cfg: BuildConfig) -> list[str]:
    fields = ",".join(DUMP_FIELDS)
    argv = [
        cfg.python,
        str(DUMP_BIN),
        "dump_all",
        f"--data_path={cfg.staging_dir}",
        f"--qlib_dir={cfg.qlib_dir}",
        "--file_suffix=.parquet",
        f"--max_workers={REQUIRED_WORKERS}",
        "--exclude_fields=symbol",
        f"--include_fields={fields}",
    ]
    if any(part == "dump_update" or part.startswith("dump_update") for part in argv):
        raise BuildEtfError("禁止 dump_update")
    if f"--max_workers={REQUIRED_WORKERS}" not in argv:
        raise BuildEtfError(f"dump max_workers 必须为 {REQUIRED_WORKERS}")
    return argv


def stage_argv(cfg: BuildConfig) -> list[str]:
    return [
        cfg.python,
        str(STAGE_SCRIPT),
        "--lake-root",
        str(cfg.resolved_lake()),
        "--staging-dir",
        str(cfg.staging_dir),
        "--start",
        WINDOW_START,
        "--end",
        WINDOW_END,
        "--max-workers",
        str(REQUIRED_WORKERS),
    ]


def _run(argv: list[str]) -> None:
    print("RUN " + " ".join(argv), flush=True)
    subprocess.check_call(argv, cwd=str(_REPO))


def default_stage(cfg: BuildConfig) -> None:
    _run(stage_argv(cfg))


def default_dump(cfg: BuildConfig) -> None:
    _run(dump_argv(cfg))


def default_wipe(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def load_calendar(staging_dir: Path) -> pd.DatetimeIndex:
    path = Path(staging_dir) / f"{CALENDAR_STEM}.parquet"
    if not path.is_file():
        raise BuildEtfError(f"缺少日历基准 {path.name}")
    frame = pd.read_parquet(path, columns=["date"])
    dates = pd.DatetimeIndex(pd.to_datetime(frame["date"])).normalize().unique().sort_values()
    if len(dates) == 0:
        raise BuildEtfError("510300 日历为空")
    weekends = dates[dates.weekday >= 5]
    if len(weekends):
        raise BuildEtfError(f"510300 日历含非交易日 {weekends[0].date()}")
    if dates.min() != pd.Timestamp(WINDOW_START) or dates.max() != pd.Timestamp(WINDOW_END):
        raise BuildEtfError(
            f"510300 日历范围 {dates.min().date()}..{dates.max().date()}，"
            f"窗口锁定 {WINDOW_START}..{WINDOW_END}"
        )
    return dates


def dates_outside(staging_dir: Path, calendar: pd.DatetimeIndex) -> dict[str, list[str]]:
    allowed = set(pd.DatetimeIndex(calendar).normalize())
    bad: dict[str, list[str]] = {}
    for path in sorted(Path(staging_dir).glob("*.parquet")):
        frame = pd.read_parquet(path, columns=["date"])
        got = pd.DatetimeIndex(pd.to_datetime(frame["date"])).normalize().unique()
        extra = [str(ts.date()) for ts in got if ts not in allowed]
        if extra:
            bad[path.name] = extra
    return bad


def ensure_calendar_subset(staging_dir: Path) -> pd.DatetimeIndex:
    calendar = load_calendar(staging_dir)
    extra = dates_outside(staging_dir, calendar)
    if extra:
        sample = next(iter(extra.items()))
        raise BuildEtfError(f"标的日期超出 510300 日历，例如 {sample[0]} {sample[1][:3]}")
    return calendar


def vwap_gap_stats(frame: pd.DataFrame) -> dict:
    gap = (frame["vwap"].astype("float64") / frame["close"].astype("float64") - 1.0).abs()
    early = gap[pd.to_datetime(frame["date"]) < pd.Timestamp("2021-01-01")]
    late = gap[pd.to_datetime(frame["date"]) >= pd.Timestamp("2026-01-01")]
    early_m = float(early.median()) if len(early) else float(gap.median())
    late_m = float(late.median()) if len(late) else float(gap.median())
    return {"median": float(gap.median()), "drift": abs(early_m - late_m), "rows": int(len(frame))}


def vwap_gap_ok(stats: dict) -> bool:
    return float(stats["median"]) < VWAP_MEDIAN_MAX and float(stats["drift"]) < VWAP_DRIFT_MAX


def ensure_staged_vwap(staging_dir: Path) -> list[dict]:
    reports = []
    for stem in VWAP_STEMS:
        path = Path(staging_dir) / f"{stem}.parquet"
        if not path.is_file():
            raise BuildEtfError(f"缺少 VWAP 验收标的 {path.name}")
        frame = pd.read_parquet(path, columns=["date", "close", "vwap"])
        stats = vwap_gap_stats(frame)
        stats["stem"] = stem
        reports.append(stats)
        if not vwap_gap_ok(stats):
            raise BuildEtfError(
                f"{stem} VWAP 与 front 收盘不同口径 median={stats['median']:.4f} drift={stats['drift']:.4f}"
            )
    return reports


def ensure_lake_basis(lake_root: Path) -> list[dict]:
    reports = []
    none_root = Path(lake_root).parent / "dividend_type=none"
    for code in READBACK_CODES:
        part = qlib_code_to_partition(code)
        front_path = Path(lake_root) / f"symbol={part}" / "data.parquet"
        none_path = none_root / f"symbol={part}" / "data.parquet"
        evidence = basis_evidence(pd.read_parquet(front_path), pd.read_parquet(none_path))
        evidence["code"] = code
        reports.append(evidence)
        if not basis_passes(evidence):
            raise BuildEtfError(f"{code} 复权口径未通过: {evidence}")
    return reports


def symbol_profile(path: Path, calendar: pd.DatetimeIndex) -> dict:
    frame = pd.read_parquet(path, columns=["date", "symbol"])
    dates = pd.DatetimeIndex(pd.to_datetime(frame["date"])).normalize().unique().sort_values()
    allowed = set(pd.DatetimeIndex(calendar).normalize())
    present = sum(1 for ts in dates if ts in allowed)
    code = str(frame["symbol"].iloc[0]).upper()
    return {
        "code": code,
        "start": dates.min(),
        "end": dates.max(),
        "bars": int(len(dates)),
        "missing_ratio": 1.0 - present / len(allowed),
        "has_window_start": pd.Timestamp(WINDOW_START) in set(dates),
    }


def is_etf_full(
    profile: dict,
    *,
    min_bars: int = ETF_FULL_MIN_BARS,
    min_end: str = ETF_FULL_MIN_END,
    max_start: str = ETF_FULL_MAX_START,
) -> bool:
    """2022-01-01 前上市、仍交易到 2026-10，且窗口内 K 线不少于 500。"""
    return bool(
        pd.Timestamp(profile["start"]) <= pd.Timestamp(max_start)
        and pd.Timestamp(profile["end"]) >= pd.Timestamp(min_end)
        and int(profile["bars"]) >= min_bars
    )


def rewrite_etf_full_from_gaps(report: Path, qlib_dir: Path) -> int:
    """用已有缺口表重写 instruments/etf_full.txt，不重灌 bin。"""
    frame = pd.read_csv(report)
    selected = [row for row in frame.to_dict("records") if is_etf_full(row)]
    lines = [
        f"{str(row['code']).upper()}\t{pd.Timestamp(row['start']).strftime('%Y-%m-%d')}\t"
        f"{pd.Timestamp(row['end']).strftime('%Y-%m-%d')}"
        for row in selected
    ]
    dest = Path(qlib_dir) / "instruments" / "etf_full.txt"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    print(f"etf_full {len(selected)} → {dest}", flush=True)
    print(SURVIVORSHIP_NOTE, flush=True)
    return len(selected)


def summarize_ratios(ratios: Sequence[float]) -> dict:
    series = pd.Series(list(ratios), dtype="float64")
    if series.empty:
        return {"n": 0, "mean": None, "median": None, "max": None}
    return {
        "n": int(len(series)),
        "mean": float(series.mean()),
        "median": float(series.median()),
        "max": float(series.max()),
    }


def write_universe(staging_dir: Path, qlib_dir: Path, meta_dir: Path, calendar: pd.DatetimeIndex) -> dict:
    profiles = [symbol_profile(path, calendar) for path in sorted(Path(staging_dir).glob("*.parquet"))]
    for profile in profiles:
        profile["in_etf_full"] = is_etf_full(profile)
    selected = [profile for profile in profiles if profile["in_etf_full"]]
    instruments = Path(qlib_dir) / "instruments"
    instruments.mkdir(parents=True, exist_ok=True)
    lines = [
        f"{profile['code']}\t{pd.Timestamp(profile['start']).strftime('%Y-%m-%d')}\t"
        f"{pd.Timestamp(profile['end']).strftime('%Y-%m-%d')}"
        for profile in selected
    ]
    (instruments / "etf_full.txt").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    summary = summarize_ratios([profile["missing_ratio"] for profile in selected])
    meta_dir.mkdir(parents=True, exist_ok=True)
    report = meta_dir / "etf_full_gaps.csv"
    pd.DataFrame(profiles).to_csv(report, index=False)
    print(SURVIVORSHIP_NOTE, flush=True)
    print(
        f"etf_full {len(selected)} / staged {len(profiles)} "
        f"missing_ratio mean={summary['mean']} median={summary['median']} max={summary['max']}",
        flush=True,
    )
    print(f"gap report {report}", flush=True)
    return {"etf_full": len(selected), "staged": len(profiles), "missing": summary, "report": str(report)}


def _lake_close_ends(lake_root: Path, code: str) -> tuple[float, float]:
    part = qlib_code_to_partition(code)
    frame = pd.read_parquet(Path(lake_root) / f"symbol={part}" / "data.parquet")
    dates = (
        pd.to_datetime(frame["time"], unit="ms", utc=True)
        .dt.tz_convert("Asia/Shanghai")
        .dt.normalize()
        .dt.tz_localize(None)
    )
    work = frame.copy()
    work["date"] = dates
    valid = work.loc[work["close"].gt(0) & work["volume"].gt(0)]
    valid = valid.loc[(valid["date"] >= WINDOW_START) & (valid["date"] <= WINDOW_END)].sort_values("date")
    if valid.empty:
        raise BuildEtfError(f"{code} 湖内窗口无有效收盘")
    return float(valid["close"].iloc[0]), float(valid["close"].iloc[-1])


def _feature_close(frame: pd.DataFrame, code: str) -> pd.Series:
    if not isinstance(frame.index, pd.MultiIndex):
        series = frame.iloc[:, 0]
    elif code in set(frame.index.get_level_values(0)):
        series = frame.xs(code, level=0).iloc[:, 0]
    else:
        series = frame.xs(code, level=1).iloc[:, 0]
    return series.dropna().sort_index()


def verify_readback(qlib_dir: Path, lake_root: Path) -> None:
    import qlib
    from qlib.constant import REG_CN
    from qlib.data import D

    qlib.init(provider_uri=str(qlib_dir), region=REG_CN, kernels=1)
    calendar = pd.DatetimeIndex(D.calendar(start_time=WINDOW_START, end_time=WINDOW_END))
    if str(pd.Timestamp(calendar.min()).date()) != WINDOW_START or str(pd.Timestamp(calendar.max()).date()) != WINDOW_END:
        raise BuildEtfError(f"读回日历 {calendar.min()}..{calendar.max()} 长度 {len(calendar)}")
    if (calendar.weekday >= 5).any():
        raise BuildEtfError("读回日历含周末")
    print(f"calendar {calendar.min().date()}..{calendar.max().date()} days={len(calendar)}", flush=True)
    all_text = (Path(qlib_dir) / "instruments" / "all.txt").read_text(encoding="utf-8")
    listed = {}
    for line in all_text.splitlines():
        if not line.strip():
            continue
        code, _start, end = line.split("\t")
        listed[code.upper()] = end
    for code in READBACK_CODES:
        expected_first, expected_last = _lake_close_ends(lake_root, code)
        got = D.features([code], ["$close"], start_time=WINDOW_START, end_time=WINDOW_END)
        series = _feature_close(got, code)
        if abs(float(series.iloc[0]) - expected_first) > CLOSE_TOL or abs(float(series.iloc[-1]) - expected_last) > CLOSE_TOL:
            raise BuildEtfError(
                f"{code} 读回 {float(series.iloc[0])}..{float(series.iloc[-1])} "
                f"湖 {expected_first}..{expected_last}"
            )
        print(f"readback {code} {float(series.iloc[0])} -> {float(series.iloc[-1])}", flush=True)
    from stage_etf_daily_from_lake import shanghai_dates

    early_part = qlib_code_to_partition(EARLY_END_CODE)
    early_file = Path(lake_root) / f"symbol={early_part}" / "data.parquet"
    if early_file.is_file() and EARLY_END_CODE in listed:
        raw = pd.read_parquet(early_file, columns=["time", "close", "volume"])
        dates = shanghai_dates(raw["time"])
        valid_dates = dates.loc[raw["close"].gt(0) & raw["volume"].gt(0)]
        valid_dates = valid_dates.loc[(valid_dates >= WINDOW_START) & (valid_dates <= WINDOW_END)]
        last = pd.Timestamp(valid_dates.max()).strftime("%Y-%m-%d")
        if listed[EARLY_END_CODE] != last:
            raise BuildEtfError(f"{EARLY_END_CODE} 登记末日 {listed[EARLY_END_CODE]}，湖内最后有效日 {last}")
        if last == WINDOW_END:
            raise BuildEtfError(f"{EARLY_END_CODE} 不应登记到日历末日")
        print(f"{EARLY_END_CODE} instrument end {listed[EARLY_END_CODE]}", flush=True)
    zero_hits = []
    for part in Path(lake_root).glob("symbol=*"):
        data_path = part / "data.parquet"
        if not data_path.is_file():
            continue
        raw = pd.read_parquet(data_path, columns=["time", "close", "volume"])
        dates = shanghai_dates(raw["time"])
        valid = raw["close"].gt(0) & raw["volume"].gt(0) & dates.ge(WINDOW_START) & dates.le(WINDOW_END)
        if not bool(valid.any()):
            code = lake_partition_to_qlib_code(part.name)
            if code in listed:
                zero_hits.append(code)
    if zero_hits:
        raise BuildEtfError(f"全零代码进入 all.txt: {zero_hits[:8]}")
    print(f"all.txt {len(listed)} zero_codes_excluded ok", flush=True)


def execute(
    cfg: BuildConfig,
    *,
    stage_fn: Callable[[BuildConfig], None] | None = None,
    dump_fn: Callable[[BuildConfig], None] | None = None,
    wipe_fn: Callable[[Path], None] | None = None,
) -> int:
    stage_fn = default_stage if stage_fn is None else stage_fn
    dump_fn = default_dump if dump_fn is None else dump_fn
    wipe_fn = default_wipe if wipe_fn is None else wipe_fn
    assert_target_allowed(cfg.qlib_dir, cfg.resolved_protected())
    if cfg.max_workers != REQUIRED_WORKERS:
        raise BuildEtfError(f"max_workers 必须为 {REQUIRED_WORKERS}，收到 {cfg.max_workers}")
    lake = cfg.resolved_lake()
    if cfg.dry_run:
        print(f"lake {lake}", flush=True)
        print(f"staging {cfg.staging_dir}", flush=True)
        print(f"qlib {cfg.qlib_dir}", flush=True)
        print("RUN " + " ".join(stage_argv(cfg)), flush=True)
        print("RUN " + " ".join(dump_argv(cfg)), flush=True)
        print("dry-run：不 stage、不清空、不 dump", flush=True)
        return 0
    if cfg.wipe_qlib_dir:
        print(f"wipe {cfg.qlib_dir}", flush=True)
        wipe_fn(cfg.qlib_dir)
    elif dir_nonempty(cfg.qlib_dir):
        raise BuildEtfError(f"{cfg.qlib_dir} 非空。--wipe-qlib-dir 才会清掉半成品后重灌")
    stage_fn(cfg)
    stats_path = Path(cfg.staging_dir) / STATS_NAME
    if stats_path.is_file():
        print("stage_stats " + stats_path.read_text(encoding="utf-8"), flush=True)
    calendar = ensure_calendar_subset(cfg.staging_dir)
    print(f"calendar gate {calendar.min().date()}..{calendar.max().date()} days={len(calendar)}", flush=True)
    vwap_report = ensure_staged_vwap(cfg.staging_dir)
    print("staged vwap " + json.dumps(vwap_report), flush=True)
    basis = ensure_lake_basis(lake)
    print("vwap basis " + json.dumps(basis), flush=True)
    cfg.resolved_meta().mkdir(parents=True, exist_ok=True)
    (cfg.resolved_meta() / "vwap_basis.json").write_text(json.dumps(basis, indent=2), encoding="utf-8")
    dump_fn(cfg)
    universe = write_universe(cfg.staging_dir, cfg.qlib_dir, cfg.resolved_meta(), calendar)
    print(f"universe {json.dumps({k: v for k, v in universe.items() if k != 'report'})}", flush=True)
    if cfg.verify:
        verify_readback(cfg.qlib_dir, lake)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build ~/.qlib/qlib_data/my_data_etf from ETF daily front")
    parser.add_argument("--lake-root", type=Path, default=None)
    parser.add_argument("--staging-dir", type=Path, default=Path(r"D:\qlib_data\_staging_etf_1d"))
    parser.add_argument("--qlib-dir", type=Path, default=None)
    parser.add_argument("--meta-dir", type=Path, default=None)
    parser.add_argument("--max-workers", type=int, default=REQUIRED_WORKERS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--wipe-qlib-dir", action="store_true")
    parser.add_argument("--skip-verify", action="store_true")
    return parser


def config_from_args(argv: Sequence[str] | None = None) -> BuildConfig:
    args = build_parser().parse_args(argv)
    return BuildConfig(
        lake_root=args.lake_root,
        staging_dir=args.staging_dir,
        qlib_dir=args.qlib_dir or default_qlib_dir(),
        meta_dir=args.meta_dir,
        max_workers=args.max_workers,
        dry_run=bool(args.dry_run),
        wipe_qlib_dir=bool(args.wipe_qlib_dir),
        verify=not bool(args.skip_verify),
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return execute(config_from_args(argv))
    except BuildEtfError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    raise SystemExit(main())
