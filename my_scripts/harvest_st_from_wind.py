"""ST 历史 PIT 数据集采集与后处理（Wind × Kimi datasource）。

本脚本不直接调用 MCP；它负责：
- 从代码清单生成 Wind 问题串文件（供 Kimi agent / 本会话 MCP 批量调用）
- 列出尚未落盘的批次（额度恢复后继续采）
- 合并原始 CSV 响应为 parquet
- 派生 ST 区间表与每日 ST 状态矩阵（稀疏：仅 is_st=True）
- 校验与审计

Wind 问题串模板（NLU）：
- 实施："{codes}的ST状态和历史戴帽摘帽时间"
- 撤销："{codes}的撤销风险警示和摘帽日期"

代码格式：000001.SZ、600000.SH、920000.BJ（用中文顿号连接）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
_MY_SCRIPTS = _ROOT / "my_scripts"
if str(_MY_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_MY_SCRIPTS))

DEFAULT_OUTPUT_DIR = Path("F:/stock_data/vendor_wind_st_status")
DEFAULT_QLIB_DIR = Path.home() / ".qlib" / "qlib_data" / "my_data"
DEFAULT_BATCH_SIZE = 100

# 与 QMT 名称任务书同一口径：*ST / ST / S ST / SST / 退市（全角＊ 经 NFKC）
_ST_RISK_NAME_RE = re.compile(r"(?:\*?ST|S\s*ST|SST|退市)", re.IGNORECASE)

_IMPL_Q_SUFFIX = "的ST状态和历史戴帽摘帽时间"
_REVOKE_Q_SUFFIX = "的撤销风险警示和摘帽日期"

_EMPTY_IMPL_COLS = [
    "code",
    "name",
    "st_after_name",
    "st_before_name",
    "stock_kind",
    "st_date",
    "reason",
]
_EMPTY_REVOKE_COLS = [
    "code",
    "name",
    "revoke_date",
    "after_revoke_name",
    "before_revoke_name",
]
_EMPTY_INTERVAL_COLS = [
    "code",
    "name",
    "st_kind",
    "start_date",
    "end_date",
    "reason",
    "end_status",
]


def to_wind_code(qlib_code: str) -> str:
    """SH600000 -> 600000.SH; SZ000001 -> 000001.SZ; BJ920000 -> 920000.BJ."""
    c = qlib_code.strip().upper()
    if c.startswith("SH"):
        return c[2:] + ".SH"
    if c.startswith("SZ"):
        return c[2:] + ".SZ"
    if c.startswith("BJ"):
        return c[2:] + ".BJ"
    return c


def to_qlib_code(wind_code: str) -> str:
    """600000.SH -> SH600000."""
    c = wind_code.strip().upper()
    if c.endswith(".SH"):
        return "SH" + c[:-3]
    if c.endswith(".SZ"):
        return "SZ" + c[:-3]
    if c.endswith(".BJ"):
        return "BJ" + c[:-3]
    return c


def load_all_codes(qlib_dir: Path) -> list[str]:
    """读取 instruments/all.txt，返回 Wind 格式代码列表。"""
    path = Path(qlib_dir) / "instruments" / "all.txt"
    codes = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 1:
            continue
        codes.append(to_wind_code(parts[0]))
    return sorted(set(codes))


def make_batches(codes: list[str], batch_size: int) -> list[list[str]]:
    return [codes[i : i + batch_size] for i in range(0, len(codes), batch_size)]


def generate_question_files(
    codes: list[str],
    out_dir: Path,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[tuple[int, Path, Path]]:
    """生成每批的问题串文件，返回 (batch_idx, implement_question_path, revoke_question_path)。"""
    raw_dir = Path(out_dir) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    batches = make_batches(codes, batch_size)
    result = []
    for i, batch in enumerate(batches):
        joined = "、".join(batch)
        impl_path = raw_dir / f"q_st_implement_{i:04d}.txt"
        revoke_path = raw_dir / f"q_st_revoke_{i:04d}.txt"
        impl_path.write_text(f"{joined}{_IMPL_Q_SUFFIX}", encoding="utf-8")
        revoke_path.write_text(f"{joined}{_REVOKE_Q_SUFFIX}", encoding="utf-8")
        result.append((i, impl_path, revoke_path))
    return result


def parse_codes_from_question(text: str) -> list[str]:
    """从问题串文件还原本批 Wind 代码。"""
    body = text.strip()
    for suffix in (_IMPL_Q_SUFFIX, _REVOKE_Q_SUFFIX):
        if body.endswith(suffix):
            body = body[: -len(suffix)]
            break
    return [c.strip().upper() for c in body.split("、") if c.strip()]


def read_raw_csvs(glob_pattern: str) -> pd.DataFrame:
    """合并符合 glob 的所有原始 CSV，空文件/无列文件跳过。

    接受绝对路径通配（Windows 上 Path().glob(abs) 不会命中）。
    """
    if "*" in glob_pattern:
        parent = Path(glob_pattern).parent
        paths = sorted(parent.glob(Path(glob_pattern).name))
    else:
        paths = [Path(glob_pattern)]
    frames = []
    for p in paths:
        if not p.is_file() or p.stat().st_size == 0:
            continue
        try:
            df = pd.read_csv(p)
        except Exception:
            continue
        if df.empty:
            continue
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _empty_impl() -> pd.DataFrame:
    return pd.DataFrame(columns=_EMPTY_IMPL_COLS)


def _empty_revoke() -> pd.DataFrame:
    return pd.DataFrame(columns=_EMPTY_REVOKE_COLS)


def normalize_implement(df: pd.DataFrame) -> pd.DataFrame:
    """统一实施 ST 原始响应的列名与格式。"""
    if df is None or df.empty:
        return _empty_impl()
    rename = {
        "Wind代码": "code",
        "证券简称": "name",
        "实施ST后简称": "st_after_name",
        "实施ST前简称": "st_before_name",
        "股票种类": "stock_kind",
        "实施ST日期": "st_date",
        "实施ST原因": "reason",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    if "code" not in df.columns or "st_date" not in df.columns:
        return _empty_impl()
    df["code"] = df["code"].astype(str).str.strip().str.upper()
    df["st_date"] = pd.to_datetime(df["st_date"], errors="coerce").dt.date
    df = df.dropna(subset=["code", "st_date"]).copy()
    keep = [c for c in _EMPTY_IMPL_COLS if c in df.columns]
    return df[keep]


def normalize_revoke(df: pd.DataFrame) -> pd.DataFrame:
    """统一撤销 ST 原始响应的列名与格式。"""
    if df is None or df.empty:
        return _empty_revoke()
    rename = {
        "股票编号": "code",
        "证券名称": "name",
        "撤销日期": "revoke_date",
        "撤销ST后简称": "after_revoke_name",
        "撤销ST前简称": "before_revoke_name",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    if "code" not in df.columns or "revoke_date" not in df.columns:
        return _empty_revoke()
    df["code"] = df["code"].astype(str).str.strip().str.upper()
    df["revoke_date"] = pd.to_datetime(df["revoke_date"], errors="coerce").dt.date
    df = df.dropna(subset=["code", "revoke_date"]).copy()
    keep = [c for c in _EMPTY_REVOKE_COLS if c in df.columns]
    return df[keep]


def is_st_risk_name(name: str | None) -> bool:
    """证券简称是否仍带 ST / *ST / SST / 退市（NFKC 后再判）。"""
    if not name or not isinstance(name, str):
        return False
    n = unicodedata.normalize("NFKC", name)
    return bool(_ST_RISK_NAME_RE.search(n))


def infer_st_kind(name: str | None, reason: str | None) -> str:
    """由简称/原因推断 ST 类别。"""
    n = unicodedata.normalize("NFKC", name or "")
    r = unicodedata.normalize("NFKC", reason or "")
    n_up = n.upper()
    if "退市" in n or "退市" in r:
        return "delist"
    if n_up.startswith("*ST") or "*ST" in n_up:
        return "star_st"
    if n_up.startswith("ST") or "ST" in n_up:
        return "st"
    return "other"


def _annotate_end_status(rows: list[dict], latest_name: pd.Series) -> list[dict]:
    for row in rows:
        if row.get("end_date") is not None and pd.notna(row["end_date"]):
            row["end_status"] = "revoked"
            continue
        name = latest_name.get(row["code"]) if len(latest_name) else None
        if name is None:
            name = row.get("name")
        row["end_status"] = "open" if is_st_risk_name(name) else "unknown_end"
    return rows


def build_intervals(impl: pd.DataFrame, revoke: pd.DataFrame) -> pd.DataFrame:
    """由实施/撤销记录生成 ST 区间表。

    有撤销：每条实施匹配其后最近一次撤销（未匹配则按当前简称推断 open / unknown_end）。
    无撤销：每只股票塌缩为一段，start=最早实施日；当前简称仍是 ST 风险 → open，
    否则 unknown_end（禁止把已摘帽股展开到日历末日）。
    """
    if impl.empty:
        return pd.DataFrame(columns=_EMPTY_INTERVAL_COLS)

    impl = impl.sort_values(["code", "st_date"]).copy()
    latest_name = impl.groupby("code")["name"].last()
    has_revoke = (
        revoke is not None
        and not revoke.empty
        and "code" in revoke.columns
        and "revoke_date" in revoke.columns
    )

    rows: list[dict] = []
    if not has_revoke:
        for code, sub in impl.groupby("code"):
            first = sub.iloc[0]
            last = sub.iloc[-1]
            rows.append(
                {
                    "code": code,
                    "name": last["name"],
                    "st_kind": infer_st_kind(last.get("st_after_name"), last.get("reason")),
                    "start_date": first["st_date"],
                    "end_date": None,
                    "reason": last.get("reason"),
                    "end_status": "open" if is_st_risk_name(last["name"]) else "unknown_end",
                }
            )
        return pd.DataFrame(rows)

    revoke = revoke.sort_values(["code", "revoke_date"]).copy()
    for code, sub in impl.groupby("code"):
        revokes = revoke[revoke["code"] == code].sort_values("revoke_date").to_dict("records")
        rev_idx = 0
        for _, row in sub.iterrows():
            start = row["st_date"]
            end = None
            while rev_idx < len(revokes) and revokes[rev_idx]["revoke_date"] <= start:
                rev_idx += 1
            if rev_idx < len(revokes):
                end = revokes[rev_idx]["revoke_date"]
                rev_idx += 1
            rows.append(
                {
                    "code": code,
                    "name": row["name"],
                    "st_kind": infer_st_kind(row.get("st_after_name"), row.get("reason")),
                    "start_date": start,
                    "end_date": end,
                    "reason": row.get("reason"),
                }
            )
    _annotate_end_status(rows, latest_name)
    return pd.DataFrame(rows)


def build_daily_matrix(
    intervals: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    all_codes: list[str] | None = None,
    dense: bool = False,
) -> pd.DataFrame:
    """由区间表展开为每日 ST 状态。

    默认稀疏（仅 is_st=True）。unknown_end 不展开——缺撤销日时宁可漏历史帽期，
    也不把已摘帽股标成一直 ST。dense=True 时才做 交易日×全市场 补 False（完整采集后用）。
    """
    empty = pd.DataFrame(columns=["trade_date", "code", "is_st", "st_kind", "name"])
    if intervals.empty or calendar is None or len(calendar) == 0:
        return empty

    usable = intervals
    if "end_status" in intervals.columns:
        usable = intervals[intervals["end_status"] != "unknown_end"]
    if usable.empty:
        return empty

    cal = pd.DatetimeIndex(calendar)
    parts = []
    for _, row in usable.iterrows():
        start = pd.Timestamp(row["start_date"])
        if pd.notna(row.get("end_date")):
            end = pd.Timestamp(row["end_date"])
        else:
            end = cal[-1]
        days = cal[(cal >= start) & (cal <= end)]
        if len(days) == 0:
            continue
        parts.append(
            pd.DataFrame(
                {
                    "trade_date": days,
                    "code": row["code"],
                    "is_st": True,
                    "st_kind": row["st_kind"],
                    "name": row["name"],
                }
            )
        )
    if not parts:
        return empty
    df = pd.concat(parts, ignore_index=True)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["code"] = df["code"].astype(str).str.upper()
    df = df.drop_duplicates(subset=["trade_date", "code"], keep="last")

    if dense and all_codes:
        dates = pd.DataFrame({"trade_date": cal})
        codes = pd.DataFrame({"code": sorted(set(all_codes))})
        base = dates.merge(codes, how="cross")
        base["trade_date"] = pd.to_datetime(base["trade_date"])
        base["code"] = base["code"].astype(str).str.upper()
        merged = base.merge(df, on=["trade_date", "code"], how="left")
        merged["is_st"] = merged["is_st"].fillna(False)
        merged["st_kind"] = merged["st_kind"].where(merged["is_st"], None)
        df = merged

    return df.sort_values(["trade_date", "code"]).reset_index(drop=True)


def _batch_ids_from_paths(paths: list[Path], prefix: str) -> list[str]:
    ids = []
    pat = re.compile(rf"{re.escape(prefix)}(\d{{4}})\.csv$")
    for p in paths:
        m = pat.search(p.name)
        if m:
            ids.append(m.group(1))
    return sorted(ids)


def collect_harvest_status(output_dir: Path, batch_size: int = DEFAULT_BATCH_SIZE) -> dict[str, Any]:
    """扫描 raw/ 下问题串与 CSV，给出缺批清单（供额度恢复后续采）。"""
    raw_dir = Path(output_dir) / "raw"
    q_impl = sorted(raw_dir.glob("q_st_implement_*.txt")) if raw_dir.is_dir() else []
    n_batches = len(q_impl)
    expected = [f"{i:04d}" for i in range(n_batches)]

    impl_csvs = sorted(raw_dir.glob("st_implement_batch_*.csv")) if raw_dir.is_dir() else []
    revoke_csvs = sorted(raw_dir.glob("st_revoke_batch_*.csv")) if raw_dir.is_dir() else []
    have_impl = _batch_ids_from_paths(impl_csvs, "st_implement_batch_")
    have_revoke = _batch_ids_from_paths(revoke_csvs, "st_revoke_batch_")
    missing_impl = [b for b in expected if b not in have_impl]
    missing_revoke = [b for b in expected if b not in have_revoke]

    harvested_codes: list[str] = []
    for bid in have_impl:
        qp = raw_dir / f"q_st_implement_{bid}.txt"
        if qp.is_file():
            harvested_codes.extend(parse_codes_from_question(qp.read_text(encoding="utf-8")))

    return {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "output_dir": str(Path(output_dir)),
        "batch_size": batch_size,
        "n_batches": n_batches,
        "implement": {
            "have": have_impl,
            "missing": missing_impl,
            "n_have": len(have_impl),
            "n_missing": len(missing_impl),
        },
        "revoke": {
            "have": have_revoke,
            "missing": missing_revoke,
            "n_have": len(have_revoke),
            "n_missing": len(missing_revoke),
        },
        "harvested_wind_codes": sorted(set(harvested_codes)),
        "n_harvested_codes": len(set(harvested_codes)),
        "partial": bool(missing_impl or missing_revoke),
        "do_not_download": True,
        "next_when_quota_recovers": {
            "retry_implement_batches": missing_impl,
            "harvest_revoke_batches": missing_revoke,
            "note": (
                "0027/0028 曾返回「没找到数据」（多为 301xxx，可能确无实施记录）；"
                "额度恢复后先重试这两批，再补 0035+ 实施，然后从 0000 采撤销。"
            ),
        },
    }


def coverage_fallback_qlib(coverage: dict, static_codes: set[str] | None = None) -> set[str]:
    """静态名单里需要 fallback 的代码：未采到的 + 有实施但不知摘帽日的。"""
    static = {c.upper() for c in (static_codes or set())}
    if not coverage:
        return static
    harvested = {to_qlib_code(c) for c in coverage.get("harvested_wind_codes", [])}
    unknown = {to_qlib_code(c) for c in coverage.get("unknown_end_wind_codes", [])}
    if not harvested and not unknown:
        return static
    return (static - harvested) | (static & unknown)


def load_st_daily_index(
    daily_path: str | Path,
    coverage_path: str | Path | None = None,
    fallback_static: set[str] | None = None,
) -> tuple[dict[date, set[str]], set[str]]:
    """st_daily.parquet → {date: {QLib代码}}，以及 fallback 集合。"""
    p = Path(daily_path)
    df = pd.read_parquet(p)
    by_date: dict[date, set[str]] = {}
    if not df.empty and "is_st" in df.columns:
        hit = df[df["is_st"] == True].copy()  # noqa: E712
        hit["trade_date"] = pd.to_datetime(hit["trade_date"])
        hit["qlib"] = hit["code"].map(to_qlib_code)
        for d, sub in hit.groupby(hit["trade_date"].dt.date):
            by_date[d] = set(sub["qlib"].astype(str).str.upper())
    cov_path = Path(coverage_path) if coverage_path else p.parent / "st_coverage.json"
    coverage = {}
    if cov_path.is_file():
        coverage = json.loads(cov_path.read_text(encoding="utf-8"))
    fallback = coverage_fallback_qlib(coverage, fallback_static)
    return by_date, fallback


def load_st_codes_asof(
    daily_path: str | Path,
    asof=None,
    coverage_path: str | Path | None = None,
    fallback_static: set[str] | None = None,
) -> set[str]:
    """取 as-of 日（默认矩阵最后一天）的 QLib ST 集合，并并上 fallback。"""
    from bisect import bisect_right

    by_date, fallback = load_st_daily_index(daily_path, coverage_path, fallback_static)
    if not by_date:
        return set(fallback)
    dates = sorted(by_date)
    if asof is None:
        chosen = dates[-1]
    else:
        target = pd.Timestamp(asof).date()
        idx = bisect_right(dates, target) - 1
        if idx < 0:
            return set(fallback)
        chosen = dates[idx]
    return set(by_date[chosen]) | set(fallback)


def write_harvest_status(output_dir: Path, extra: dict[str, Any] | None = None) -> Path:
    status = collect_harvest_status(output_dir)
    if extra:
        status.update(extra)
    path = Path(output_dir) / "harvest_status.json"
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _to_parquet(df: pd.DataFrame, path: Path) -> None:
    """写出 parquet：日期列统一 datetime64，避免 Python date 把 Arrow 打崩。"""
    out = df.copy()
    for col in out.columns:
        if "date" in col:
            out[col] = pd.to_datetime(out[col], errors="coerce")
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path, index=False)


def merge_raw_to_parquet(
    output_dir: Path,
    pulled_at: str | None = None,
    calendar: pd.DatetimeIndex | None = None,
    all_codes: list[str] | None = None,
    dense: bool = False,
    skip_daily: bool = False,
) -> dict[str, Any]:
    """读取 raw 目录下全部 CSV，合并为 parquet，并派生区间表/每日矩阵。"""
    output_dir = Path(output_dir)
    raw_dir = output_dir / "raw"
    pulled_at = pulled_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    impl = normalize_implement(read_raw_csvs(str(raw_dir / "st_implement_batch_*.csv")))
    revoke = normalize_revoke(read_raw_csvs(str(raw_dir / "st_revoke_batch_*.csv")))

    impl["pulled_at_utc"] = pulled_at
    impl["source"] = "wind:kimi-datasource"
    revoke["pulled_at_utc"] = pulled_at
    revoke["source"] = "wind:kimi-datasource"

    impl_path = output_dir / "st_implement.parquet"
    revoke_path = output_dir / "st_revoke.parquet"
    _to_parquet(impl, impl_path)
    _to_parquet(revoke, revoke_path)

    intervals = build_intervals(impl, revoke)
    intervals_path = output_dir / "st_intervals.parquet"
    _to_parquet(intervals, intervals_path)

    if calendar is None:
        cal_path = DEFAULT_QLIB_DIR / "calendars" / "day.txt"
        if cal_path.is_file():
            cal = pd.read_csv(cal_path, header=None, parse_dates=[0])[0]
            calendar = pd.DatetimeIndex(cal)
        else:
            calendar = pd.DatetimeIndex([])

    if all_codes is None and dense:
        all_txt = DEFAULT_QLIB_DIR / "instruments" / "all.txt"
        if all_txt.is_file():
            all_codes = load_all_codes(DEFAULT_QLIB_DIR)

    daily_path = output_dir / "st_daily.parquet"
    if skip_daily:
        daily = pd.DataFrame(columns=["trade_date", "code", "is_st", "st_kind", "name"])
        _to_parquet(daily, daily_path)
    else:
        daily = build_daily_matrix(intervals, calendar, all_codes if dense else None, dense=dense)
        _to_parquet(daily, daily_path)

    status = collect_harvest_status(output_dir)
    unknown = []
    open_st = []
    if not intervals.empty and "end_status" in intervals.columns:
        unknown = sorted(intervals.loc[intervals["end_status"] == "unknown_end", "code"].astype(str).unique())
        open_st = sorted(intervals.loc[intervals["end_status"] == "open", "code"].astype(str).unique())
    coverage = {
        "harvested_wind_codes": status["harvested_wind_codes"],
        "unknown_end_wind_codes": unknown,
        "open_st_wind_codes": open_st,
        "n_implement_rows": int(len(impl)),
        "n_revoke_rows": int(len(revoke)),
        "n_interval_rows": int(len(intervals)),
        "n_daily_rows": int(len(daily)),
        "daily_sparse": not dense,
        "partial": status["partial"],
        "updated_at": pulled_at,
    }
    coverage_path = output_dir / "st_coverage.json"
    coverage_path.write_text(json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8")
    write_harvest_status(output_dir, extra={"coverage": coverage})

    return {
        "implement": impl_path,
        "revoke": revoke_path,
        "intervals": intervals_path,
        "daily": daily_path,
        "coverage": coverage_path,
        "status": output_dir / "harvest_status.json",
        "impl_rows": len(impl),
        "revoke_rows": len(revoke),
        "interval_rows": len(intervals),
        "daily_rows": len(daily),
        "open_st": len(open_st),
        "unknown_end": len(unknown),
        "partial": status["partial"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="ST 历史数据集 Wind 采集与后处理")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate-questions", help="从代码清单生成 Wind 问题串文件")
    gen.add_argument("--qlib-dir", default=str(DEFAULT_QLIB_DIR))
    gen.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    gen.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    gen.add_argument(
        "--static-blacklist",
        action="store_true",
        help="仅使用 train_wiring.EXCLUDE_STOCKS_DEFAULT 生成问题串（小批量验证）",
    )

    merge = sub.add_parser("merge", help="合并 raw CSV 为 parquet 并派生区间/每日矩阵")
    merge.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    merge.add_argument(
        "--dense",
        action="store_true",
        help="写出 交易日×全市场 稠密矩阵（完整采集后才有意义；默认稀疏仅 is_st=True）",
    )
    merge.add_argument(
        "--skip-daily",
        action="store_true",
        help="只写 implement/revoke/intervals/coverage，不展开每日矩阵",
    )

    status = sub.add_parser("status", help="只扫描 raw/，写出 harvest_status.json，不下载")
    status.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))

    args = parser.parse_args()

    if args.command == "generate-questions":
        if args.static_blacklist:
            from train_wiring import EXCLUDE_STOCKS_DEFAULT  # noqa: WPS433

            codes = [to_wind_code(c) for c in EXCLUDE_STOCKS_DEFAULT]
        else:
            codes = load_all_codes(Path(args.qlib_dir))
        result = generate_question_files(codes, Path(args.output_dir), args.batch_size)
        print(
            f"[st-wind] 生成 {len(result)} 批问题串，"
            f"目录：{Path(args.output_dir) / 'raw'}"
        )
        return 0

    if args.command == "status":
        path = write_harvest_status(Path(args.output_dir))
        data = json.loads(path.read_text(encoding="utf-8"))
        print(
            f"[st-wind] 实施 {data['implement']['n_have']}/{data['n_batches']}，"
            f"缺 {data['implement']['missing'][:8]}"
            f"{'…' if len(data['implement']['missing']) > 8 else ''}\n"
            f"  撤销 {data['revoke']['n_have']}/{data['n_batches']}，"
            f"缺全部={data['revoke']['n_missing'] == data['n_batches']}\n"
            f"  → {path}"
        )
        return 0

    if args.command == "merge":
        stats = merge_raw_to_parquet(
            Path(args.output_dir), dense=args.dense, skip_daily=args.skip_daily
        )
        print(
            f"[st-wind] 合并完成（partial={stats['partial']}）：\n"
            f"  implement: {stats['impl_rows']} 行 -> {stats['implement']}\n"
            f"  revoke:    {stats['revoke_rows']} 行 -> {stats['revoke']}\n"
            f"  intervals: {stats['interval_rows']} 行 "
            f"(open={stats['open_st']}, unknown_end={stats['unknown_end']}) "
            f"-> {stats['intervals']}\n"
            f"  daily:     {stats['daily_rows']} 行(稀疏) -> {stats['daily']}"
        )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
