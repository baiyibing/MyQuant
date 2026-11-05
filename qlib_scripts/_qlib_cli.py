"""MQ CLI declarations, usable before the optional production package is loaded.

Options mirror myquant-infra 3c377e9718e811112993579b6d91a603395db699
``adapters/qlib_data/_arguments.py`` and ``cli.py``. Keep these in sync when
updating the pin; host tests compare the declarations to the installed adapter.
"""

import argparse
import sys
from pathlib import Path

DEFAULT_MAX_WORKERS = 8
REQUIRED_WORKERS = 8
DEFAULT_EXPECTED_DELIST_MAX = 50
DEFAULT_LAKE_SYMBOL = "000001_SH"
DEFAULT_SYMBOLS = "000300_SH,000001_SH"
MIN_DUMP_FREE_GB = 3.0
MIN_STAGING_FREE_GB = 2.0
WINDOW_START = "2020-01-02"
WINDOW_END = "2026-10-13"


def refresh_mydata_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="my_data 全量刷新编排器（merge→dump_all(8)→patch）")
    p.add_argument("--archive-dir", required=True)
    p.add_argument(
        "--csv-dir",
        required=True,
        help="CSV batch directory",
    )
    p.add_argument("--qlib-dir", required=True, help="线上目标目录（swap 终点）")
    p.add_argument("--staging-dir", required=True, help="merge output directory")
    p.add_argument("--new-qlib-dir", required=True, help="new provider directory for dump_all")
    p.add_argument(
        "--lake-index-root",
        required=True,
        help="index daily none partition root",
    )
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
        help="异地根目录，可重复；--offsite 时必填，不猜 F:/G:",
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
    p.add_argument("--csv-validator", help="injected validator module:callable returning a fatal report")
    p.add_argument("--verify-patch", action="store_true", help="qlib readback after patch (requires qlib extra)")
    p.add_argument("--min-dump-free-gb", type=float, default=MIN_DUMP_FREE_GB)
    p.add_argument("--min-staging-free-gb", type=float, default=MIN_STAGING_FREE_GB)
    return p


def merge_archive_and_csv_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="合并旧 bin 存档 + 最新 CSV 批 → staging parquet")
    parser.add_argument("--archive-dir", required=True)
    parser.add_argument(
        "--csv-dir",
        required=True,
        help="CSV batch directory",
    )
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--start", default="2020-01-02", help="保留起点（含），早于该日丢弃")
    parser.add_argument("--symbols", default="", help="逗号分隔，仅处理指定标的（调试用）")
    return parser


def patch_index_data_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="湖指数日线 → qlib bin 增量补丁")
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS, help="湖分区名，逗号分隔，如 000300_SH,000001_SH")
    parser.add_argument(
        "--lake-root",
        required=True,
        help="index daily none partition root",
    )
    parser.add_argument("--qlib-dir", required=True, help="qlib 数据目录")
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--no-backup", action="store_true", help="跳过备份（首次运行不要用）")
    parser.add_argument("--skip-verify", action="store_true", help="跳过末尾的 qlib 读回验证")
    parser.add_argument("--force", action="store_true", help="覆盖率有缺口时仍继续（默认中止）")
    return parser


def refresh_mydata_1min_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh qlib 1min bins (not daily my_data)")
    parser.add_argument("--lake-root", type=Path, required=True)
    parser.add_argument("--index-lake", type=Path, default=None)
    parser.add_argument("--skip-index", action="store_true")
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--qlib-dir", type=Path, required=True)
    parser.add_argument("--daily-dir", type=Path, required=True, help="daily provider to protect")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--rebuild", action="store_true", help="dump_all even if my_data_1min exists")
    parser.add_argument("--skip-stage", action="store_true")
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    parser.add_argument("--receipt", type=Path, default=None, help="write QL11 1min increment receipt JSON on success")
    return parser


def stage_1min_from_lake_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage hive 1m parquet for qlib dump_bin --freq=1min")
    parser.add_argument("--lake-root", type=Path, required=True, help="stock 1m/none partition root")
    parser.add_argument("--index-lake", type=Path, default=None, help="index 1m/none partition root; otherwise use --skip-index")
    parser.add_argument("--skip-index", action="store_true")
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--symbols", nargs="*", help="SZ000001 / 000001.SZ / 000001_SZ")
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    return parser


def build_mydata_1min_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage + dump qlib 1min bins (not my_data)")
    parser.add_argument("--lake-root", type=Path, required=True)
    parser.add_argument("--index-lake", type=Path, default=None)
    parser.add_argument("--skip-index", action="store_true")
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--qlib-dir", type=Path, required=True)
    parser.add_argument("--daily-dir", type=Path, required=True, help="daily provider to protect")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--all-symbols", action="store_true", help="Dump every lake partition (large)")
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    parser.add_argument("--skip-stage", action="store_true")
    return parser


def stage_etf_daily_from_lake_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage ETF daily front parquet for qlib dump_bin")
    parser.add_argument("--lake-root", type=Path, required=True, help="dividend_type=front partition root")
    parser.add_argument("--none-root", type=Path, default=None, help="dividend_type=none；缺省为 front 的同级目录")
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--start", default=WINDOW_START)
    parser.add_argument("--end", default=WINDOW_END)
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    return parser


def build_etf_qlib_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a separate ETF provider from ETF daily front")
    parser.add_argument("--lake-root", type=Path, required=True)
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--qlib-dir", type=Path, required=True)
    parser.add_argument("--protected-dir", type=Path, action="append", required=True, help="daily/minute providers to protect; repeat for both")
    parser.add_argument("--meta-dir", type=Path, default=None)
    parser.add_argument("--max-workers", type=int, default=REQUIRED_WORKERS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--wipe-qlib-dir", action="store_true")
    parser.add_argument("--skip-verify", action="store_true")
    return parser


def dump_parser():
    parser = argparse.ArgumentParser(description="CSV/parquet to qlib float32 bins (no qlib required)")
    parser.add_argument("mode", choices=["dump_all", "dump_fix", "dump_update"])
    for option in ("data_path", "qlib_dir"):
        parser.add_argument("--" + option, "--" + option.replace("_", "-"), required=True)
    for option, default in (("backup_dir", None), ("freq", "day"), ("date_field_name", "date"),
                            ("file_suffix", ".csv"), ("symbol_field_name", "symbol"),
                            ("exclude_fields", ""), ("include_fields", "")):
        flags = ["--" + option]
        if "_" in option:
            flags.append("--" + option.replace("_", "-"))
        parser.add_argument(*flags, default=default)
    parser.add_argument("--max_workers", "--max-workers", type=int, default=8)
    parser.add_argument("--limit_nums", "--limit-nums", type=int)
    return parser


def check_bin_parser():
    parser = argparse.ArgumentParser(description="Compare provider fields to CSV/parquet (requires qlib)")
    parser.add_argument("--qlib-dir", required=True)
    parser.add_argument("--csv-path", required=True)
    parser.add_argument("--check-fields")
    parser.add_argument("--freq", default="day")
    parser.add_argument("--symbol-field-name", default="symbol")
    parser.add_argument("--date-field-name", default="date")
    parser.add_argument("--file-suffix", default=".csv")
    parser.add_argument("--max-workers", type=int, default=8)
    return parser


def health_parser():
    parser = argparse.ArgumentParser(description="Check OHLCV/factor health in CSV or a qlib provider")
    roots = parser.add_mutually_exclusive_group(required=True)
    roots.add_argument("--csv-path")
    roots.add_argument("--qlib-dir")
    parser.add_argument("--freq", default="day")
    parser.add_argument("--large-step-threshold-price", type=float, default=0.5)
    parser.add_argument("--large-step-threshold-volume", type=float, default=3)
    parser.add_argument("--missing-data-num", type=int, default=0)
    return parser
