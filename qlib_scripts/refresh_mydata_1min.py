# -*- coding: utf-8 -*-
"""MQ compatibility caller; production implementation lives in myquant-infra."""

from pathlib import Path

if __package__:
    from . import _infra_qlib as host
else:
    import _infra_qlib as host

_adapter = host.adapter("refresh_mydata_1min")

DEFAULT_STAGING = Path(r"D:\qlib_data\_staging_1min")
DEFAULT_QLIB_DIR = Path.home() / ".qlib/qlib_data/my_data_1min"
DAILY_QLIB = Path.home() / ".qlib/qlib_data/my_data"
DEFAULT_QLIB_1MIN = DEFAULT_QLIB_DIR


def refuse_if_daily(qlib_dir, daily_dir=None):
    return _adapter.refuse_if_daily(qlib_dir, daily_dir if daily_dir is not None else DAILY_QLIB)


def daily_calendar_fingerprint(daily_dir=None):
    return _adapter.daily_calendar_fingerprint(daily_dir if daily_dir is not None else DAILY_QLIB)


def assert_daily_unchanged(before, daily_dir=None):
    return _adapter.assert_daily_unchanged(before, daily_dir if daily_dir is not None else DAILY_QLIB)


def build_parser():
    return host.parser_with_defaults(
        _adapter.build_parser(), lake_root=None, staging_dir=DEFAULT_STAGING,
        qlib_dir=DEFAULT_QLIB_DIR, daily_dir=DAILY_QLIB,
    )


def main(argv=None):
    parser = build_parser()
    args = host.minute_paths(parser.parse_args(argv))
    _adapter.refuse_if_daily(args.qlib_dir, args.daily_dir)
    _adapter.refuse_if_daily(args.staging_dir, args.daily_dir)
    full_staging = args.staging_dir.parent / (args.staging_dir.name + "_full_new")
    _adapter.refuse_if_daily(full_staging, args.daily_dir)
    if args.receipt is not None:
        _adapter.refuse_if_daily(args.receipt, args.daily_dir)
    return _adapter.main(host.arguments(parser, args))


def __getattr__(name):
    return getattr(_adapter, name)


if __name__ == "__main__":
    raise SystemExit(main())
