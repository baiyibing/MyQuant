"""Caller data/configuration ports. The factor library never imports a host repo."""
from __future__ import annotations

import logging
import os
from pathlib import Path

_ports: dict = {}


def configure_host(**ports) -> None:
    """Bind explicit data/clock/log ports for one consumer process."""
    allowed = {"source_parquet", "data_root", "tr_root", "previous_trading_day", "logger",
               "reader_factory", "research_root", "period_root", "pool_entries", "trade_days", "clock",
               "parquet_root", "python", "store_factory", "store_path", "year_path", "store_merge"}
    if set(ports) - allowed or not all(callable(value) for value in ports.values()):
        raise ValueError("factor host ports must be known callable providers")
    _ports.update(ports)


class _ContextLog(logging.LoggerAdapter):
    def process(self, message, kwargs):
        context = kwargs.pop("context", None)
        if context is not None:
            kwargs.setdefault("extra", {})["context"] = context
        return message, kwargs


class _PortLog:
    def __init__(self, name):
        self.name = name
        self.default = _ContextLog(logging.getLogger(name), {})

    def __getattr__(self, name):
        factory = _ports.get("logger")
        target = factory(self.name) if factory else self.default
        return getattr(target, name)


def get_logger(name):
    return _PortLog(name)


def resolve_source_parquet(name):
    if "source_parquet" in _ports:
        return _ports["source_parquet"](name)
    from myquant_infra.lake.paths import source_parquet
    configured = os.environ.get("OSKH_SOURCE_PARQUET_ROOT")
    if not configured:
        raise RuntimeError("Set OSKH_SOURCE_PARQUET_ROOT or inject source_parquet explicitly")
    return source_parquet(Path(configured), name)


def resolve_data_root(*, explicit_root=None):
    if "data_root" in _ports:
        return _ports["data_root"](explicit_root=explicit_root)
    if explicit_root is None:
        raise RuntimeError("an explicit workspace root or data_root port is required")
    return Path(explicit_root).resolve()


def resolve_turnover_resist_parquet_root():
    if "tr_root" in _ports:
        return _ports["tr_root"]()
    configured = os.environ.get("TURNOVER_RESIST_DATA_DIR") or os.environ.get("OSKH_SOURCE_PARQUET_ROOT")
    if not configured:
        raise RuntimeError("an explicit TR parquet directory or tr_root port is required")
    root = Path(configured).resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    return root


def previous_trading_day(value):
    if "previous_trading_day" not in _ports:
        raise RuntimeError("freshness checks require an explicit previous_trading_day port")
    return _ports["previous_trading_day"](value)


def rust_source_root() -> Path:
    return Path(__file__).resolve().parent / "rust" / "turnover-resist"


def research_root() -> Path:
    if "research_root" in _ports:
        return Path(_ports["research_root"]()).resolve()
    configured = os.environ.get("MYQUANT_RESEARCH_ROOT")
    if not configured:
        raise RuntimeError("Set MYQUANT_RESEARCH_ROOT or use a MyQuant research CLI entry")
    root = Path(configured).resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    return root


def resolve_period_root(period):
    if "period_root" in _ports:
        return _ports["period_root"](period)
    from myquant_infra.lake.paths import stock_period_root
    explicit = os.environ.get(f"OSKH_PERIOD_{str(period).upper()}_ROOT")
    container = os.environ.get("OSKH_SOURCE_PARQUET_ROOT")
    if not explicit and not container:
        raise RuntimeError("an explicit parquet container or period root is required")
    return stock_period_root(container, period, explicit_root=explicit)


def StockDataReader(*args, **kwargs):
    if "reader_factory" in _ports:
        return _ports["reader_factory"](*args, **kwargs)
    from myquant_infra.lake.readers import StockDataReader as SharedReader
    root = os.environ.get("OSKH_SOURCE_PARQUET_ROOT")
    workspace = os.environ.get("OSKH_DATA_ROOT")
    if not root or not workspace:
        raise RuntimeError("research readers require OSKH_SOURCE_PARQUET_ROOT and OSKH_DATA_ROOT")
    kwargs.setdefault("base_dir", root)
    kwargs.setdefault("db_dir", workspace)
    kwargs.setdefault("mode", "parquet")
    return SharedReader(*args, **kwargs)


def parse_pool_csv_entries(path):
    if "pool_entries" in _ports:
        return _ports["pool_entries"](path)
    from myquant_infra.reference_data.pool_csv import iter_pool_csv_rows, pool_cell_to_bare, check_pool_duplicate
    from myquant_infra.reference_data.symbols import canonical_from_bare_code
    entries, seen = [], {}
    for number, parts in iter_pool_csv_rows(path):
        bare = pool_cell_to_bare(parts[0] if parts else "")
        code = canonical_from_bare_code(bare) if bare else None
        if code:
            check_pool_duplicate(path, seen, code, number)
            entries.append((code, parts[1] if len(parts) > 1 else ""))
    return entries


def shanghai_now():
    if "clock" in _ports:
        return _ports["clock"]()
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def get_trade_days_sse(*, since=None, until=None, count=None):
    if "trade_days" in _ports:
        return _ports["trade_days"](since=since, until=until, count=count)
    from myquant_infra.reference_data.calendar import SSECalendar, get_trade_days_sse as query
    if since is None or until is None:
        raise RuntimeError("standalone factor research requires explicit calendar since/until")
    return query(calendar=SSECalendar(start=since, end=until), since=since, until=until, count=count)


def parse_pool_csv(path):
    return [code for code, _name in parse_pool_csv_entries(path)]


def resolve_parquet_container():
    if "parquet_root" in _ports:
        return _ports["parquet_root"]()
    from myquant_infra.lake.paths import parquet_container
    configured = os.environ.get("OSKH_SOURCE_PARQUET_ROOT")
    if not configured:
        raise RuntimeError("OSKH_SOURCE_PARQUET_ROOT is required")
    return parquet_container(configured)


def ensure_repo_on_syspath(_source=None):
    import sys
    root = research_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def resolve_oskh_python():
    if "python" in _ports:
        return _ports["python"]()
    import sys
    return sys.executable


def shanghai_date_yyyymmdd():
    return shanghai_now().strftime("%Y%m%d")
