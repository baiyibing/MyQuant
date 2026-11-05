# -*- coding: utf-8 -*-
"""Host CLI and compatibility imports for the infra CSV float validator.

Install the optional, pinned ``myquant-infra[data-validation]`` dependency as
documented in docs/engineering/c2-csv-float-infra-switch-20261105.md.
Importing this module and displaying CLI help do not require that package.
"""

from __future__ import annotations

import argparse
from importlib import import_module
from pathlib import Path
from types import ModuleType

_INFRA_MODULE = "myquant_infra.data_validation.csv_float"
_INFRA_EXPORTS = (
    "ILLEGAL_FLOAT_RE",
    "ILLEGAL_CELL_RE",
    "PRICE_FIELDS",
    "ID_COLUMNS",
    "file_has_illegal_float",
    "inspect_csv_illegal",
    "scan_csv_dir",
    "summarize_hits_by_column",
    "format_column_summary",
    "format_scan_report",
)
__all__ = [*_INFRA_EXPORTS, "build_parser", "main"]


def _load_backend() -> ModuleType:
    try:
        return import_module(_INFRA_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name not in {
            "myquant_infra",
            "myquant_infra.data_validation",
            _INFRA_MODULE,
        }:
            raise
        raise ModuleNotFoundError(
            "CSV float validation requires the optional pinned "
            "myquant-infra[data-validation] package. See "
            "docs/engineering/c2-csv-float-infra-switch-20261105.md "
            "for installation and rollback.",
            name=exc.name,
        ) from exc


def __getattr__(name: str):
    if name in _INFRA_EXPORTS:
        return getattr(_load_backend(), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="扫描 CSV 批中的 MSVC/Windows 非法浮点串")
    p.add_argument("--csv-dir", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    backend = _load_backend()
    report = backend.scan_csv_dir(Path(args.csv_dir))
    print(backend.format_scan_report(report))
    return 2 if report["fatal"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
