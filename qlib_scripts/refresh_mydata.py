# -*- coding: utf-8 -*-
"""my_data 全量刷新编排器（M1）：merge → dump_all(8) → patch_index。

把 2026-09-13 手工串起来的三件套固化成一条命令。现有脚本接口不变，本脚本只
用子进程调用它们。硬约束见 docs/plan-midterm-m1m4m2m3-2026-09-13.md §0：

- dump_all 必须 --max_workers 8（禁止 16）
- 禁止 dump_update
- 指数不得留在 instruments/all.txt（由 patch_index_data 第 4 步挪走）
- ~/.qlib 数据只准经本编排器改动；换目录前自动备份 my_data_backup_YYYYMMDD_pre_*

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
    lines.append("integrity gates (M1-B): calendar / sample values / no-index-in-all / universe diff")
    lines.append("atomic swap (M1-B): backup my_data_backup_YYYYMMDD_pre_* then mv")
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
        help="门禁 2 抽样标的（可重复）；默认从 all.txt 取前 3 只非指数",
    )
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

    # M1-A：真实执行只跑三件套；swap/门禁/归档在后续片接入。
    # 路径缺失时明确报错，避免在无 F: 湖的 VM 上半写 ~/.qlib。
    missing = [str(p) for p in (cfg.archive_dir, cfg.csv_dir) if not cfg.skip_merge and not Path(p).exists()]
    if missing and not cfg.skip_merge:
        raise RefreshError(
            "源路径不存在，拒绝执行（可用 --dry-run 看计划，或在有数据的机器上跑）: "
            + ", ".join(missing)
        )

    for step in steps:
        # 安全网：命令行里绝不能出现 dump_update
        if any("dump_update" in part for part in step.argv):
            raise RefreshError("内部错误：检测到 dump_update（已禁用）")
        if step.name.startswith("dump_bin") and f"--max_workers={DEFAULT_MAX_WORKERS}" not in step.argv:
            raise RefreshError("内部错误：dump_all 未钉死 max_workers=8")
        run_step(step)

    print("M1-A 三件套完成。swap/门禁见 M1-B；--archive/--offsite 见 M1-C。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RefreshError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
