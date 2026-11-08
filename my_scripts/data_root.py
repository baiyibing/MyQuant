"""MyQuant environment configuration for infra's explicit lake-path API."""
from __future__ import annotations

import os
from pathlib import Path

from myquant_infra.lake import paths

SOURCE_PARQUET_ENV = "OSKH_SOURCE_PARQUET_ROOT"
QLIB_CSV_ENV = "OSKH_QLIB_CSV_DIR"
INDEX_DAILY_ENV = "OSKH_INDEX_DAILY_ROOT"
INDEX_MINUTE_ENV = "OSKH_INDEX_1M_ROOT"
ETF_DAILY_ENV = "OSKH_ETF_DAILY_ROOT"


class DataRootError(RuntimeError):
    """Required host configuration or consume file is missing."""


def _env_path(name: str) -> Path | None:
    raw = str(os.environ.get(name) or "").strip()
    return Path(raw) if raw else None


def _configured(name: str, explicit_root: str | Path | None) -> Path:
    value = explicit_root or _env_path(name)
    if value is None:
        raise DataRootError(f"未设置 {name}；请配置环境变量或传显式路径。")
    return Path(value)


def resolve_parquet_container(*, explicit_root: str | Path | None = None) -> Path:
    return paths.parquet_container(_configured(SOURCE_PARQUET_ENV, explicit_root))


def resolve_qlib_csv_dir(*, explicit_root: str | Path | None = None) -> Path:
    return paths.qlib_csv_dir(_configured(QLIB_CSV_ENV, explicit_root))


def resolve_period_root(period: str, *, explicit_root: str | Path | None = None) -> Path:
    override = explicit_root or _env_path(f"OSKH_PERIOD_{period.upper()}_ROOT")
    return paths.stock_period_root(
        None if override else resolve_parquet_container(), period, explicit_root=override,
    )


def resolve_index_daily_root(*, explicit_root: str | Path | None = None) -> Path:
    override = explicit_root or _env_path(INDEX_DAILY_ENV)
    return paths.index_daily_root(
        None if override else resolve_parquet_container(), explicit_root=override,
    )


def resolve_index_minute_root(*, explicit_root: str | Path | None = None) -> Path:
    override = explicit_root or _env_path(INDEX_MINUTE_ENV)
    return paths.index_minute_root(
        None if override else resolve_parquet_container(), explicit_root=override,
    )


def resolve_etf_daily_root(*, explicit_root: str | Path | None = None) -> Path:
    override = explicit_root or _env_path(ETF_DAILY_ENV)
    return paths.etf_daily_root(
        None if override else resolve_parquet_container(), explicit_root=override,
    )


def resolve_stock_1min_none() -> Path:
    return paths.stock_minute_none(explicit_root=resolve_period_root("1m"))


def resolve_index_1min_none() -> Path:
    return paths.index_minute_none(explicit_root=resolve_index_minute_root())


def resolve_index_1d_none() -> Path:
    return paths.index_daily_none(explicit_root=resolve_index_daily_root())


def resolve_etf_1d_none() -> Path:
    return paths.etf_daily_none(explicit_root=resolve_etf_daily_root())


def resolve_source_parquet(name: str) -> Path:
    return paths.source_parquet(resolve_parquet_container(), name)


def _consume(resolver, *, what: str, **kwargs) -> Path:
    try:
        return resolver(**kwargs)
    except paths.MissingLakeFileError as exc:
        raise DataRootError(f"未找到{what}：{exc}") from exc


def resolve_st_daily(*, must_exist: bool = True) -> Path:
    return _consume(
        paths.st_daily_path, what="ST 日表",
        container=resolve_parquet_container(), must_exist=must_exist,
    )


def resolve_cyq_winner_ratio(*, must_exist: bool = False) -> Path:
    return _consume(
        paths.cyq_winner_ratio_path, what="CYQ 盈筹率",
        container=resolve_parquet_container(), must_exist=must_exist,
    )


def resolve_qmt_winner_chips(*, must_exist: bool = True) -> Path:
    return _consume(
        paths.qmt_winner_chips_path, what="QMT 盈筹真值",
        container=resolve_parquet_container(), must_exist=must_exist,
    )


def resolve_sw_l1_root() -> Path:
    return paths.sw_l1_root(resolve_parquet_container())


def resolve_sw_l1_map(*, explicit_root: str | Path | None = None) -> Path:
    return _consume(
        paths.sw_l1_map_path, what="行业映射",
        container=None if explicit_root else resolve_parquet_container(),
        explicit_file=explicit_root,
    )
