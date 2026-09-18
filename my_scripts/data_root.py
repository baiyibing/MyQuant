# -*- coding: utf-8 -*-
"""Parquet lake roots — same product key as OSkhQuant1.3.

1.3 three-store SSOT (``docs/operations/data-three-stores-ssot.md``):

- **Parquet lake** = ``OSKH_SOURCE_PARQUET_ROOT`` (hive container).
  Sub-trees are derived: ``stock/period=*``, ``index/period=*``, ``etf/period=1d``.
- **DuckDB workspace** = ``{OSKH_DATA_ROOT}/stock_data`` — 1.3 only. This repo
  must **not** treat ``OSKH_DATA_ROOT`` as the hive (CI sets it to ``D:\\oskh_ci_data``).
- **SQLite** — 1.3 trading DBs; unused here.

Unset container / CSV env raises. Do not guess ``E:`` / ``F:``.
Fine-grained overrides (``OSKH_PERIOD_1M_ROOT``, ``OSKH_INDEX_1M_ROOT``, …) win
when set, matching 1.3. Index resolvers never read stock ``OSKH_PERIOD_*``.
"""

from __future__ import annotations

import os
from pathlib import Path

SOURCE_PARQUET_ENV = "OSKH_SOURCE_PARQUET_ROOT"
QLIB_CSV_ENV = "OSKH_QLIB_CSV_DIR"
INDEX_DAILY_ENV = "OSKH_INDEX_DAILY_ROOT"
INDEX_MINUTE_ENV = "OSKH_INDEX_1M_ROOT"
ETF_DAILY_ENV = "OSKH_ETF_DAILY_ROOT"


class DataRootError(RuntimeError):
    """Required data-path env or argument is missing."""


def _env_path(name: str) -> Path | None:
    raw = str(os.environ.get(name) or "").strip()
    return Path(raw) if raw else None


def resolve_parquet_container(*, explicit_root: str | Path | None = None) -> Path:
    """Hive container (adj/ST/cyq + stock|index|etf trees). Never uses OSKH_DATA_ROOT."""
    if explicit_root:
        return Path(explicit_root)
    env = _env_path(SOURCE_PARQUET_ENV)
    if env is not None:
        return env
    raise DataRootError(
        f"未设置 {SOURCE_PARQUET_ENV}。不要猜测 E:/F: 盘符；"
        f"setx {SOURCE_PARQUET_ENV} <湖容器> 或传显式路径。"
    )


def resolve_qlib_csv_dir(*, explicit_root: str | Path | None = None) -> Path:
    """Vendor CSV batch for refresh/merge. Never defaults to F:/qlibdata."""
    if explicit_root:
        return Path(explicit_root)
    env = _env_path(QLIB_CSV_ENV)
    if env is not None:
        return env
    raise DataRootError(
        f"未设置 {QLIB_CSV_ENV} / --csv-dir。不要猜测 F:/qlibdata；把本批 CSV 目录传进来。"
    )


def resolve_period_root(
    period: str,
    *,
    explicit_root: str | Path | None = None,
) -> Path:
    """A-share tree: ``{container}/stock/period={period}`` (legacy ``{container}/period=*``)."""
    if explicit_root:
        return Path(explicit_root)
    env = _env_path(f"OSKH_PERIOD_{period.upper()}_ROOT")
    if env is not None:
        return env
    container = resolve_parquet_container()
    stock_root = container / "stock" / f"period={period}"
    legacy = container / f"period={period}"
    if not stock_root.exists() and legacy.exists():
        return legacy
    return stock_root


def resolve_index_daily_root(*, explicit_root: str | Path | None = None) -> Path:
    if explicit_root:
        return Path(explicit_root)
    env = _env_path(INDEX_DAILY_ENV)
    if env is not None:
        return env
    return resolve_parquet_container() / "index" / "period=1d"


def resolve_index_minute_root(*, explicit_root: str | Path | None = None) -> Path:
    """Never reads ``OSKH_PERIOD_1M_ROOT`` (1.3 contract)."""
    if explicit_root:
        return Path(explicit_root)
    env = _env_path(INDEX_MINUTE_ENV)
    if env is not None:
        return env
    return resolve_parquet_container() / "index" / "period=1m"


def resolve_etf_daily_root(*, explicit_root: str | Path | None = None) -> Path:
    if explicit_root:
        return Path(explicit_root)
    env = _env_path(ETF_DAILY_ENV)
    if env is not None:
        return env
    return resolve_parquet_container() / "etf" / "period=1d"


def hive_none(period_root: Path) -> Path:
    return Path(period_root) / "dividend_type=none"


def resolve_stock_1min_none() -> Path:
    return hive_none(resolve_period_root("1m"))


def resolve_index_1min_none() -> Path:
    return hive_none(resolve_index_minute_root())


def resolve_index_1d_none() -> Path:
    return hive_none(resolve_index_daily_root())


def resolve_etf_1d_none() -> Path:
    return hive_none(resolve_etf_daily_root())


def resolve_source_parquet(name: str) -> Path:
    return resolve_parquet_container() / name


def resolve_st_daily() -> Path:
    return resolve_parquet_container() / "vendor_wind_st_status" / "st_daily.parquet"


def resolve_sw_l1_root() -> Path:
    """1.3 writes this tree; this repo only consumes it."""
    return resolve_source_parquet("vendor_wind_sw_l1")


def resolve_sw_l1_map(*, explicit_root: str | Path | None = None) -> Path:
    """SW L1 consume file. Prefer ``sw_l1_map.csv``, else ``wind_l1_map.csv``.

    Unset ``OSKH_SOURCE_PARQUET_ROOT`` or a missing file raises. Do not fall
    back to ``exports/m3d_industry``.
    """
    if explicit_root:
        return Path(explicit_root)
    root = resolve_sw_l1_root()
    preferred = root / "sw_l1_map.csv"
    wind = root / "wind_l1_map.csv"
    if preferred.is_file():
        return preferred
    if wind.is_file():
        return wind
    raise DataRootError(
        f"未找到行业映射 {preferred} 或 {wind}。"
        "1.3 写湖：python -m oskh_data.vendor_wind_sw_l1；不要猜测 E:/F: 或仓库 exports。"
    )
