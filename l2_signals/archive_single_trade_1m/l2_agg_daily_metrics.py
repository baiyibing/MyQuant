"""单笔百万成交实验的数据准备；仅 main，无 main/order join。

归档自 grok-bot-ops `scripts/ops/l2_agg_daily_metrics.py`（删于 022f820）。
口径：单笔成交额 ≥100 万（≠ 订单聚合 ≥10 万 SSOT）。结论见
`docs/l2_signals/2026-10-30-single-trade-1m-verify-archive.md`。

按 --start/--end 动态发现湖分区，另带 --lookback 个前置分区及
--forward-days 个后置分区。默认各1个用于上一观测日放量和下一观测日收益。
缺档/停牌不等同交易所日历：report 的 lag/lead 仍是该票相邻有成交观测日。
缓存含口径/SQL代码哈希及源文件 size/mtime；源被原地替换却保留二者时用 --refresh。
旧的 <lake> <out_csv> [concurrency] 位置参数继续支持，推荐显式命名参数。
USB HDD 推荐 concurrency=1；新版本增加唯一性检查，旧33分钟测速不能直接套用。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from _lake_helpers import (  # noqa: E402
    duckdb,
    iso_date,
    select_days,
    source_signature,
    sql_literal,
    stable_hash,
    validate_unique_keys,
)

CACHE_VERSION = "single-trade-v3"
AGG_SQL = '''
    SELECT CAST({day} AS DATE) d, stock_code,
           sum(CAST(Price AS DOUBLE)*Volume) total_amt,
           sum(CASE WHEN CAST(Price AS DOUBLE)*Volume>=1000000 THEN Volume ELSE 0 END) big1_vol,
           sum(CASE WHEN CAST(Price AS DOUBLE)*Volume>=1000000 THEN CAST(Price AS DOUBLE)*Volume ELSE 0 END) big1_amt,
           sum(CASE WHEN CAST(Price AS DOUBLE)*Volume>=1000000 AND Type='B' THEN CAST(Price AS DOUBLE)*Volume ELSE 0 END) big1_buy_amt,
           sum(CASE WHEN CAST(Price AS DOUBLE)*Volume>=5000000 THEN Volume ELSE 0 END) big5_vol,
           sum(CASE WHEN CAST(Price AS DOUBLE)*Volume>=5000000 THEN CAST(Price AS DOUBLE)*Volume ELSE 0 END) big5_amt,
           sum(CASE WHEN CAST(Price AS DOUBLE)*Volume>=5000000 AND Type='B' THEN CAST(Price AS DOUBLE)*Volume ELSE 0 END) big5_buy_amt,
           sum(CASE WHEN Type='B' THEN CAST(Price AS DOUBLE)*Volume ELSE 0 END) buy_amt,
           arg_max(CAST(Price AS DOUBLE),TranID) close_px
    FROM main_src WHERE instrument_type='stock' GROUP BY stock_code
'''


def process_day(lake, parts, day, params, threads=8, refresh=False):
    source = lake / f"date={day}" / "main.parquet"
    sig = source_signature([source])
    expected = {"parameters": params, "sources": sig}
    fragment = parts / f"{day}.csv"
    meta = fragment.with_suffix(".meta.json")
    if not refresh and fragment.is_file() and fragment.stat().st_size and meta.is_file():
        try:
            if json.loads(meta.read_text(encoding="utf-8")) == expected:
                return fragment, True
        except (ValueError, OSError):
            pass
    parts.mkdir(parents=True, exist_ok=True)
    tmp = fragment.with_suffix(".tmp.csv")
    spill = parts / "_duckdb_tmp" / day
    try:
        with duckdb.connect() as con:
            con.execute(f"SET threads={threads}")
            spill.mkdir(parents=True, exist_ok=True)
            con.execute(f"SET temp_directory={sql_literal(spill.as_posix())}")
            con.execute(
                f"CREATE TEMP TABLE main_src AS SELECT stock_code,date,TranID,Price,Volume,Type,instrument_type "
                f"FROM read_parquet({sql_literal(source.as_posix())},hive_partitioning=false)"
            )
            validate_unique_keys(con, ("main_src",))
            bad = con.execute(
                "SELECT count(*) FROM main_src WHERE date IS NULL OR CAST(date AS DATE)<>CAST(? AS DATE)",
                [day],
            ).fetchone()[0]
            if bad:
                raise ValueError(f"wrong partition date: {day}, rows={bad}")
            bad = con.execute(
                """SELECT stock_code,count(*) FROM main_src
                WHERE instrument_type='stock' AND (Price IS NULL OR Price<=0 OR
                    NOT isfinite(CAST(Price AS DOUBLE)) OR Volume IS NULL OR Volume<=0)
                GROUP BY 1"""
            ).fetchall()
            if bad:
                raise ValueError(f"invalid stock Price/Volume: {bad}")
            try:
                con.execute(
                    f"COPY ({AGG_SQL.format(day=sql_literal(day))}) TO {sql_literal(tmp.as_posix())} (FORMAT CSV, HEADER)"
                )
                if source_signature([source]) != sig:
                    raise ValueError(f"source changed during processing: {day}")
                meta.unlink(missing_ok=True)
                os.replace(tmp, fragment)
                meta_tmp = meta.with_suffix(".tmp.json")
                meta_tmp.write_text(
                    json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                os.replace(meta_tmp, meta)
            finally:
                tmp.unlink(missing_ok=True)
    finally:
        shutil.rmtree(spill, ignore_errors=True)
    return fragment, False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("lake_pos", nargs="?", type=Path)
    ap.add_argument("out_pos", nargs="?", type=Path)
    ap.add_argument("concurrency_pos", nargs="?", type=int)
    ap.add_argument("--lake", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--start", type=iso_date, default="2026-01-01")
    ap.add_argument("--end", type=iso_date, default="2026-12-31")
    ap.add_argument(
        "--lookback",
        type=int,
        default=1,
        help="放量基准所需前置湖分区数；N日均量基准请设至少N",
    )
    ap.add_argument("--forward-days", type=int, default=1, help="T+1所需后置湖分区数")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--concurrency", type=int)
    ap.add_argument("--on-dup", choices=("fail",), default="fail")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args(argv)
    if duckdb is None:
        ap.error("duckdb is required")
    if args.start > args.end or min(args.lookback, args.forward_days) < 0 or args.threads < 1:
        ap.error("invalid date range/lookback/forward-days/threads")
    lake = args.lake or args.lake_pos or Path("J:/l2_lake/l2_parquet")
    out = args.out or args.out_pos or Path("E:/stock_data/l2_research/single_trade_1m/agg_v2.csv")
    concurrency = args.concurrency if args.concurrency is not None else args.concurrency_pos
    concurrency = 1 if concurrency is None else concurrency
    if concurrency < 1:
        ap.error("concurrency must be positive")
    days = select_days(lake, args.start, args.end, args.lookback, args.forward_days)
    if not days:
        ap.error("no date partitions selected")
    here = Path(__file__).resolve()
    params = {
        "version": CACHE_VERSION,
        "sql": AGG_SQL,
        "on_dup": args.on_dup,
        "code_hash": hashlib.sha256(here.read_bytes()).hexdigest(),
        "validator_hash": hashlib.sha256(here.with_name("_lake_helpers.py").read_bytes()).hexdigest(),
        "duckdb_version": duckdb.__version__,
    }
    ph = stable_hash(params)
    parts = Path(str(out) + ".parts") / f"{CACHE_VERSION}-{ph}"
    began = time.monotonic()

    def run(day):
        t0 = time.monotonic()
        fragment, skip = process_day(lake, parts, day, params, args.threads, args.refresh)
        print(f"{day} {'SKIP' if skip else 'OK'} {time.monotonic()-t0:.1f}s", flush=True)
        return fragment

    try:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            fragments = list(executor.map(run, days))
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(out.suffix + ".tmp")
        n = 0
        with tmp.open("w", encoding="utf-8", newline="") as fout:
            for i, fragment in enumerate(fragments):
                with fragment.open(encoding="utf-8", newline="") as fin:
                    header = fin.readline()
                    if i == 0:
                        fout.write(header)
                    for line in fin:
                        fout.write(line)
                        n += 1
        os.replace(tmp, out)
        meta = out.with_suffix(out.suffix + ".meta.json")
        meta_tmp = meta.with_suffix(".tmp.json")
        meta_tmp.write_text(
            json.dumps(
                {
                    "params_hash": ph,
                    "parameters": params,
                    "days": days,
                    "start": args.start,
                    "end": args.end,
                    "lookback": args.lookback,
                    "forward_days": args.forward_days,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        os.replace(meta_tmp, meta)
    except (ValueError, OSError, duckdb.Error) as exc:
        print(f"FAIL: {exc}", file=sys.stderr, flush=True)
        return 1
    print(
        f"DONE days={len(days)} rows={n} wall={time.monotonic()-began:.1f}s params={ph}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
