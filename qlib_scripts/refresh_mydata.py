# -*- coding: utf-8 -*-
"""my_data 全量刷新编排器（M1）：merge → dump_all(8) → patch_index。

把 2026-09-13 手工串起来的三件套固化成一条命令。现有脚本接口不变，本脚本只
用子进程调用它们。硬约束见 docs/plan-midterm-m1m4m2m3-2026-09-13.md §0 与
my_docs/提示词-qlib-bin刷新.md（2026-09-14 / **2026-09-15** 实踩）：

- dump_all 必须 --max_workers 8（禁止 16）
- 禁止 dump_update；日历末日不变（纠错/赢筹浮点）也必须 dump_all
- 指数不得留在 instruments/all.txt（由 patch_index_data 第 4 步挪走）
- ~/.qlib 数据只准经本编排器改动；换目录前自动备份 my_data_backup_YYYYMMDD_pre_*
- 半成品 dump 目录必须先删再重灌（--wipe-new-qlib-dir）
- CSV 里 Windows NaN（-1.#J / -1.#IND）在 merge/dump 收成 NaN；OHLC 出现则中止
- 扫描报告按列汇总（赢筹干净 vs 只剩 vwap）；swap 后抽样 $winratio ∈ [0,1]

用法::

    python qlib_scripts/refresh_mydata.py --dry-run
    python qlib_scripts/refresh_mydata.py --force   # 退市数超预期时才需要
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Iterable, Sequence

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent

DEFAULT_ARCHIVE_DIR = Path.home() / ".qlib/qlib_data/my_data_20260410_archived"
DEFAULT_CSV_DIR = Path("F:/qlibdata")
DEFAULT_QLIB_DIR = Path.home() / ".qlib/qlib_data/my_data"
DEFAULT_LAKE_INDEX_ROOT = Path("F:/stock_data/index/period=1d/dividend_type=none")
DEFAULT_LAKE_SYMBOL = "000001_SH"
DEFAULT_MAX_WORKERS = 8  # 硬约束：禁止 16
DEFAULT_EXPECTED_DELIST_MAX = 50
DEFAULT_OFFSITE_DIRS = ("F:/", "G:/")
WIN_7Z = Path(r"C:\Program Files\7-Zip\7z.exe")
MIN_DUMP_FREE_GB = 3.0
MIN_STAGING_FREE_GB = 2.0

# 指数代码形态：SH000xxx / SZ399xxx（训练宇宙绝不能混入）
INDEX_CODE_RE = re.compile(r"^(SH000|SZ399)", re.IGNORECASE)


class RefreshError(RuntimeError):
    """编排或门禁失败。"""


@dataclass
class RefreshConfig:
    archive_dir: Path = DEFAULT_ARCHIVE_DIR
    csv_dir: Path = DEFAULT_CSV_DIR
    qlib_dir: Path = DEFAULT_QLIB_DIR
    lake_index_root: Path = DEFAULT_LAKE_INDEX_ROOT
    lake_symbol: str = DEFAULT_LAKE_SYMBOL
    staging_dir: Path | None = None
    new_qlib_dir: Path | None = None
    max_workers: int = DEFAULT_MAX_WORKERS
    expected_delist_max: int = DEFAULT_EXPECTED_DELIST_MAX
    force: bool = False
    dry_run: bool = False
    skip_merge: bool = False
    skip_dump: bool = False
    skip_patch: bool = False
    skip_swap: bool = False
    archive: bool = False
    offsite: bool = False
    offsite_dirs: tuple[Path, ...] = field(
        default_factory=lambda: tuple(Path(p) for p in DEFAULT_OFFSITE_DIRS)
    )
    seven_zip: Path | None = None
    python: Path = field(default_factory=lambda: Path(sys.executable))
    sample_symbols: tuple[str, ...] = ()
    today: date = field(default_factory=date.today)
    allow_beyond_lake: bool = False
    wipe_new_qlib_dir: bool = False
    skip_csv_scan: bool = False
    min_dump_free_gb: float = MIN_DUMP_FREE_GB
    min_staging_free_gb: float = MIN_STAGING_FREE_GB

    def resolve_paths(self) -> None:
        """补齐 staging / new_qlib 默认路径（相对 qlib_dir 父目录）。"""
        parent = self.qlib_dir.expanduser().resolve().parent
        stamp = self.today.strftime("%Y%m%d")
        if self.staging_dir is None:
            self.staging_dir = parent / f"my_data_staging_{stamp}"
        if self.new_qlib_dir is None:
            self.new_qlib_dir = parent / f"my_data_new_{stamp}"
        self.archive_dir = self.archive_dir.expanduser()
        self.csv_dir = self.csv_dir.expanduser()
        self.qlib_dir = self.qlib_dir.expanduser()
        self.lake_index_root = self.lake_index_root.expanduser()
        self.staging_dir = self.staging_dir.expanduser()
        self.new_qlib_dir = self.new_qlib_dir.expanduser()
        self.offsite_dirs = tuple(Path(p).expanduser() for p in self.offsite_dirs)
        if self.seven_zip is not None:
            self.seven_zip = self.seven_zip.expanduser()


def validate_params(cfg: RefreshConfig) -> list[str]:
    """参数校验；返回错误列表（空=通过）。不抛异常，便于单测。"""
    errors: list[str] = []
    if cfg.max_workers != DEFAULT_MAX_WORKERS:
        errors.append(
            f"max_workers 必须为 {DEFAULT_MAX_WORKERS}（禁止 16；收到 {cfg.max_workers}）"
        )
    if cfg.expected_delist_max < 0:
        errors.append(f"expected_delist_max 不能为负: {cfg.expected_delist_max}")
    if not cfg.lake_symbol or "_" not in cfg.lake_symbol:
        errors.append(f"lake_symbol 应形如 000001_SH，收到: {cfg.lake_symbol!r}")
    if cfg.archive and cfg.offsite and not cfg.offsite_dirs:
        errors.append("--offsite 需要至少一个 offsite 目录")
    if cfg.python and not str(cfg.python).strip():
        errors.append("python 解释器路径不能为空")
    return errors


def require_valid(cfg: RefreshConfig) -> None:
    errs = validate_params(cfg)
    if errs:
        raise RefreshError("参数校验失败:\n- " + "\n- ".join(errs))


def discover_7z(explicit: Path | None = None) -> Path | None:
    """发现 7-Zip 可执行文件：显式路径 → Windows 默认 → PATH 上的 7z/7za。"""
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    candidates.append(WIN_7Z)
    for name in ("7z", "7za"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    for path in candidates:
        if path and path.is_file():
            return path
    return None


def estimate_universe(csv_dir: Path, qlib_dir: Path) -> dict:
    """干跑用的宇宙变化预估（路径缺失时标明 unavailable）。"""
    out: dict = {"csv_symbols": None, "old_universe": None, "approx_delta": None, "note": ""}
    if csv_dir.is_dir():
        csv_syms = {p.stem.upper() for p in csv_dir.glob("*.csv")}
        out["csv_symbols"] = len(csv_syms)
    else:
        out["note"] = f"csv_dir 不存在: {csv_dir}"
    all_txt = qlib_dir / "instruments" / "all.txt"
    if all_txt.is_file():
        old = {
            ln.split("\t", 1)[0].strip().upper()
            for ln in all_txt.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        }
        out["old_universe"] = len(old)
        if out["csv_symbols"] is not None:
            # 粗估：CSV 批是尾段宇宙上界，不是精确 diff（退市股只在 archive）
            out["approx_delta"] = out["csv_symbols"] - len(old)
            out["note"] = (out["note"] + "；" if out["note"] else "") + (
                "approx_delta≈csv_count-old_all（未计 archive-only 退市股）"
            )
    else:
        out["note"] = (out["note"] + "；" if out["note"] else "") + f"旧 all.txt 不存在: {all_txt}"
    return out


@dataclass
class StepPlan:
    name: str
    argv: list[str]
    cwd: str
    note: str = ""


def build_merge_cmd(cfg: RefreshConfig) -> StepPlan:
    script = str(SCRIPTS_DIR / "merge_archive_and_csv.py")
    argv = [
        str(cfg.python),
        script,
        "--archive-dir",
        str(cfg.archive_dir),
        "--csv-dir",
        str(cfg.csv_dir),
        "--out-dir",
        str(cfg.staging_dir),
    ]
    return StepPlan("merge_archive_and_csv", argv, str(REPO_ROOT), "拼接 archive+CSV → staging parquet")


def build_dump_cmd(cfg: RefreshConfig) -> StepPlan:
    """只允许 dump_all；max_workers 钉死为 8。永不调用 dump_update。"""
    script = str(SCRIPTS_DIR / "dump_bin.py")
    argv = [
        str(cfg.python),
        script,
        "dump_all",
        f"--data_path={cfg.staging_dir}",
        f"--qlib_dir={cfg.new_qlib_dir}",
        "--file_suffix=.parquet",
        f"--max_workers={DEFAULT_MAX_WORKERS}",
    ]
    return StepPlan(
        "dump_bin.dump_all",
        argv,
        str(REPO_ROOT),
        f"全量灌 bin（max_workers={DEFAULT_MAX_WORKERS}；禁用 dump_update）",
    )


def build_patch_cmd(cfg: RefreshConfig) -> StepPlan:
    script = str(SCRIPTS_DIR / "patch_index_data.py")
    argv = [
        str(cfg.python),
        script,
        "--qlib-dir",
        str(cfg.new_qlib_dir),
        "--lake-root",
        str(cfg.lake_index_root),
        "--no-backup",
    ]
    return StepPlan(
        "patch_index_data",
        argv,
        str(REPO_ROOT),
        "补指数 + all.txt→index.txt 挪移",
    )


def build_plan(cfg: RefreshConfig) -> list[StepPlan]:
    cfg.resolve_paths()
    steps: list[StepPlan] = []
    if not cfg.skip_merge:
        steps.append(build_merge_cmd(cfg))
    if not cfg.skip_dump:
        steps.append(build_dump_cmd(cfg))
    if not cfg.skip_patch:
        steps.append(build_patch_cmd(cfg))
    return steps


def format_dry_run(cfg: RefreshConfig, steps: Sequence[StepPlan]) -> str:
    cfg.resolve_paths()
    uni = estimate_universe(cfg.csv_dir, cfg.qlib_dir)
    lines = [
        "=== refresh_mydata dry-run ===",
        f"today: {cfg.today.isoformat()}",
        f"archive_dir: {cfg.archive_dir}",
        f"csv_dir: {cfg.csv_dir}",
        f"staging_dir: {cfg.staging_dir}",
        f"new_qlib_dir: {cfg.new_qlib_dir}",
        f"target_qlib_dir: {cfg.qlib_dir}",
        f"lake_index_root: {cfg.lake_index_root} (calendar gate symbol={cfg.lake_symbol})",
        f"max_workers: {DEFAULT_MAX_WORKERS} (dump_update: FORBIDDEN)",
        f"force: {cfg.force}",
        f"allow_beyond_lake: {cfg.allow_beyond_lake}",
        f"archive: {cfg.archive}",
        f"offsite: {cfg.offsite} dirs={[str(p) for p in cfg.offsite_dirs]}",
        f"universe_estimate: csv={uni['csv_symbols']} old_all={uni['old_universe']} "
        f"approx_delta={uni['approx_delta']} ({uni['note'] or 'ok'})",
        "--- steps ---",
    ]
    for i, step in enumerate(steps, 1):
        lines.append(f"[{i}/{len(steps)}] {step.name}: {step.note}")
        lines.append(f"  cwd: {step.cwd}")
        lines.append(f"  cmd: {subprocess.list2cmdline(step.argv)}")
    lines.append("--- post ---")
    lines.append(
        f"day_future: rebuild calendars/day_future.txt = day.txt + {DEFAULT_DAY_FUTURE_EXTRA} weekdays "
        "(回测交易日历 future=True 依赖；陈旧文件会导致回测末日越界)"
    )
    lines.append(
        "preflight: CSV illegal-float scan; refuse dump into non-empty new_qlib_dir "
        "unless --wipe-new-qlib-dir; disk free on staging/dump drives"
    )
    lines.append("integrity gates: calendar / sample values / no-index-in-all / universe diff (fail → no swap)")
    lines.append("atomic swap: backup my_data_backup_YYYYMMDD_pre_* then mv; rollback on error")
    lines.append("note: 日历末日不变也要 dump_all（纠错/赢筹浮点）；禁止 dump_update")
    lines.append(
        "post-swap smoke: calendar last / index.txt / winratio bins + [0,1] sample "
        "via read_bin_field（首元素是起始下标；PowerShell 双引号勿写 $close）"
    )
    if cfg.archive:
        lines.append(f"archive (M1-C): my_data_{cfg.today.strftime('%Y%m%d')}_full.7z")
    if cfg.offsite:
        lines.append(f"offsite (M1-C): copy+MD5 → {[str(p) for p in cfg.offsite_dirs]}")
    return "\n".join(lines) + "\n"


def run_step(step: StepPlan, *, runner: Callable[..., subprocess.CompletedProcess] | None = None) -> None:
    run = runner or subprocess.run
    print(f"→ {step.name}: {subprocess.list2cmdline(step.argv)}")
    proc = run(step.argv, cwd=step.cwd, check=False)
    code = getattr(proc, "returncode", proc)
    if isinstance(code, subprocess.CompletedProcess):
        code = code.returncode
    if code != 0:
        raise RefreshError(f"{step.name} 失败，exit={code}")


def disk_free_gb(path: Path, *, usage_fn=shutil.disk_usage) -> float:
    """path 所在盘剩余 GB。目录不存在则沿父路径找已存在的祖先。"""
    probe = Path(path)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    if not probe.exists():
        raise RefreshError(f"无法探测磁盘空间: {path}")
    return usage_fn(probe).free / 1e9


def assert_disk_space(cfg: RefreshConfig, *, usage_fn=shutil.disk_usage) -> None:
    """C 盘空间不够时拒绝 dump；staging 请放到 F: 等大盘。"""
    if not cfg.skip_merge:
        free = disk_free_gb(cfg.staging_dir, usage_fn=usage_fn)
        if free < cfg.min_staging_free_gb:
            raise RefreshError(
                f"staging 盘剩余 {free:.1f} GB < {cfg.min_staging_free_gb} GB："
                f"{cfg.staging_dir}。把 --staging-dir 放到 F: 等空间更大的盘"
            )
        print(f"[pre] staging 盘剩余 {free:.1f} GB")
    if not cfg.skip_dump:
        free = disk_free_gb(cfg.new_qlib_dir, usage_fn=usage_fn)
        if free < cfg.min_dump_free_gb:
            raise RefreshError(
                f"dump 目标盘剩余 {free:.1f} GB < {cfg.min_dump_free_gb} GB："
                f"{cfg.new_qlib_dir}。旧 features_cache 可达 6GB，不要和半成品挤在同一小盘"
            )
        print(f"[pre] dump 盘剩余 {free:.1f} GB")


def dump_target_is_dirty(qlib_dir: Path) -> bool:
    qlib_dir = Path(qlib_dir)
    if not qlib_dir.exists():
        return False
    if (qlib_dir / "calendars" / "day.txt").is_file():
        return True
    feat = qlib_dir / "features"
    if feat.is_dir() and any(feat.iterdir()):
        return True
    return False


def ensure_dump_target_clean(cfg: RefreshConfig, *, remover=shutil.rmtree) -> None:
    """半成品 dump 目录必须先删再 dump_all，禁止往未完成目录上续写。"""
    if cfg.skip_dump:
        return
    target = Path(cfg.new_qlib_dir)
    if not dump_target_is_dirty(target):
        return
    if not cfg.wipe_new_qlib_dir:
        raise RefreshError(
            f"dump 目标已存在且非空: {target}。半成品必须先删干净再 dump_all，"
            "加 --wipe-new-qlib-dir 才会删除后重灌（禁止往半成品上继续 dump）"
        )
    print(f"[pre] wipe dump 目标 {target}")
    remover(target)


def run_csv_scan_preflight(cfg: RefreshConfig) -> dict | None:
    if cfg.skip_merge or cfg.skip_csv_scan:
        return None
    from csv_float_scan import format_scan_report, scan_csv_dir

    report = scan_csv_dir(cfg.csv_dir)
    print(format_scan_report(report))
    if report["fatal"]:
        files = sorted({h["file"] for h in report["fatal"]})
        raise RefreshError(
            "CSV 的 OHLC/volume/factor 含 Windows 非法浮点，拒绝入库: " + ", ".join(files[:10])
        )
    return report


def run_preflight(cfg: RefreshConfig, *, usage_fn=shutil.disk_usage, remover=shutil.rmtree) -> None:
    run_csv_scan_preflight(cfg)
    assert_disk_space(cfg, usage_fn=usage_fn)
    ensure_dump_target_clean(cfg, remover=remover)


def _fmt_opt_float(value) -> str:
    if value is None:
        return "nan"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "nan"
    if np.isnan(number) or np.isinf(number):
        return "nan"
    return f"{number:.4f}"


def smoke_winratio_sample(
    qlib_dir: Path, calendar: pd.DatetimeIndex | None = None
) -> dict | None:
    """抽一只 $winratio：合法值应在 [0,1]。bin 首元素是日历起始下标，禁止裸 fromfile。"""
    qlib_dir = Path(qlib_dir)
    bins = list((qlib_dir / "features").glob("*/winratio.day.bin"))
    if not bins:
        return None
    calendar = calendar if calendar is not None else read_calendar(qlib_dir)
    symbol = None
    if (qlib_dir / "instruments" / "all.txt").is_file():
        try:
            symbol = pick_sample_symbols(qlib_dir, n=1)[0]
        except RefreshError:
            symbol = None
    if symbol is None:
        symbol = bins[0].parent.name.upper()
    series = read_bin_field(qlib_dir, symbol, "winratio", calendar)
    valid = series.replace([np.inf, -np.inf], np.nan).dropna()
    out_of = int(((valid < 0) | (valid > 1)).sum()) if len(valid) else 0
    last = series.iloc[-1] if len(series) else None
    return {
        "symbol": symbol,
        "n": int(len(series)),
        "valid": int(len(valid)),
        "nan": int(series.isna().sum()),
        "last": None if last is None or pd.isna(last) else float(last),
        "vmin": float(valid.min()) if len(valid) else None,
        "vmax": float(valid.max()) if len(valid) else None,
        "out_of_01": out_of,
    }


def print_refresh_summary(qlib_dir: Path) -> None:
    """swap 后冒烟：日历末日、day_future、index.txt、winratio bin 数 + [0,1] 抽样。"""
    qlib_dir = Path(qlib_dir)
    calendar = read_calendar(qlib_dir)
    print(
        f"[smoke] calendar {calendar[0].date()} .. {calendar[-1].date()} n={len(calendar)}"
    )
    fut = qlib_dir / "calendars" / "day_future.txt"
    if fut.is_file():
        fut_cal = pd.to_datetime(
            [ln for ln in fut.read_text(encoding="utf-8").splitlines() if ln.strip()]
        )
        print(f"[smoke] day_future .. {fut_cal[-1].date()} n={len(fut_cal)}")
        if len(fut_cal) == 0 or fut_cal[-1] <= calendar[-1]:
            print("[smoke] WARN day_future 未长过 day.txt，回测末日会越界")
    else:
        print("[smoke] WARN 缺少 day_future.txt（回测 future=True 会在数据末日越界）")
    index_path = qlib_dir / "instruments" / "index.txt"
    if index_path.is_file():
        for ln in index_path.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                print(f"[smoke] index {ln}")
    wr = list((qlib_dir / "features").glob("*/winratio.day.bin"))
    print(f"[smoke] winratio bins={len(wr)}")
    try:
        sample = smoke_winratio_sample(qlib_dir, calendar)
    except (RefreshError, ValueError, OSError) as exc:
        print(f"[smoke] WARN winratio 抽样失败: {exc}")
        return
    if sample is None:
        return
    print(
        f"[smoke] winratio {sample['symbol']} last={_fmt_opt_float(sample['last'])} "
        f"valid={sample['valid']} nan={sample['nan']} "
        f"range=[{_fmt_opt_float(sample['vmin'])},{_fmt_opt_float(sample['vmax'])}] "
        f"out_of_[0,1]={sample['out_of_01']}"
    )
    if sample["out_of_01"]:
        print("[smoke] WARN winratio 存在超出 [0,1] 的值（源纠错批不应再出现）")


# ---------------------------------------------------------------------------
# M1-B：完整性门禁 + 原子 swap
# ---------------------------------------------------------------------------


def read_calendar(qlib_dir: Path) -> pd.DatetimeIndex:
    cal_path = Path(qlib_dir) / "calendars" / "day.txt"
    if not cal_path.is_file():
        raise RefreshError(f"日历不存在: {cal_path}")
    frame = pd.read_csv(cal_path, header=None, parse_dates=[0])
    return pd.DatetimeIndex(frame[0])


DEFAULT_DAY_FUTURE_EXTRA = 5  # 数据末日之后再顺延的工作日数（与 2026-04 旧档口径一致）


def next_weekdays_after(last_day: pd.Timestamp, n: int) -> list[pd.Timestamp]:
    """last_day 之后的前 n 个工作日（周一~周五）。

    近似：不含 A 股节假日。day_future 只被回测交易日历（Cal.calendar(future=True)）
    使用、绝不参与数据加载，且策略仅在最后一根 bar 取「下一交易日」做 epsilon_change，
    因此工作日近似足够；n 取 5 留出冗余。
    """
    days: list[pd.Timestamp] = []
    cur = pd.Timestamp(last_day)
    while len(days) < n:
        cur = cur + pd.Timedelta(days=1)
        if cur.weekday() < 5:
            days.append(cur)
    return days


def refresh_day_future_calendar(qlib_dir: Path, extra_days: int = DEFAULT_DAY_FUTURE_EXTRA) -> Path:
    """重建 calendars/day_future.txt = day.txt 全量 + 末日后 n 个工作日。

    背景（2026-09-13 实踩）：qlib 回测交易日历走 future=True 读 day_future.txt；
    该文件若停在旧档日期（或缺失后回落到 day.txt），当回测 end_time == 数据末日时，
    TradeCalendarManager.get_step_time 取 calendar[index+1] 越界崩溃。数据刷新流程
    此前不重建该文件，陈旧版本会随数据包流转（Thinkpad 4 月旧档即如此）。
    """
    qlib_dir = Path(qlib_dir)
    calendar = read_calendar(qlib_dir)
    if len(calendar) == 0:
        raise RefreshError("day.txt 为空，拒绝生成 day_future.txt")
    extra = next_weekdays_after(calendar[-1], extra_days)
    full = list(calendar) + extra

    cal_path = qlib_dir / "calendars" / "day.txt"
    raw = cal_path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    out_path = qlib_dir / "calendars" / "day_future.txt"
    body = newline.join(d.strftime("%Y-%m-%d") for d in full) + newline
    out_path.write_text(body, encoding="ascii", newline="")
    print(
        f"[day_future] rebuilt: {len(full)} days "
        f"({full[0].date()} ~ {full[-1].date()}，数据末日 {calendar[-1].date()} 后顺延 {len(extra)} 个工作日)"
    )
    return out_path


def load_lake_trading_days(
    lake_index_root: Path,
    symbol: str,
    *,
    reader: Callable[[Path], pd.DataFrame] | None = None,
) -> pd.DatetimeIndex:
    """湖指数分区 → Asia/Shanghai 交易日（time 为 UTC 毫秒）。"""
    source = Path(lake_index_root) / f"symbol={symbol}" / "data.parquet"
    if reader is None:
        if not source.is_file():
            raise RefreshError(f"湖指数 parquet 不存在: {source}")
        df = pd.read_parquet(source)
    else:
        df = reader(source)
    if "time" not in df.columns:
        raise RefreshError("湖 parquet 缺少 time 列")
    dates = (
        pd.to_datetime(df["time"], unit="ms", utc=True)
        .dt.tz_convert("Asia/Shanghai")
        .dt.normalize()
        .dt.tz_localize(None)
    )
    return pd.DatetimeIndex(sorted(dates.unique()))


def gate_calendar_vs_lake(
    qlib_dir: Path,
    lake_index_root: Path,
    lake_symbol: str = DEFAULT_LAKE_SYMBOL,
    *,
    lake_days: pd.DatetimeIndex | None = None,
    allow_beyond_lake: bool = False,
) -> dict:
    """门禁 1：新日历 ⊆ 湖交易日（湖范围内 0 缺失）。

    allow_beyond_lake：允许日历末日晚于湖（CSV 尾巴已更新、湖指数分区尚未跟上）。
    湖 max 及以前的空洞仍失败。
    """
    calendar = read_calendar(qlib_dir)
    lake = lake_days if lake_days is not None else load_lake_trading_days(lake_index_root, lake_symbol)
    lake_set = set(lake)
    cal_set = set(calendar)
    missing_in_lake = sorted(cal_set - lake_set)
    lake_max = lake.max() if len(lake) else None
    historical = [d for d in missing_in_lake if lake_max is None or d <= lake_max]
    beyond = [d for d in missing_in_lake if lake_max is not None and d > lake_max]
    report = {
        "calendar_days": len(calendar),
        "lake_days_in_range": len([d for d in lake if calendar.min() <= d <= calendar.max()]),
        "missing_in_lake": [str(d.date()) for d in missing_in_lake],
        "missing_count": len(missing_in_lake),
        "beyond_lake": [str(d.date()) for d in beyond],
    }
    if historical:
        raise RefreshError(
            f"门禁1失败：日历相对湖 {lake_symbol} 缺 {len(historical)} 日 "
            f"(例: {[str(d.date()) for d in historical[:5]]})"
        )
    if beyond and not allow_beyond_lake:
        raise RefreshError(
            f"门禁1失败：日历比湖 {lake_symbol} 多 {len(beyond)} 日 "
            f"(例: {report['beyond_lake'][:5]}；湖末日 {lake_max.date() if lake_max is not None else 'n/a'}。"
            f"CSV 尾巴新于湖时加 --allow-beyond-lake)"
        )
    if beyond:
        print(
            f"[gate1] 日历超出湖 {len(beyond)} 日（已 --allow-beyond-lake）: {report['beyond_lake'][:5]}",
            flush=True,
        )
    return report


def _code_to_fname(code: str) -> str:
    return code.lower()


def read_bin_field(qlib_dir: Path, symbol: str, field: str, calendar: pd.DatetimeIndex) -> pd.Series:
    path = Path(qlib_dir) / "features" / _code_to_fname(symbol) / f"{field}.day.bin"
    if not path.is_file():
        raise RefreshError(f"缺少 bin: {path}")
    arr = np.fromfile(path, dtype="<f")
    start = int(arr[0])
    return pd.Series(arr[1:], index=calendar[start : start + len(arr) - 1])


def read_source_close(csv_dir: Path, symbol: str, day: pd.Timestamp) -> float | None:
    """从源 CSV 取某日 close；文件或日期缺失返回 None。"""
    # CSV 可能是 SH600000.csv 或 600000.csv / sh600000.csv
    candidates = [
        Path(csv_dir) / f"{symbol}.csv",
        Path(csv_dir) / f"{symbol.upper()}.csv",
        Path(csv_dir) / f"{symbol.lower()}.csv",
    ]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        return None
    df = pd.read_csv(path)
    date_col = "date" if "date" in df.columns else df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col])
    row = df.loc[df[date_col] == pd.Timestamp(day)]
    if row.empty or "close" not in df.columns:
        return None
    return float(row["close"].iloc[0])


def pick_sample_symbols(qlib_dir: Path, n: int = 3, explicit: Sequence[str] = ()) -> list[str]:
    """抽覆盖日历首末日的非指数标的。all.txt 按代码排序时前几只常是北交所，首日无 bin。"""
    if explicit:
        return [s.upper() for s in explicit][:n]
    calendar = read_calendar(qlib_dir)
    first, last = calendar[0], calendar[-1]
    all_txt = Path(qlib_dir) / "instruments" / "all.txt"
    syms = []
    for ln in all_txt.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        parts = [p.strip() for p in ln.split("\t")]
        sym = parts[0].upper()
        if INDEX_CODE_RE.match(sym):
            continue
        if len(parts) >= 3:
            start, end = pd.Timestamp(parts[1]), pd.Timestamp(parts[2])
            if start > first or end < last:
                continue
        syms.append(sym)
        if len(syms) >= n:
            break
    if len(syms) < n:
        raise RefreshError(f"all.txt 覆盖日历首末日的非指数标的不足 {n} 只，无法抽样")
    return syms


def gate_sample_values(
    qlib_dir: Path,
    csv_dir: Path,
    symbols: Sequence[str] | None = None,
    *,
    source_close_fn: Callable[[str, pd.Timestamp], float | None] | None = None,
    rtol: float = 1e-5,
    atol: float = 1e-4,
) -> dict:
    """门禁 2：首日/末日 × 抽样标的 close 与源 CSV 对齐。"""
    calendar = read_calendar(qlib_dir)
    first, last = calendar[0], calendar[-1]
    syms = list(symbols) if symbols else pick_sample_symbols(qlib_dir, 3)
    mismatches = []
    checked = []
    get_close = source_close_fn or (lambda s, d: read_source_close(csv_dir, s, d))
    for sym in syms:
        series = read_bin_field(qlib_dir, sym, "close", calendar)
        for day, label in ((first, "first"), (last, "last")):
            if day not in series.index:
                mismatches.append(f"{sym}@{label}:{day.date()} 无 bin 值")
                continue
            got = float(series.loc[day])
            exp = get_close(sym, day)
            if exp is None:
                # 源 CSV 无该日（可能仅 archive 段）——跳过但不记失败
                checked.append({"symbol": sym, "day": str(day.date()), "skipped": "no_csv"})
                continue
            if not np.isclose(got, exp, rtol=rtol, atol=atol):
                mismatches.append(f"{sym}@{label}:{day.date()} bin={got} csv={exp}")
            else:
                checked.append({"symbol": sym, "day": str(day.date()), "ok": True, "close": got})
    if mismatches:
        raise RefreshError("门禁2失败：抽样值不一致: " + "; ".join(mismatches))
    return {"symbols": syms, "checked": checked}


def read_universe(qlib_dir: Path) -> set[str]:
    all_txt = Path(qlib_dir) / "instruments" / "all.txt"
    if not all_txt.is_file():
        raise RefreshError(f"缺少 all.txt: {all_txt}")
    return {
        ln.split("\t", 1)[0].strip().upper()
        for ln in all_txt.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    }


def gate_no_indices_in_all(qlib_dir: Path) -> dict:
    """门禁 3：all.txt 不含指数代码。"""
    universe = read_universe(qlib_dir)
    leaked = sorted(s for s in universe if INDEX_CODE_RE.match(s))
    if leaked:
        raise RefreshError(f"门禁3失败：all.txt 含指数 {leaked}")
    return {"universe_size": len(universe), "index_leak": []}


def gate_universe_diff(
    old_qlib_dir: Path,
    new_qlib_dir: Path,
    *,
    expected_delist_max: int = DEFAULT_EXPECTED_DELIST_MAX,
    force: bool = False,
) -> dict:
    """门禁 4：新旧宇宙 diff；退市数超预期须 --force。"""
    old = read_universe(old_qlib_dir) if (Path(old_qlib_dir) / "instruments" / "all.txt").is_file() else set()
    new = read_universe(new_qlib_dir)
    added = sorted(new - old)
    removed = sorted(old - new)
    report = {
        "old_size": len(old),
        "new_size": len(new),
        "added": added,
        "removed": removed,
        "added_count": len(added),
        "removed_count": len(removed),
    }
    print(
        f"宇宙 diff: old={len(old)} new={len(new)} "
        f"+{len(added)} -{len(removed)}; "
        f"新增例={added[:5]}; 退市例={removed[:5]}"
    )
    if len(removed) > expected_delist_max and not force:
        raise RefreshError(
            f"门禁4失败：退市数 {len(removed)} > 预期上限 {expected_delist_max}；"
            f"确认后加 --force 再跑（不会在失败时 swap）"
        )
    return report


def run_integrity_gates(
    cfg: RefreshConfig,
    *,
    lake_days: pd.DatetimeIndex | None = None,
    source_close_fn: Callable[[str, pd.Timestamp], float | None] | None = None,
) -> dict:
    """跑齐四门禁；任一门失败抛 RefreshError（调用方不得 swap）。"""
    assert cfg.new_qlib_dir is not None
    reports = {}
    print("[gate1] 日历 vs 湖 …")
    reports["calendar"] = gate_calendar_vs_lake(
        cfg.new_qlib_dir,
        cfg.lake_index_root,
        cfg.lake_symbol,
        lake_days=lake_days,
        allow_beyond_lake=cfg.allow_beyond_lake,
    )
    print(f"[gate1] ok missing={reports['calendar']['missing_count']}")
    print("[gate2] 抽样双端值 …")
    reports["sample"] = gate_sample_values(
        cfg.new_qlib_dir,
        cfg.csv_dir,
        symbols=cfg.sample_symbols or None,
        source_close_fn=source_close_fn,
    )
    print(f"[gate2] ok symbols={reports['sample']['symbols']}")
    print("[gate3] all.txt 无指数 …")
    reports["no_index"] = gate_no_indices_in_all(cfg.new_qlib_dir)
    print(f"[gate3] ok universe={reports['no_index']['universe_size']}")
    print("[gate4] 宇宙 diff …")
    reports["universe"] = gate_universe_diff(
        cfg.qlib_dir,
        cfg.new_qlib_dir,
        expected_delist_max=cfg.expected_delist_max,
        force=cfg.force,
    )
    print("[gate4] ok")
    return reports


def backup_name(qlib_dir: Path, today: date, tag: str = "refresh") -> Path:
    return qlib_dir.parent / f"my_data_backup_{today.strftime('%Y%m%d')}_pre_{tag}"


def atomic_swap(
    qlib_dir: Path,
    new_qlib_dir: Path,
    *,
    today: date | None = None,
    renamer: Callable[[Path, Path], None] | None = None,
) -> Path:
    """原子 mv：目标 → backup，new → 目标；失败回滚。返回 backup 路径。"""
    today = today or date.today()
    qlib_dir = Path(qlib_dir)
    new_qlib_dir = Path(new_qlib_dir)
    if not new_qlib_dir.is_dir():
        raise RefreshError(f"new_qlib_dir 不存在，拒绝 swap: {new_qlib_dir}")
    backup = backup_name(qlib_dir, today)
    if backup.exists():
        raise RefreshError(f"备份目录已存在，拒绝覆盖: {backup}")
    do_rename = renamer or (lambda a, b: a.rename(b))
    moved_old = False
    try:
        if qlib_dir.exists():
            do_rename(qlib_dir, backup)
            moved_old = True
        do_rename(new_qlib_dir, qlib_dir)
    except Exception as exc:
        # 回滚
        if qlib_dir.exists() and moved_old and not new_qlib_dir.exists():
            try:
                do_rename(qlib_dir, new_qlib_dir)
            except Exception:
                pass
        if moved_old and backup.exists() and not qlib_dir.exists():
            try:
                do_rename(backup, qlib_dir)
            except Exception:
                pass
        raise RefreshError(f"原子 swap 失败并已尝试回滚: {exc}") from exc
    print(f"swap 完成: {new_qlib_dir} → {qlib_dir}；备份 {backup}")
    return backup



def md5_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.md5()
    with Path(path).open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def archive_qlib_dir(
    qlib_dir: Path,
    *,
    today: date | None = None,
    seven_zip: Path | None = None,
    out_dir: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> Path:
    """打 my_data_YYYYMMDD_full.7z。seven_zip 可注入；缺失时清晰报错。"""
    today = today or date.today()
    qlib_dir = Path(qlib_dir)
    out_dir = Path(out_dir) if out_dir else qlib_dir.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    archive_path = out_dir / f"my_data_{today.strftime('%Y%m%d')}_full.7z"
    exe = discover_7z(seven_zip)
    if exe is None:
        raise RefreshError(
            "未找到 7-Zip（已查 Windows 默认路径与 PATH 上的 7z/7za）。"
            "请安装 7-Zip 或传 --seven-zip /path/to/7z"
        )
    if archive_path.exists():
        raise RefreshError(f"归档已存在，拒绝覆盖: {archive_path}")
    # 7z a -t7z archive.7z ./my_data/*
    # 用目录名为根，便于解压还原
    argv = [str(exe), "a", "-t7z", "-mx=5", str(archive_path), str(qlib_dir.name)]
    run = runner or subprocess.run
    print(f"→ archive: {subprocess.list2cmdline(argv)} (cwd={out_dir})")
    proc = run(argv, cwd=str(out_dir), check=False)
    code = proc.returncode if hasattr(proc, "returncode") else int(proc)
    if code != 0:
        raise RefreshError(f"7z 归档失败 exit={code}")
    digest = md5_file(archive_path)
    print(f"archive ok: {archive_path} md5={digest} size={archive_path.stat().st_size}")
    return archive_path


def offsite_copy_and_verify(
    archive_path: Path,
    offsite_dirs: Sequence[Path],
    *,
    copy_fn: Callable[[Path, Path], None] | None = None,
    md5_fn: Callable[[Path], str] | None = None,
) -> dict:
    """拷贝归档到各异地根目录，三方（源+各地）MD5 一致才算过。

    目录不存在时跳过并记入 missing（本 VM 无 F:/G: 属预期）；若全部缺失则报错。
    """
    archive_path = Path(archive_path)
    if not archive_path.is_file():
        raise RefreshError(f"归档不存在: {archive_path}")
    md5 = md5_fn or md5_file
    copy = copy_fn or shutil.copy2
    src_md5 = md5(archive_path)
    results = {"source_md5": src_md5, "copies": [], "missing": [], "mismatched": []}
    for root in offsite_dirs:
        root = Path(root)
        if not root.exists():
            results["missing"].append(str(root))
            print(f"offsite skip (missing root): {root}")
            continue
        dest = root / archive_path.name
        copy(archive_path, dest)
        dest_md5 = md5(dest)
        entry = {"path": str(dest), "md5": dest_md5}
        results["copies"].append(entry)
        if dest_md5 != src_md5:
            results["mismatched"].append(entry)
            print(f"offsite MD5 不一致: {dest} {dest_md5} != {src_md5}")
        else:
            print(f"offsite ok: {dest} md5={dest_md5}")
    if not results["copies"] and results["missing"]:
        raise RefreshError(
            "所有 offsite 根目录都不存在（本机无 F:/G: 时请传 --offsite-dir 指向可写目录）: "
            + ", ".join(results["missing"])
        )
    if results["mismatched"]:
        raise RefreshError(f"offsite MD5 三方校验失败: {results['mismatched']}")
    # 若部分缺失但至少一份成功：警告但不失败（硬件不全的 VM）
    if results["missing"]:
        print(f"offsite 警告：部分根目录缺失 {results['missing']}，已校验副本 {len(results['copies'])} 份")
    return results


def paths_ready_for_real_run(cfg: RefreshConfig) -> list[str]:
    """真实跑需要的路径；返回缺失列表。"""
    missing = []
    if not cfg.skip_merge:
        for p in (cfg.archive_dir, cfg.csv_dir):
            if not Path(p).exists():
                missing.append(str(p))
    return missing


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="my_data 全量刷新编排器（merge→dump_all(8)→patch）")
    p.add_argument("--archive-dir", default=str(DEFAULT_ARCHIVE_DIR))
    p.add_argument("--csv-dir", default=str(DEFAULT_CSV_DIR))
    p.add_argument("--qlib-dir", default=str(DEFAULT_QLIB_DIR), help="线上目标目录（swap 终点）")
    p.add_argument("--staging-dir", default="", help="merge 输出；默认 my_data_staging_YYYYMMDD")
    p.add_argument("--new-qlib-dir", default="", help="dump_all 输出；默认 my_data_new_YYYYMMDD")
    p.add_argument("--lake-index-root", default=str(DEFAULT_LAKE_INDEX_ROOT))
    p.add_argument("--lake-symbol", default=DEFAULT_LAKE_SYMBOL, help="日历门禁用的湖指数分区")
    p.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_MAX_WORKERS,
        help=f"必须为 {DEFAULT_MAX_WORKERS}",
    )
    p.add_argument("--expected-delist-max", type=int, default=DEFAULT_EXPECTED_DELIST_MAX)
    p.add_argument("--force", action="store_true", help="退市数超预期时强制过门禁 4")
    p.add_argument(
        "--allow-beyond-lake",
        action="store_true",
        help="允许日历末日晚于湖指数分区（CSV 尾巴已更新、湖尚未跟上）；湖范围内缺日仍失败",
    )
    p.add_argument("--dry-run", action="store_true", help="只打印计划，不执行")
    p.add_argument("--skip-merge", action="store_true")
    p.add_argument("--skip-dump", action="store_true")
    p.add_argument("--skip-patch", action="store_true")
    p.add_argument("--skip-swap", action="store_true", help="跑完三件套+门禁但不换目录")
    p.add_argument("--archive", action="store_true", help="M1-C：打 7z 全量包")
    p.add_argument("--offsite", action="store_true", help="M1-C：拷到异地目录并 MD5 三方校验")
    p.add_argument(
        "--offsite-dir",
        action="append",
        default=None,
        help="异地根目录，可重复；默认 F:/ 与 G:/",
    )
    p.add_argument("--seven-zip", default="", help="7z 可执行文件路径；空则自动发现")
    p.add_argument("--python", default=sys.executable, help="调用子脚本的解释器")
    p.add_argument(
        "--sample-symbol",
        action="append",
        default=None,
        help="门禁 2 抽样标的（可重复）；默认从 all.txt 取覆盖日历首末日的前 3 只非指数",
    )
    p.add_argument(
        "--wipe-new-qlib-dir",
        action="store_true",
        help="dump 前删除已存在的 new_qlib_dir（半成品必须先删再 dump_all）",
    )
    p.add_argument(
        "--skip-csv-scan",
        action="store_true",
        help="跳过入库前 CSV 非法浮点扫描（-1.#J / -1.#IND）",
    )
    p.add_argument("--min-dump-free-gb", type=float, default=MIN_DUMP_FREE_GB)
    p.add_argument("--min-staging-free-gb", type=float, default=MIN_STAGING_FREE_GB)
    return p


def config_from_args(args: argparse.Namespace, *, today: date | None = None) -> RefreshConfig:
    offsite = tuple(Path(p) for p in args.offsite_dir) if args.offsite_dir else tuple(
        Path(p) for p in DEFAULT_OFFSITE_DIRS
    )
    samples = tuple(s.strip().upper() for s in (args.sample_symbol or []) if s.strip())
    cfg = RefreshConfig(
        archive_dir=Path(args.archive_dir),
        csv_dir=Path(args.csv_dir),
        qlib_dir=Path(args.qlib_dir),
        lake_index_root=Path(args.lake_index_root),
        lake_symbol=args.lake_symbol.strip(),
        staging_dir=Path(args.staging_dir) if args.staging_dir else None,
        new_qlib_dir=Path(args.new_qlib_dir) if args.new_qlib_dir else None,
        max_workers=args.max_workers,
        expected_delist_max=args.expected_delist_max,
        force=bool(args.force),
        allow_beyond_lake=bool(args.allow_beyond_lake),
        dry_run=bool(args.dry_run),
        skip_merge=bool(args.skip_merge),
        skip_dump=bool(args.skip_dump),
        skip_patch=bool(args.skip_patch),
        skip_swap=bool(args.skip_swap),
        archive=bool(args.archive),
        offsite=bool(args.offsite),
        offsite_dirs=offsite,
        seven_zip=Path(args.seven_zip) if args.seven_zip else None,
        python=Path(args.python),
        sample_symbols=samples,
        today=today or date.today(),
        wipe_new_qlib_dir=bool(args.wipe_new_qlib_dir),
        skip_csv_scan=bool(args.skip_csv_scan),
        min_dump_free_gb=float(args.min_dump_free_gb),
        min_staging_free_gb=float(args.min_staging_free_gb),
    )
    cfg.resolve_paths()
    return cfg


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config_from_args(args)
    require_valid(cfg)
    steps = build_plan(cfg)
    if cfg.dry_run:
        sys.stdout.write(format_dry_run(cfg, steps))
        return 0

    missing = paths_ready_for_real_run(cfg)
    if missing:
        raise RefreshError(
            "源路径不存在，拒绝执行（可用 --dry-run 看计划；门禁单测不依赖真湖）: "
            + ", ".join(missing)
        )

    run_preflight(cfg)

    for step in steps:
        if any("dump_update" in part for part in step.argv):
            raise RefreshError("内部错误：检测到 dump_update（已禁用）")
        if step.name.startswith("dump_bin") and f"--max_workers={DEFAULT_MAX_WORKERS}" not in step.argv:
            raise RefreshError("内部错误：dump_all 未钉死 max_workers=8")
        run_step(step)

    # 门禁失败绝不能 swap；swap 前先重建 day_future（数据加载不用它，只服务回测日历）
    refresh_day_future_calendar(cfg.new_qlib_dir)
    run_integrity_gates(cfg)

    if cfg.skip_swap:
        print("skip_swap：门禁已过，未换目录")
        live_dir = cfg.new_qlib_dir
    else:
        atomic_swap(cfg.qlib_dir, cfg.new_qlib_dir, today=cfg.today)
        live_dir = cfg.qlib_dir

    archive_path = None
    if cfg.archive:
        archive_path = archive_qlib_dir(
            live_dir, today=cfg.today, seven_zip=cfg.seven_zip, out_dir=Path(live_dir).parent
        )
    if cfg.offsite:
        if archive_path is None:
            # 允许只 offsite：若同日归档已在父目录则复用，否则先归档
            candidate = Path(live_dir).parent / f"my_data_{cfg.today.strftime('%Y%m%d')}_full.7z"
            if candidate.is_file():
                archive_path = candidate
            else:
                archive_path = archive_qlib_dir(
                    live_dir, today=cfg.today, seven_zip=cfg.seven_zip, out_dir=Path(live_dir).parent
                )
        offsite_copy_and_verify(archive_path, cfg.offsite_dirs)

    print_refresh_summary(live_dir)
    print("refresh_mydata 完成。")
    return 0



if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RefreshError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
