# -*- coding: utf-8 -*-
"""MQ compatibility caller; production implementation lives in myquant-infra."""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable
import os

if __package__:
    from . import _infra_qlib as host
else:
    import _infra_qlib as host


def _load_backend():
    return host.adapter("refresh_mydata")


# eng-perf P1-1: dump workers are independent of qlib kernels and LGB threads.
DEFAULT_MAX_WORKERS = 8
DEFAULT_ARCHIVE_DIR = Path.home() / ".qlib/qlib_data/my_data_20260410_archived"
DEFAULT_QLIB_DIR = Path.home() / ".qlib/qlib_data/my_data"
WIN_7Z = Path(r"C:\Program Files\7-Zip\7z.exe")
CSV_VALIDATOR = "qlib_scripts.csv_float_scan:scan_csv_dir"


class _RefreshError(RuntimeError):
    """CSV preflight failure when the optional production adapter is absent."""


@dataclass
class RefreshConfig:
    # Keep configuration and skipped preflights usable without production infra.
    # These fields mirror the pinned adapter, with MQ's existing defaults.
    archive_dir: Path = DEFAULT_ARCHIVE_DIR
    csv_dir: Path | None = None
    qlib_dir: Path = DEFAULT_QLIB_DIR
    lake_index_root: Path | None = None
    staging_dir: Path | None = None
    new_qlib_dir: Path | None = None
    lake_symbol: str = "000001_SH"
    max_workers: int = DEFAULT_MAX_WORKERS
    expected_delist_max: int = 50
    force: bool = False
    dry_run: bool = False
    skip_merge: bool = False
    skip_dump: bool = False
    skip_patch: bool = False
    skip_swap: bool = False
    archive: bool = False
    offsite: bool = False
    offsite_dirs: tuple[Path, ...] = field(default_factory=tuple)
    seven_zip: Path | None = None
    python: Path = field(default_factory=lambda: Path(host.sys.executable))
    sample_symbols: tuple[str, ...] = ()
    today: date = field(default_factory=date.today)
    allow_beyond_lake: bool = False
    wipe_new_qlib_dir: bool = False
    skip_csv_scan: bool = False
    min_dump_free_gb: float = 3.0
    min_staging_free_gb: float = 2.0
    source_parquet_root: Path | None = None
    csv_validator: Callable[[Path], dict] | None = None
    csv_validator_spec: str | None = CSV_VALIDATOR
    verify_patch: bool = True

    def resolve_paths(self):
        parent = self.qlib_dir.expanduser().resolve().parent
        stamp = self.today.strftime("%Y%m%d")
        self.staging_dir = self.staging_dir or parent / ("my_data_staging_" + stamp)
        self.new_qlib_dir = self.new_qlib_dir or parent / ("my_data_new_" + stamp)
        _load_backend().RefreshConfig.resolve_paths(self)


def build_parser():
    parser = host.parser_with_defaults(
        host.cli.refresh_mydata_parser(), archive_dir=str(DEFAULT_ARCHIVE_DIR), csv_dir="",
        qlib_dir=str(DEFAULT_QLIB_DIR), staging_dir="", new_qlib_dir="", lake_index_root="",
        csv_validator=CSV_VALIDATOR, verify_patch=True,
    )
    parser.add_argument("--skip-verify-patch", dest="verify_patch", action="store_false",
                        help="skip optional qlib index readback")
    return parser


def resolve_args(args, today=None):
    roots = host.data_roots()
    args.csv_dir = str(roots.resolve_qlib_csv_dir(explicit_root=args.csv_dir or None))
    args.lake_index_root = str(args.lake_index_root or roots.resolve_index_1d_none())
    parent = Path(args.qlib_dir).expanduser().resolve().parent
    stamp = (today or date.today()).strftime("%Y%m%d")
    args.staging_dir = args.staging_dir or str(parent / ("my_data_staging_" + stamp))
    args.new_qlib_dir = args.new_qlib_dir or str(parent / ("my_data_new_" + stamp))
    if not args.seven_zip and WIN_7Z.is_file():
        args.seven_zip = str(WIN_7Z)
    return args


def config_from_args(args, *, today=None):
    backend = _load_backend()
    cfg = backend.config_from_args(resolve_args(args, today), today=today)
    pin = str(os.environ.get("OSKH_SOURCE_PARQUET_ROOT") or "").strip()
    cfg.source_parquet_root = Path(pin) if pin else None
    return cfg


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    backend = _load_backend()
    cfg = config_from_args(args)
    # Preserve MQ's whole-lake boundary in addition to infra's explicit roots.
    backend.require_valid(cfg)
    return backend.main(host.arguments(backend.build_parser(), args))


def run_csv_scan_preflight(cfg):
    # Preserve C2's host scanner bridge; skipping it never needs production infra.
    if cfg.skip_merge or cfg.skip_csv_scan:
        return None
    if cfg.csv_validator is not None or cfg.csv_validator_spec not in (None, CSV_VALIDATOR):
        return _load_backend().run_csv_scan_preflight(cfg)
    if __package__:
        from .csv_float_scan import format_scan_report, scan_csv_dir
    else:
        from csv_float_scan import format_scan_report, scan_csv_dir

    report = scan_csv_dir(cfg.csv_dir)
    print(format_scan_report(report))
    if report["fatal"]:
        files = sorted({hit["file"] for hit in report["fatal"]})
        raise __getattr__("RefreshError")(
            "CSV 的 OHLC/volume/factor 含 Windows 非法浮点，拒绝入库: " + ", ".join(files[:10])
        )
    return report


def __getattr__(name):
    if name == "RefreshError":
        try:
            return _load_backend().RefreshError
        except host.InstallError:
            return _RefreshError
    return host.adapter_attribute(_load_backend, name)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        if not isinstance(exc, __getattr__("RefreshError")):
            raise
        print("ERROR: " + str(exc), file=host.sys.stderr)
        raise SystemExit(2) from exc
