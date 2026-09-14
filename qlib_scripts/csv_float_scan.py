# -*- coding: utf-8 -*-
"""扫描 CSV 批里的 Windows/MSVC 非法浮点串。

2026-09-14 全量扫描 F:\\qlibdata20260914\\qlibdata（5561 文件）只见两种写法：
- ``-1.#J``：MSVC NaN 截断，出现在 winratio
- ``-1.#IND``：标准 Windows NaN，出现在 0 成交日的 vwap

OHLC / volume / factor 若出现这类串，说明导出坏了，应中止入库。
winratio / vwap 上的串由 merge/dump 的 ``pd.to_numeric(..., errors="coerce")`` 收成 NaN。
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

ILLEGAL_FLOAT_RE = re.compile(rb"-?1\.#(?:J|IND|QNAN|INF)", re.IGNORECASE)
ILLEGAL_CELL_RE = re.compile(r"-?1\.#(?:J|IND|QNAN|INF)", re.IGNORECASE)

PRICE_FIELDS = frozenset(
    {
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "factor",
        "adjclose",
    }
)
ID_COLUMNS = {"code", "date", "symbol", "time"}


def file_has_illegal_float(path: Path) -> bool:
    return ILLEGAL_FLOAT_RE.search(path.read_bytes()) is not None


def inspect_csv_illegal(path: Path) -> list[dict]:
    """返回该文件里非法浮点按列的统计。文件干净则空列表。"""
    if not file_has_illegal_float(path):
        return []
    # pandas 默认 na_values 含 -1.#IND，会在进单元格前吞掉；扫描必须 keep_default_na=False
    frame = pd.read_csv(path, dtype=str, low_memory=False, keep_default_na=False)
    hits: list[dict] = []
    for col in frame.columns:
        name = str(col).strip()
        if name.lower() in ID_COLUMNS:
            continue
        mask = frame[col].fillna("").map(lambda x: bool(ILLEGAL_CELL_RE.search(str(x))))
        n = int(mask.sum())
        if n == 0:
            continue
        first_idx = int(mask.idxmax())
        first_val = str(frame.loc[first_idx, col])
        first_date = ""
        if "date" in frame.columns:
            first_date = str(frame.loc[first_idx, "date"])
        hits.append(
            {
                "file": path.name,
                "column": name,
                "count": n,
                "rows": int(len(frame)),
                "first_date": first_date,
                "sample": first_val,
                "fatal": name.lower() in PRICE_FIELDS,
            }
        )
    return hits


def scan_csv_dir(csv_dir: Path) -> dict:
    """扫描目录下全部 CSV。返回 hits / fatal / warn / files_scanned。"""
    csv_dir = Path(csv_dir)
    files = sorted(csv_dir.glob("*.csv"))
    hits: list[dict] = []
    for path in files:
        hits.extend(inspect_csv_illegal(path))
    fatal = [h for h in hits if h["fatal"]]
    warn = [h for h in hits if not h["fatal"]]
    return {
        "files_scanned": len(files),
        "files_hit": len({h["file"] for h in hits}),
        "hits": hits,
        "fatal": fatal,
        "warn": warn,
    }


def format_scan_report(report: dict) -> str:
    lines = [
        f"[csv-scan] files={report['files_scanned']} hit={report['files_hit']} "
        f"fatal={len(report['fatal'])} warn={len(report['warn'])}"
    ]
    for h in report["fatal"][:20]:
        lines.append(
            f"  FATAL {h['file']} {h['column']} {h['count']}/{h['rows']} "
            f"from {h['first_date'] or '?'} sample={h['sample']}"
        )
    for h in report["warn"][:20]:
        lines.append(
            f"  WARN  {h['file']} {h['column']} {h['count']}/{h['rows']} "
            f"from {h['first_date'] or '?'} sample={h['sample']}"
        )
    extra = len(report["warn"]) - 20
    if extra > 0:
        lines.append(f"  ... {extra} more warn rows")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="扫描 CSV 批中的 MSVC/Windows 非法浮点串")
    p.add_argument("--csv-dir", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = scan_csv_dir(Path(args.csv_dir))
    print(format_scan_report(report))
    return 2 if report["fatal"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
