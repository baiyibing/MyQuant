"""Host exclusion policy and thin calls to the optional infra universe transform.

Example (all paths and the exclusion snapshot date are explicit)::

    python my_scripts/build_tradable_universe.py --qlib-dir /tmp/provider \
        --calendar /tmp/provider/calendars/day.txt --asof 2026-01-16 --age-days 60

The CLI resolves host static/extra/ST exclusions. The generic helpers and
``build`` only delegate to myquant-infra; they never load training policy.
Install the optional pin with ``python -m pip install -r requirements-infra.txt``.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from datetime import date
from importlib import import_module
from pathlib import Path
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

_INFRA_MODULE = "myquant_infra.adapters.qlib_data.universe"


class InstallError(ModuleNotFoundError):
    """The optional universe adapter is unavailable."""


def _universe():
    try:
        return import_module(_INFRA_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name in {
            "myquant_infra", "myquant_infra.adapters", "myquant_infra.adapters.qlib_data", _INFRA_MODULE,
        }:
            raise InstallError(
                "C4 tradable universe requires the optional requirements-infra.txt pin; "
                "install it with python -m pip install -r requirements-infra.txt",
                name=exc.name,
            ) from exc
        raise


def read_calendar(calendar_path: str | Path) -> pd.DatetimeIndex:
    """Read an explicit calendar file through infra (formerly a provider path)."""
    return _universe().read_calendar(calendar_path)


def drop_excluded(lines: list[str], exclude: Iterable[str]) -> tuple[list[str], list[str]]:
    return _universe().drop_excluded(lines, exclude)


def shift_start_for_age(lines: list[str], calendar: Iterable, age_days: int) -> list[str]:
    return _universe().shift_start_for_age(lines, calendar, age_days)


def build(
    qlib_dir: str | Path,
    *,
    exclusions: Iterable[str],
    age_days: int,
    calendar: Iterable,
    asof: str | date,
) -> dict:
    """Delegate IO with caller-resolved exclusions and an explicit snapshot label."""
    return _universe().build(
        qlib_dir, exclusions=exclusions, age_days=age_days, calendar=calendar, asof=asof,
    )


def resolve_exclusions(
    extra_exclude_file: str | Path | None,
    st_daily_file: str | Path | None,
    *,
    asof: str,
) -> set[str]:
    """Resolve MQ policy before calling the generic transform; never used by infra."""
    scripts = str(Path(__file__).resolve().parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from train_wiring import EXCLUDE_STOCKS_DEFAULT

    exclude = {code.upper() for code in EXCLUDE_STOCKS_DEFAULT}
    extra_path = Path(extra_exclude_file) if extra_exclude_file else None
    if extra_path and extra_path.is_file():
        exclude |= {line.strip().upper() for line in extra_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()}
    if st_daily_file:
        from st_status import load_st_codes_asof

        exclude |= load_st_codes_asof(st_daily_file, asof=asof)
    return exclude


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建 all_tradable.txt（host ST 排除集、infra 年龄顺延）")
    parser.add_argument("--qlib-dir", type=Path, required=True, help="显式 Qlib provider 路径（无 home 默认值）")
    parser.add_argument("--calendar", type=Path, required=True, help="显式交易日历文件，每行一个日期")
    parser.add_argument(
        "--asof", "--st-asof", type=date.fromisoformat, required=True,
        help="排除集 as-of 日 YYYY-MM-DD；同时传给 host ST 选择器与 infra 标签",
    )
    parser.add_argument("--age-days", type=int, default=60)
    parser.add_argument("--extra-exclude-file", type=Path, default=None, help="每行一个 QLib 代码的补充黑名单")
    parser.add_argument(
        "--st-daily-file", type=Path, default=None,
        help="vendor_wind_st_status/st_daily.parquet：由 host 按 --asof 解析 ST 排除集",
    )
    args = parser.parse_args(argv)
    # Fail with the install hint before loading host policy or reading inputs.
    _universe()
    asof = args.asof.isoformat()
    exclusions = resolve_exclusions(
        args.extra_exclude_file.expanduser() if args.extra_exclude_file else None,
        args.st_daily_file.expanduser() if args.st_daily_file else None,
        asof=asof,
    )
    stats = build(
        args.qlib_dir.expanduser(), exclusions=exclusions, age_days=args.age_days,
        calendar=read_calendar(args.calendar.expanduser()), asof=asof,
    )
    print(
        f"[tradable] 全宇宙 {stats['total']} → 剔除ST {stats['dropped_st']} → 保留 {stats['kept']}，"
        f"起始日顺延 {args.age_days} 个交易日 → {stats['path']} (asof={stats['asof']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
