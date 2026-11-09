# -*- coding: utf-8 -*-
"""Stock table path resolution (RFC-003 §4.3 · M-003b)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from myquant_factors._runtime import resolve_data_root


def resolve_stock_data_root(*, explicit_root: Optional[str] = None) -> Path:
    return resolve_data_root(explicit_root=explicit_root)


def stock_data_path(filename: str, *, explicit_root: Optional[str] = None) -> Path:
    """散装 parquet 单源（plan-data-path-ssot D1）：默认经 resolve_source_parquet
    （honors OSKH_SOURCE_PARQUET_ROOT）；``explicit_root`` 保持 repo 根语义
    （root/stock_data/filename，测试/工具用）。"""
    if explicit_root:
        return resolve_stock_data_root(explicit_root=explicit_root) / "stock_data" / filename
    from myquant_factors._runtime import resolve_source_parquet

    return resolve_source_parquet(filename)
