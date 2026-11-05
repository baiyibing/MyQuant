# -*- coding: utf-8 -*-
"""MQ compatibility caller; production implementation lives in myquant-infra."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import os

if __package__:
    from . import _infra_qlib as host
else:
    import _infra_qlib as host

_adapter = host.adapter("refresh_mydata")

# eng-perf P1-1: dump workers are independent of qlib kernels and LGB threads.
DEFAULT_MAX_WORKERS = 8
DEFAULT_ARCHIVE_DIR = Path.home() / ".qlib/qlib_data/my_data_20260410_archived"
DEFAULT_QLIB_DIR = Path.home() / ".qlib/qlib_data/my_data"
WIN_7Z = Path(r"C:\Program Files\7-Zip\7z.exe")
CSV_VALIDATOR = "qlib_scripts.csv_float_scan:scan_csv_dir"


@dataclass
class RefreshConfig(_adapter.RefreshConfig):
    archive_dir: Path = DEFAULT_ARCHIVE_DIR
    csv_dir: Path | None = None
    qlib_dir: Path = DEFAULT_QLIB_DIR
    lake_index_root: Path | None = None
    staging_dir: Path | None = None
    new_qlib_dir: Path | None = None
    csv_validator_spec: str | None = CSV_VALIDATOR
    verify_patch: bool = True

    def resolve_paths(self):
        parent = self.qlib_dir.expanduser().resolve().parent
        stamp = self.today.strftime("%Y%m%d")
        self.staging_dir = self.staging_dir or parent / ("my_data_staging_" + stamp)
        self.new_qlib_dir = self.new_qlib_dir or parent / ("my_data_new_" + stamp)
        super().resolve_paths()


def build_parser():
    parser = host.parser_with_defaults(
        _adapter.build_parser(), archive_dir=str(DEFAULT_ARCHIVE_DIR), csv_dir="",
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
    cfg = _adapter.config_from_args(resolve_args(args, today), today=today)
    pin = str(os.environ.get("OSKH_SOURCE_PARQUET_ROOT") or "").strip()
    cfg.source_parquet_root = Path(pin) if pin else None
    return cfg


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = config_from_args(args)
    # Preserve MQ's whole-lake boundary in addition to infra's explicit roots.
    _adapter.require_valid(cfg)
    return _adapter.main(host.arguments(_adapter.build_parser(), args))


def __getattr__(name):
    return getattr(_adapter, name)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except _adapter.RefreshError as exc:
        print("ERROR: " + str(exc), file=host.sys.stderr)
        raise SystemExit(2) from exc
