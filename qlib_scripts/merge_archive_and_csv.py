# -*- coding: utf-8 -*-
"""合并旧 qlib bin 存档 + 最新 CSV 批 → dump_all 喂料目录。

场景（2026-09-13 实例）：CSV 批历史起点多数在 2022-07-26；旧 bin 存档字段全
但止于 2026-04-10。2026-09-14 批（F:\\qlibdata20260914\\qlibdata）多数已从
2020-01-02 起、并多出 winratio 列。重叠段数值经校验一致。本脚本按标的拼接：

- 双方都有：``overlay_csv_on_archive``——只把 CSV **有值**的单元格盖到旧档上。
  缺列或整列/单元格为空（短尾巴无 ``winratio``）保留旧档。禁止「按 CSV 首日
  截断再 concat」，那会把重叠段赢筹打成 NaN。
- 仅旧有（退市）：整段保留，否则退市股历史丢失
- 仅新有（新上市）：原样
- CSV 多出的列（如 winratio）并入 staging；旧档没有的日期填 NaN

只生成 staging（每股一个 parquet：date + 字段列）。写完用 dump_all 灌入
全新 qlib 目录（不要 dump_update——按个股日期 append，停牌即错位）::

    python qlib_scripts/merge_archive_and_csv.py \\
        --csv-dir <OSKH_QLIB_CSV_DIR> --out-dir <staging>
    python qlib_scripts/dump_bin.py dump_all --data-path <staging> \\
        --qlib-dir <新目录> --file-suffix .parquet --max_workers 8
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

_MY_SCRIPTS = Path(__file__).resolve().parents[1] / "my_scripts"
if str(_MY_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_MY_SCRIPTS))
from data_root import resolve_qlib_csv_dir  # noqa: E402

import numpy as np
import pandas as pd

ID_COLUMNS = {"code", "date", "symbol", "time"}
SHORT_TAIL_MAX_DAYS = 60


def column_is_effectively_empty(series: pd.Series) -> bool:
    """空串 / None / 非法浮点都算空；短尾巴里的空 winratio 应忽略而不是盖旧档。"""
    if series is None or len(series) == 0:
        return True
    return int(pd.to_numeric(series, errors="coerce").notna().sum()) == 0


def overlay_csv_on_archive(
    archive: pd.DataFrame,
    csv_df: pd.DataFrame,
    fields: Sequence[str],
) -> pd.DataFrame:
    """短尾巴 CSV 只覆盖有值的单元格；缺列或空值保留 archive。

    2026-09-15 增量批（``F:\\qlibdata20260915\\qlibdata``）约 10 个交易日、
    **没有 winratio 列**。用户口径：空/缺该字段就忽略，不要删 ``$winratio`` bin。
    若先按 CSV 首日截断再 concat，重叠段赢筹会被盖成 NaN。
    """
    usable = [c for c in fields if c in csv_df.columns]
    if archive is None or len(archive) == 0:
        frame = csv_df[usable].copy() if usable else pd.DataFrame(index=getattr(csv_df, "index", None))
        for col in list(frame.columns):
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        return frame.reindex(columns=list(fields))
    if not usable:
        return archive.copy().reindex(columns=list(fields))

    idx = archive.index.union(csv_df.index)
    frame = archive.reindex(idx)
    for col in usable:
        values = pd.to_numeric(csv_df[col], errors="coerce")
        valid = values.dropna()
        if len(valid) == 0:
            continue
        frame.loc[valid.index, col] = valid.to_numpy()
    return frame.reindex(columns=list(fields))


def list_archive_fields(archive_dir: Path, *, min_bins: int = 16) -> list[str]:
    """从存档 features 里找一只字段齐全的票，列出 ``*.day.bin`` 字段名。"""
    features = Path(archive_dir) / "features"
    if not features.is_dir():
        return []
    for name in sorted(p.name for p in features.iterdir() if p.is_dir()):
        bins = list((features / name).glob("*.day.bin"))
        if len(bins) >= min_bins:
            return sorted(p.name.split(".")[0] for p in bins)
    return []


def _sample_csv_paths(files: Sequence[Path], limit: int = 2) -> list[Path]:
    if not files:
        return []
    if len(files) == 1 or limit <= 1:
        return [files[0]]
    picked = [files[0], files[-1]]
    if limit >= 3 and len(files) > 2:
        picked.insert(1, files[len(files) // 2])
    return picked[:limit]


def profile_csv_batch(
    csv_dir: Path,
    archive_fields: Sequence[str] | None = None,
    *,
    sample_files: int = 2,
) -> dict:
    """入库前看清：是全历史还是短尾巴、缺哪些旧档列、哪些列整列为空。"""
    csv_dir = Path(csv_dir)
    files = sorted(csv_dir.glob("*.csv")) if csv_dir.is_dir() else []
    archive_fields = [str(f) for f in (archive_fields or [])]
    empty: dict = {
        "files": 0,
        "columns": [],
        "date_min": None,
        "date_max": None,
        "approx_days": 0,
        "short_tail": False,
        "missing_vs_archive": list(archive_fields),
        "empty_ignored": [],
        "note": "csv_dir 无 csv",
    }
    if not files:
        return empty

    header = [str(c).strip() for c in pd.read_csv(files[0], nrows=0).columns]
    columns = [c for c in header if c.lower() not in ID_COLUMNS]
    missing = [f for f in archive_fields if f not in header]
    sampled = _sample_csv_paths(files, limit=sample_files)
    mins: list[pd.Timestamp] = []
    maxs: list[pd.Timestamp] = []
    day_counts: list[int] = []
    empty_votes = {c: 0 for c in columns}
    for path in sampled:
        frame = pd.read_csv(path)
        if "date" in frame.columns:
            dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
            if len(dates):
                mins.append(pd.Timestamp(dates.min()))
                maxs.append(pd.Timestamp(dates.max()))
                day_counts.append(int(dates.nunique()))
        for col in columns:
            if col not in frame.columns or column_is_effectively_empty(frame[col]):
                empty_votes[col] += 1
    empty_ignored = [c for c, n in empty_votes.items() if sampled and n == len(sampled)]
    date_min = min(mins) if mins else None
    date_max = max(maxs) if maxs else None
    approx_days = max(day_counts) if day_counts else 0
    short_tail = bool(approx_days and approx_days < SHORT_TAIL_MAX_DAYS)
    notes: list[str] = []
    if short_tail:
        notes.append("短尾巴：只覆盖 CSV 有值的列，仍 dump_all")
    if missing or empty_ignored:
        notes.append(f"缺/空列忽略（保留旧档） missing={missing} empty={empty_ignored}")
    if "winratio" in missing or "winratio" in empty_ignored:
        notes.append("不删 $winratio bin")
    if not notes:
        notes.append("列齐全，重叠日以 CSV 有值为准")
    return {
        "files": len(files),
        "columns": columns,
        "date_min": None if date_min is None else str(date_min.date()),
        "date_max": None if date_max is None else str(date_max.date()),
        "approx_days": approx_days,
        "short_tail": short_tail,
        "missing_vs_archive": missing,
        "empty_ignored": empty_ignored,
        "note": "；".join(notes),
    }


def format_csv_profile(profile: dict) -> str:
    dates = f"{profile.get('date_min') or '?'} .. {profile.get('date_max') or '?'}"
    cols = profile.get("columns") or []
    preview = ",".join(cols[:12])
    if len(cols) > 12:
        preview += ",..."
    return (
        f"[csv-profile] files={profile.get('files', 0)} dates={dates} "
        f"days≈{profile.get('approx_days', 0)} short_tail={profile.get('short_tail', False)}\n"
        f"  columns({len(cols)}): {preview or '-'}\n"
        f"  missing_vs_archive={profile.get('missing_vs_archive') or []}\n"
        f"  empty_ignored={profile.get('empty_ignored') or []}\n"
        f"  note: {profile.get('note') or '-'}"
    )


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
    parser.add_argument(
        "--csv-dir",
        default="",
        help="券商 CSV 批；缺省读 OSKH_QLIB_CSV_DIR，都没有则报错",
    )
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--start", default="2020-01-02", help="保留起点（含），早于该日丢弃")
    parser.add_argument("--symbols", default="", help="逗号分隔，仅处理指定标的（调试用）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    archive = Path(args.archive_dir).expanduser()
    csv_dir = resolve_qlib_csv_dir(explicit_root=args.csv_dir or None)
    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp(args.start)

    calendar = pd.to_datetime(pd.read_csv(archive / "calendars" / "day.txt", header=None)[0])
    features_dir = archive / "features"
    archive_fields = list_archive_fields(archive)
    if not archive_fields:
        raise SystemExit("存档里找不到字段齐全的样本标的")
    csv_files = sorted(csv_dir.glob("*.csv"))
    extra_fields: list[str] = []
    if csv_files:
        extra_fields = extra_csv_fields(pd.read_csv(csv_files[0], nrows=0).columns, archive_fields)
    fields = archive_fields + extra_fields
    print(
        f"archive calendar: {calendar.min().date()} .. {calendar.max().date()} ({len(calendar)} 天); "
        f"archive_fields({len(archive_fields)}): {archive_fields}; extra_csv({len(extra_fields)}): {extra_fields}"
    )
    print(format_csv_profile(profile_csv_batch(csv_dir, archive_fields)))
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
            had_prefix = len(prefix) > 0
            frame = overlay_csv_on_archive(prefix, csv_df, fields)
            stats["merged" if had_prefix else "csv_only"] += 1
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
