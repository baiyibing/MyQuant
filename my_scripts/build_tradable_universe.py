"""构建可交易宇宙 instruments/all_tradable.txt：all.txt − ST 黑名单，起始日顺延 age_days 个交易日。

供给两处消费：
- 训练（--tradable-universe）：D.instruments(market="all_tradable")，ST/新股从源头不进训练与预测
- 文档与审计：宇宙收缩量一目了然

用法（需 qlib 数据目录）::

    python build_tradable_university.py                # 默认 ST 剔除 + 60 交易日年龄顺延
    python build_tradable_universe.py --age-days 60 --extra-exclude-file st_full.txt
    python build_tradable_universe.py --st-daily-file F:/stock_data/vendor_wind_st_status/st_daily.parquet

注意：数据起始日=2020-01-02 的老股顺延后首日为 2020-03-30，但实验窗在 2025+，
全部老股不受影响；仅 2020 后真实上市的新股被顺延——这正是语义要求。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "my_scripts"))

from st_status import load_st_codes_asof  # noqa: E402
from train_wiring import EXCLUDE_STOCKS_DEFAULT  # noqa: E402

DEFAULT_QLIB_DIR = Path.home() / ".qlib" / "qlib_data" / "my_data"


def read_calendar(qlib_dir: Path) -> pd.DatetimeIndex:
    frame = pd.read_csv(Path(qlib_dir) / "calendars" / "day.txt", header=None, parse_dates=[0])
    return pd.DatetimeIndex(frame[0])


def drop_excluded(lines: list[str], exclude: set[str]) -> tuple[list[str], list[str]]:
    """剔除黑名单行，返回 (保留行, 剔除的代码)。大小写不敏感。"""
    want = {c.upper() for c in exclude}
    keep, dropped = [], []
    for ln in lines:
        symbol = ln.split("\t", 1)[0].strip().upper()
        if symbol in want:
            dropped.append(symbol)
        else:
            keep.append(ln)
    return keep, dropped


def shift_start_for_age(lines: list[str], calendar: pd.DatetimeIndex, age_days: int) -> list[str]:
    """每行的起始日顺延 age_days 个交易日；起始日在日历外（< 首日）的行不动。

    数据起始日在日历内 → 新起始 = calendar[pos(start)+age_days]；
    老股（start == 日历首日）同样顺延，实验窗在 2025+ 时全部不受影响。
    """
    pos = {d: i for i, d in enumerate(calendar)}
    out = []
    for ln in lines:
        parts = ln.split("\t")
        if len(parts) < 3:
            out.append(ln)
            continue
        code, start_s, end_s = parts[0], parts[1], parts[2]
        start = pd.Timestamp(start_s)
        idx = pos.get(start)
        if idx is None or idx + age_days >= len(calendar):
            new_start = start_s  # 日历外/顺延后越界：不动（越界股在窗内本就买不到）
        else:
            new_start = calendar[idx + age_days].strftime("%Y-%m-%d")
        out.append(f"{code}\t{new_start}\t{end_s}")
    return out


def build(
    qlib_dir: Path,
    age_days: int,
    extra_exclude_file: str | None,
    st_daily_file: str | None = None,
    st_asof: str | None = None,
    st_coverage_file: str | None = None,
) -> dict:
    cal = read_calendar(qlib_dir)
    all_path = Path(qlib_dir) / "instruments" / "all.txt"
    lines = [ln for ln in all_path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    exclude = {c.upper() for c in EXCLUDE_STOCKS_DEFAULT}
    extra_path = Path(extra_exclude_file) if extra_exclude_file else None
    if extra_path and extra_path.is_file():
        exclude |= {ln.strip().upper() for ln in extra_path.read_text(encoding="utf-8").splitlines() if ln.strip()}
    if st_daily_file:
        exclude |= load_st_codes_asof(
            st_daily_file,
            asof=st_asof,
            coverage_path=st_coverage_file,
            fallback_static=exclude,
        )

    kept, dropped = drop_excluded(lines, exclude)
    shifted = shift_start_for_age(kept, cal, age_days)

    out_path = Path(qlib_dir) / "instruments" / "all_tradable.txt"
    out_path.write_text("\n".join(shifted) + "\n", encoding="utf-8", newline="\n")
    return {"total": len(lines), "dropped_st": len(dropped), "kept": len(kept), "path": str(out_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 all_tradable.txt（−ST、起始日顺延 age_days）")
    parser.add_argument("--qlib-dir", default=str(DEFAULT_QLIB_DIR))
    parser.add_argument("--age-days", type=int, default=60)
    parser.add_argument("--extra-exclude-file", default=None, help="每行一个 QLib 代码的补充黑名单")
    parser.add_argument(
        "--st-daily-file",
        default=None,
        help="vendor_wind_st_status/st_daily.parquet：按 --st-asof 并入当日 ST（缺省矩阵末日）",
    )
    parser.add_argument("--st-asof", default=None, help="ST 过滤 as-of 日 YYYY-MM-DD，缺省用 daily 最后一天")
    parser.add_argument(
        "--st-coverage-file",
        default=None,
        help="st_coverage.json；缺省取 daily 同目录。未覆盖/unknown_end 仍走静态黑名单",
    )
    args = parser.parse_args()
    stats = build(
        Path(args.qlib_dir).expanduser(),
        args.age_days,
        args.extra_exclude_file,
        st_daily_file=args.st_daily_file,
        st_asof=args.st_asof,
        st_coverage_file=args.st_coverage_file,
    )
    print(
        f"[tradable] 全宇宙 {stats['total']} → 剔除ST {stats['dropped_st']} → 保留 {stats['kept']}，"
        f"起始日顺延 {args.age_days} 个交易日 → {stats['path']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
