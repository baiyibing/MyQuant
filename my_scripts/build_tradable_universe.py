"""构建可交易宇宙 instruments/all_tradable.txt：all.txt − ST 黑名单，起始日顺延 age_days 个交易日。

供给两处消费：
- 训练（--tradable-universe）：D.instruments(market="all_tradable")，ST/新股从源头不进训练与预测
- 文档与审计：宇宙收缩量一目了然

用法（需 qlib 数据目录）::

    python build_tradable_universe.py --st-asof 2026-09-14                # 默认 ST 剔除 + 60 交易日年龄顺延
    python build_tradable_universe.py --st-asof 2026-09-14 --age-days 60 --extra-exclude-file st_full.txt
    python build_tradable_universe.py --st-asof 2026-09-14 --st-daily-file {OSKH_SOURCE_PARQUET_ROOT}/vendor_wind_st_status/st_daily.parquet

注意：数据起始日=2020-01-02 的老股顺延后首日为 2020-03-30，但实验窗在 2025+，
全部老股不受影响；仅 2020 后真实上市的新股被顺延——这正是语义要求。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "my_scripts"))

from myquant_infra.adapters.qlib_data.universe import (  # noqa: E402
    build as build_membership,
    read_calendar,
)
from myquant_infra.reference_data.st.readers import load_st_codes_asof  # noqa: E402
from train_wiring import EXCLUDE_STOCKS_DEFAULT  # noqa: E402

DEFAULT_QLIB_DIR = Path.home() / ".qlib" / "qlib_data" / "my_data"


def build(
    qlib_dir: Path,
    age_days: int,
    extra_exclude_file: str | None,
    st_daily_file: str | None = None,
    st_asof: str | None = None,
) -> dict:
    if st_asof is None:
        raise ValueError("--st-asof is required to label the exclusion snapshot")
    cal = read_calendar(Path(qlib_dir) / "calendars" / "day.txt")
    exclude = {c.upper() for c in EXCLUDE_STOCKS_DEFAULT}
    extra_path = Path(extra_exclude_file) if extra_exclude_file else None
    if extra_path and extra_path.is_file():
        exclude |= {ln.strip().upper() for ln in extra_path.read_text(encoding="utf-8").splitlines() if ln.strip()}
    if st_daily_file:
        exclude |= load_st_codes_asof(st_daily_file, asof=st_asof)

    return build_membership(
        qlib_dir, exclusions=exclude, age_days=age_days, calendar=cal, asof=st_asof,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 all_tradable.txt（−ST、起始日顺延 age_days）")
    parser.add_argument("--qlib-dir", default=str(DEFAULT_QLIB_DIR))
    parser.add_argument("--age-days", type=int, default=60)
    parser.add_argument("--extra-exclude-file", default=None, help="每行一个 QLib 代码的补充黑名单")
    parser.add_argument(
        "--st-daily-file",
        default=None,
        help="vendor_wind_st_status/st_daily.parquet：按 --st-asof 并入当日 ST（必须显式指定日期）",
    )
    parser.add_argument("--st-asof", required=True, help="排除名单快照日期 YYYY-MM-DD；不隐式取最新日")
    args = parser.parse_args()
    stats = build(
        Path(args.qlib_dir).expanduser(),
        args.age_days,
        args.extra_exclude_file,
        st_daily_file=args.st_daily_file,
        st_asof=args.st_asof,
    )
    print(
        f"[tradable] 全宇宙 {stats['total']} → 剔除ST {stats['dropped_st']} → 保留 {stats['kept']}，"
        f"起始日顺延 {args.age_days} 个交易日 → {stats['path']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
