"""Research-side configuration over infra storage; no IO implementation copies."""
import os
from pathlib import Path

from myquant_infra.derived_data.turnover_resistance import store as shared
from myquant_factors import _runtime
from myquant_factors.chip.bands import compute_tr_bb_columns

DEFAULT_WINDOW = shared.DEFAULT_WINDOW
DEFAULT_FREE_FLOAT_POLICY = shared.DEFAULT_FREE_FLOAT_POLICY


def resolve_parquet_path(path=None):
    if "store_path" in _runtime._ports:
        return _runtime._ports["store_path"](path)
    return Path(path or os.environ.get("TURNOVER_RESIST_BANDS_PATH") or
                _runtime.resolve_source_parquet("turnover_resistance_daily.parquet"))


def resolve_year_staging_path(year, staging_dir=None):
    if "year_path" in _runtime._ports:
        return _runtime._ports["year_path"](year, staging_dir)
    configured = staging_dir or os.environ.get("TURNOVER_RESIST_STAGING_DIR")
    if configured is None:
        configured = _runtime.resolve_parquet_container() / "tr_staging"
    return shared.resolve_year_staging_path(year, Path(configured))


def merge_parquet_into_canonical(*sources, canonical_path=None):
    if "store_merge" in _runtime._ports:
        return _runtime._ports["store_merge"](*sources, canonical_path=canonical_path)
    return shared.merge_parquet_into_canonical(*sources, canonical_path=resolve_parquet_path(canonical_path))


def TurnoverResistanceStore(path=None, *, bands_producer=None):
    if "store_factory" in _runtime._ports:
        return _runtime._ports["store_factory"](path, bands_producer=bands_producer)
    return shared.TurnoverResistanceStore(resolve_parquet_path(path),
        bands_producer=compute_tr_bb_columns if bands_producer is None else bands_producer)
