# -*- coding: utf-8 -*-
"""湖指数日线 → qlib bin 增量补丁（湖根 = OSKH_SOURCE_PARQUET_ROOT）。

固化 2026-09-12 的手工修补流程（当天为修 PortAna benchmark 缺 SH000300 实跑过一遍）：
my_data 是纯个股数据，无任何指数行情，Qlib 回测的 benchmark 会因数据不存在直接抛
``ValueError: The benchmark ['SH000300'] does not exist``。

流程：备份 qlib_dir → 从湖裁剪指数日线 → ``dump_bin.DumpDataFix`` 增量写入 →
把指数行从 ``instruments/all.txt`` 挪到独立的 ``instruments/index.txt`` → qlib 读回验证。

两个必须知道的坑（都踩过，别绕开脚本手工做）：
1. 湖的 ``time`` 列是 **UTC 毫秒**，须转 Asia/Shanghai 再取日期；直接按 UTC 取日期会错一天。
2. ``DumpDataFix`` 会把新标的写进 ``instruments/all.txt``，而训练宇宙 ``market="all"``
   读的就是 all.txt——指数混进去会污染训练样本，且名单导出会把 ``SH000300`` 剥成
   ``000300`` 当股票买。所以必须执行 all.txt → index.txt 的挪移（本脚本自动做）。
3. ``DumpDataFix`` **不更新** all.txt 里已有标的的起止日。dump_all 若先把指数按 staging
   旧尾巴写进 all.txt，挪到 index.txt 后区间会停在旧末日（bin 已是全日历）。脚本在挪移后
   用日历首末日 ``upsert_index_txt_dates``。

用法::

    python qlib_scripts/patch_index_data.py                        # 默认补 SH000300 + SH000001
    python qlib_scripts/patch_index_data.py --symbols 000905_SH   # 补别的指数
    python qlib_scripts/patch_index_data.py --skip-verify --no-backup   # 快速重跑

验证语义：benchmark 查询（``D.features(['SH000300'], ...)``）不依赖 all.txt 会员资格，
index.txt 同时提供 ``market="index"`` 池。回滚：删除 ``features/shXXXXXX/`` 目录并从
index.txt 去掉对应行，或整体还原备份目录。
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "my_scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "my_scripts"))
from data_root import resolve_index_1d_none  # noqa: E402

DEFAULT_QLIB_DIR = Path.home() / ".qlib" / "qlib_data" / "my_data"
DEFAULT_SYMBOLS = "000300_SH,000001_SH"
FIELDS = ["open", "high", "low", "close", "volume", "amount"]


def lake_to_qlib_code(lake_symbol: str) -> str:
    """湖分区名 → qlib instrument：``000300_SH`` → ``SH000300``。"""
    code, sep, suffix = lake_symbol.partition("_")
    if not sep or not suffix or not code:
        raise ValueError(f"lake symbol 应形如 000300_SH，收到: {lake_symbol!r}")
    return f"{suffix.upper()}{code}"


def load_calendar(qlib_dir: Path) -> pd.DatetimeIndex:
    cal_path = Path(qlib_dir) / "calendars" / "day.txt"
    frame = pd.read_csv(cal_path, header=None, parse_dates=[0])
    return pd.DatetimeIndex(frame[0])


def clip_index_frame(df: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """湖 parquet → dump_bin 喂料：UTC 毫秒转上海日期、裁到日历内、去重排序。

    必须裁剪：bin 按日历位置索引，日历外的行会被丢弃，提前裁掉便于覆盖率检查。
    """
    if "time" not in df.columns:
        raise ValueError("湖 parquet 缺少 time 列")
    out = df.copy()
    out["date"] = (
        pd.to_datetime(out["time"], unit="ms", utc=True)
        .dt.tz_convert("Asia/Shanghai")
        .dt.normalize()
        .dt.tz_localize(None)
    )
    out = out[(out["date"] >= calendar.min()) & (out["date"] <= calendar.max())]
    out = out.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    return out[["date", *FIELDS]]


def coverage_report(df: pd.DataFrame, calendar: pd.DatetimeIndex) -> dict:
    missing = len(set(calendar) - set(df["date"]))
    return {
        "rows": len(df),
        "calendar_days": len(calendar),
        "calendar_missing": missing,
        "nan_close": int(df["close"].isna().sum()),
    }


def move_indices_out_of_all_txt(qlib_dir: Path, codes: list[str]) -> list[str]:
    """把指数行从 all.txt 挪到 index.txt（幂等），返回本次挪走的行。

    all.txt 是 ``market="all"`` 的宇宙来源，指数绝不能留在里面（见模块 docstring 坑 2）。
    """
    all_path = Path(qlib_dir) / "instruments" / "all.txt"
    index_path = Path(qlib_dir) / "instruments" / "index.txt"
    want = {c.upper() for c in codes}

    lines = [ln for ln in all_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    keep, moved = [], []
    for line in lines:
        symbol = line.split("\t", 1)[0].strip().upper()
        (moved if symbol in want else keep).append(line)
    if not moved:
        return []

    merged: list[str] = []
    if index_path.exists():
        merged = [ln for ln in index_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    # moved 行来自本次 dump，区间必然新于 index.txt 旧登记（旧登记可能是上次裁剪的陈旧区间），
    # 同名以新行覆盖，否则 index.txt 的登记范围永远停在首次写入的日期。
    by_symbol: dict[str, str] = {
        ln.split("\t", 1)[0].strip().upper(): ln
        for ln in merged
    }
    for ln in moved:
        by_symbol[ln.split("\t", 1)[0].strip().upper()] = ln
    merged = list(by_symbol.values())

    index_path.write_text("\n".join(merged) + "\n", encoding="utf-8", newline="\n")
    all_path.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8", newline="\n")
    return moved


def upsert_index_txt_dates(
    qlib_dir: Path,
    codes: list[str],
    start: pd.Timestamp | str,
    end: pd.Timestamp | str,
) -> list[str]:
    """把 index.txt 里指定指数的起止日写成日历区间。

    DumpDataFix 不更新 all.txt 里已有标的的登记日期；dump_all 若把指数按 staging
    旧尾巴写进 all.txt，挪到 index.txt 后区间会停在旧末日。
    """
    index_path = Path(qlib_dir) / "instruments" / "index.txt"
    start_s = pd.Timestamp(start).strftime("%Y-%m-%d")
    end_s = pd.Timestamp(end).strftime("%Y-%m-%d")
    by_symbol: dict[str, str] = {}
    if index_path.exists():
        for ln in index_path.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                by_symbol[ln.split("\t", 1)[0].strip().upper()] = ln
    updated: list[str] = []
    for code in codes:
        key = code.upper()
        new_ln = f"{key}\t{start_s}\t{end_s}"
        if by_symbol.get(key) != new_ln:
            updated.append(key)
        by_symbol[key] = new_ln
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text("\n".join(by_symbol.values()) + "\n", encoding="utf-8", newline="\n")
    return updated


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="湖指数日线 → qlib bin 增量补丁")
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS, help="湖分区名，逗号分隔，如 000300_SH,000001_SH")
    parser.add_argument(
        "--lake-root",
        default="",
        help="湖指数树根；缺省 {OSKH_SOURCE_PARQUET_ROOT}/index/period=1d/dividend_type=none",
    )
    parser.add_argument("--qlib-dir", default=str(DEFAULT_QLIB_DIR), help="qlib 数据目录")
    parser.add_argument("--no-backup", action="store_true", help="跳过备份（首次运行不要用）")
    parser.add_argument("--skip-verify", action="store_true", help="跳过末尾的 qlib 读回验证")
    parser.add_argument("--force", action="store_true", help="覆盖率有缺口时仍继续（默认中止）")
    return parser


def run_patch(args: argparse.Namespace) -> int:
    qlib_dir = Path(args.qlib_dir).expanduser()
    lake_root = Path(args.lake_root).expanduser() if args.lake_root else resolve_index_1d_none()
    calendar = load_calendar(qlib_dir)
    print(f"[1/5] 日历: {calendar.min().date()} .. {calendar.max().date()} ({len(calendar)} 天)")

    if not args.no_backup:
        backup = qlib_dir.parent / f"{qlib_dir.name}_backup_{date.today():%Y%m%d}_pre_index"
        if backup.exists():
            print(f"[1/5] 备份已存在，跳过: {backup}")
        else:
            print(f"[1/5] 备份中（~654MB 小文件较慢，约 2 分钟）: {backup}")
            shutil.copytree(qlib_dir, backup)

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    codes: list[str] = []
    staging = Path(tempfile.mkdtemp(prefix="qlib_index_dump_"))
    for symbol in symbols:
        source = lake_root / f"symbol={symbol}" / "data.parquet"
        clipped = clip_index_frame(pd.read_parquet(source), calendar)
        stats = coverage_report(clipped, calendar)
        code = lake_to_qlib_code(symbol)
        print(
            f"[2/5] {symbol} -> {code}: rows={stats['rows']}/{stats['calendar_days']}, "
            f"缺日={stats['calendar_missing']}, nan_close={stats['nan_close']}, "
            f"首收={clipped['close'].iloc[0]:.2f}, 末收={clipped['close'].iloc[-1]:.2f}"
        )
        if stats["nan_close"] > 0 or (stats["calendar_missing"] > 0 and not args.force):
            raise SystemExit(f"中止：{symbol} 覆盖率异常（nan_close={stats['nan_close']}, 缺日={stats['calendar_missing']}）。确认后可 --force")
        clipped.to_parquet(staging / f"{code.lower()}.parquet", index=False)
        codes.append(code)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from dump_bin import DumpDataFix  # 延迟导入：单测不需要它

    print(f"[3/5] dump_fix 增量写入 {qlib_dir} ...")
    DumpDataFix(data_path=str(staging), qlib_dir=str(qlib_dir), file_suffix=".parquet")()

    moved = move_indices_out_of_all_txt(qlib_dir, codes)
    print(f"[4/5] all.txt -> index.txt 挪移 {len(moved)} 行: {[ln.split(chr(9))[0] for ln in moved] or '(已在 index.txt)'}")
    dated = upsert_index_txt_dates(qlib_dir, codes, calendar.min(), calendar.max())
    print(
        f"[4/5] index.txt 区间 -> {calendar.min().date()} .. {calendar.max().date()}"
        + (f"（更新 {dated}）" if dated else "（已对齐）")
    )

    if args.skip_verify:
        print("[5/5] 跳过验证")
        return 0
    import qlib
    from qlib.data import D

    qlib.init(provider_uri=str(qlib_dir), region="cn")
    ok = True
    for code in codes:
        feat = D.features([code], ["$close"], start_time=str(calendar.min().date()), end_time=str(calendar.max().date()))
        closes = feat["$close"]
        print(f"[5/5] {code}: rows={len(closes)}, nan={int(closes.isna().sum())}, first={closes.iloc[0]:.2f}, last={closes.iloc[-1]:.2f}")
        ok = ok and len(closes) > 0 and not closes.isna().any()
    universe = D.list_instruments(D.instruments(market="all"), start_time=str(calendar.min().date()), end_time=str(calendar.max().date()))
    leak = sorted(set(universe) & set(codes))
    print(f"[5/5] market=all 宇宙 {len(universe)} 只，指数泄漏: {leak or '无'}")
    if leak:
        raise SystemExit("中止：指数泄漏进 market=all 宇宙，检查 all.txt")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    return run_patch(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
