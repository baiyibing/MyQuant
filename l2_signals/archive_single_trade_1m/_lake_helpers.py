"""从 ops `l2_rollup_daily.py`（删前）抽出的最小湖分区辅助，仅服务本目录归档脚本。

不写湖；不替代 MyQuant-infra 的 rollup SSOT。
源：grok-bot-ops@022f820^ scripts/ops/l2_rollup_daily.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

try:
    import duckdb
except ImportError:  # pragma: no cover
    duckdb = None


def sql_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def stable_hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()[:20]


def source_signature(paths):
    """低 IO 失效标记；不是内容校验和，同大小同 mtime 的替换需 --refresh。"""
    return [
        {
            "path": p.resolve().as_posix(),
            "size": p.stat().st_size,
            "mtime_ns": p.stat().st_mtime_ns,
        }
        for p in paths
    ]


def partition_days(lake):
    days = []
    for p in Path(lake).glob("date=*"):
        if p.is_dir():
            try:
                days.append(date.fromisoformat(p.name[5:]).isoformat())
            except ValueError:
                continue
    return sorted(days)


def select_days(lake, start=None, end=None, lookback=0, forward=0):
    """按实际湖分区取范围及前后 N 个分区；不冒充交易所完整交易日历。"""
    days = partition_days(lake)
    selected = [
        i
        for i, d in enumerate(days)
        if (not start or d >= start) and (not end or d <= end)
    ]
    if not selected:
        return []
    return days[
        max(0, selected[0] - lookback) : min(len(days), selected[-1] + forward + 1)
    ]


def validate_unique_keys(con, tables=("main_src", "order_src")):
    errors = []
    for table in tables:
        nulls = con.execute(
            f'SELECT count(*) FROM {table} WHERE stock_code IS NULL OR "TranID" IS NULL'
        ).fetchone()[0]
        if nulls:
            errors.append(f"{table}: NULL keys={nulls}")
        duplicates = con.execute(
            f'''
            SELECT stock_code, count(*) duplicate_keys, sum(n-1) excess_rows
            FROM (SELECT stock_code, "TranID", count(*) n FROM {table}
                  GROUP BY 1,2 HAVING count(*)>1) GROUP BY 1 ORDER BY 1
        '''
        ).fetchall()
        errors.extend(
            f"{table}: stock_code={sc} duplicate_keys={n} excess_rows={extra}"
            for sc, n, extra in duplicates
        )
    if errors:
        raise ValueError(
            "duplicate/invalid (stock_code,TranID); on-dup=fail\n" + "\n".join(errors)
        )


def iso_date(value):
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc
