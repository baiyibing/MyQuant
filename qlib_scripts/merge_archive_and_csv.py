# -*- coding: utf-8 -*-
"""合并旧 qlib bin 存档 + 最新 CSV 批 → dump_all 喂料目录。

场景（2026-09-13 实例）：CSV 批历史起点多数在 2022-07-26；旧 bin 存档字段全
但止于 2026-04-10。2026-09-14 批（F:\\qlibdata20260914\\qlibdata）多数已从
2020-01-02 起、并多出 winratio 列。重叠段数值经校验一致。本脚本按标的拼接：

- 双方都有：旧 bin 取 CSV 首日之前的行，拼到 CSV 前面（补旧 CSV 的 2020~2022 空洞；
  新批若已从 2020 起则前缀为空，整段走 CSV）
- 仅旧有（退市）：整段保留，否则退市股历史丢失
- 仅新有（新上市）：原样
- CSV 多出的列（如 winratio）并入 staging；旧档没有的日期填 NaN

只生成 staging（每股一个 parquet：date + 字段列）。写完用 dump_all 灌入
全新 qlib 目录（不要 dump_update——按个股日期 append，停牌即错位）::

    python qlib_scripts/merge_archive_and_csv.py \\
        --csv-dir F:/qlibdata --out-dir <staging>
    python qlib_scripts/dump_bin.py dump_all --data-path <staging> \\
        --qlib-dir <新目录> --file-suffix .parquet --max_workers 8
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from pathlib import Path

import numpy as np
import pandas as pd

ID_COLUMNS = {"code", "date", "symbol", "time"}


def extra_csv_fields(csv_columns: Iterable[str], archive_fields: Sequence[str]) -> list[str]:
    """CSV 有、旧档 bin 没有、且不是 id 列的字段（例：winratio）。"""
    seen = set(archive_fields)
    extra: list[str] = []
    for col in csv_columns:
        name = str(col).strip()
        if not name or name.lower() in ID_COLUMNS or name in seen:
            continue
        extra.append(name)
        seen.add(name)
    return extra


def read_bin_series(features_dir: Path, sym: str, field: str, calendar: pd.DatetimeIndex) -> pd.Series | None:
    path = features_dir / sym / f"{field}.day.bin"
    if not path.exists():
        return None
    arr = np.fromfile(path, dtype="<f")
    start = int(arr[0])
    return pd.Series(arr[1:], index=calendar[start : start + len(arr) - 1])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="合并旧 bin 存档 + 最新 CSV 批 → staging parquet")
    parser.add_argument("--archive-dir", default=str(Path.home() / ".qlib/qlib_data/my_data_20260410_archived"))
    parser.add_argument("--csv-dir", default="F:/qlibdata")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--start", default="2020-01-02", help="保留起点（含），早于该日丢弃")
    parser.add_argument("--symbols", default="", help="逗号分隔，仅处理指定标的（调试用）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    archive = Path(args.archive_dir).expanduser()
    csv_dir = Path(args.csv_dir).expanduser()
    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp(args.start)

    calendar = pd.to_datetime(pd.read_csv(archive / "calendars" / "day.txt", header=None)[0])
    features_dir = archive / "features"
    reference = next((features_dir / d for d in sorted(p.name for p in features_dir.iterdir()) if len(list((features_dir / d).glob("*.bin"))) >= 16), None)
    if reference is None:
        raise SystemExit("存档里找不到字段齐全的样本标的")
    archive_fields = sorted(p.name.split(".")[0] for p in reference.glob("*.day.bin"))
    csv_files = sorted(csv_dir.glob("*.csv"))
    extra_fields: list[str] = []
    if csv_files:
        extra_fields = extra_csv_fields(pd.read_csv(csv_files[0], nrows=0).columns, archive_fields)
    fields = archive_fields + extra_fields
    print(
        f"archive calendar: {calendar.min().date()} .. {calendar.max().date()} ({len(calendar)} 天); "
        f"archive_fields({len(archive_fields)}): {archive_fields}; extra_csv({len(extra_fields)}): {extra_fields}"
    )
    wanted = None
    if args.symbols:
        wanted = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}
        csv_files = [p for p in csv_files if p.stem.upper() in wanted]
    csv_map = {p.stem.upper(): p for p in csv_files}
    archive_syms = {p.name.upper(): p.name for p in features_dir.iterdir() if p.is_dir()}
    if wanted is not None:
        archive_syms = {k: v for k, v in archive_syms.items() if k in wanted}

    stats = {"merged": 0, "csv_only": 0, "archive_only": 0, "rows": 0}
    targets = sorted(set(csv_map) | set(archive_syms))
    for i, sym in enumerate(targets, 1):
        lower = archive_syms.get(sym, sym.lower())
        prefix_frames = []
        for field in archive_fields:
            series = read_bin_series(features_dir, lower, field, calendar)
            if series is None:
                continue
            prefix_frames.append(series.rename(field))
        if prefix_frames:
            prefix = pd.concat(prefix_frames, axis=1)
        else:
            prefix = pd.DataFrame(columns=archive_fields, index=pd.DatetimeIndex([]))
        for field in extra_fields:
            if field not in prefix.columns:
                prefix[field] = np.nan

        csv_path = csv_map.get(sym)
        if csv_path is not None:
            csv_df = pd.read_csv(csv_path, parse_dates=["date"]).set_index("date")
            csv_df = csv_df[[c for c in fields if c in csv_df.columns]]
            csv_first = csv_df.index.min()
            prefix = prefix[prefix.index < csv_first]
            frame = pd.concat([prefix, csv_df]) if len(prefix) else csv_df
            stats["merged" if len(prefix) else "csv_only"] += 1
        else:
            frame = prefix
            stats["archive_only"] += 1

        frame = frame[frame.index >= start]
        if frame.empty:
            continue
        frame = frame[~frame.index.duplicated(keep="last")].sort_index()
        frame = frame.reindex(columns=fields)
        # Windows/MSVC 会把 NaN 写成 -1.#IND，或截成 -1.#J（本批 CSV 分别在 vwap / winratio）。
        for col in fields:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        frame.reset_index(names="date").to_parquet(out_dir / f"{sym.lower()}.parquet", index=False)
        stats["rows"] += len(frame)
        if i % 500 == 0 or i == len(targets):
            print(f"[{i}/{len(targets)}] merged={stats['merged']} csv_only={stats['csv_only']} archive_only={stats['archive_only']} rows={stats['rows']}")
    print(f"done: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
