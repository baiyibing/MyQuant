# -*- coding: utf-8 -*-
"""MQ compatibility caller; production implementation lives in myquant-infra."""

from pathlib import Path

if __package__:
    from . import _infra_qlib as host
else:
    import _infra_qlib as host


def _load_backend():
    return host.adapter("refresh_mydata_1min")


DEFAULT_STAGING = Path(r"D:\qlib_data\_staging_1min")
DEFAULT_QLIB_DIR = Path.home() / ".qlib/qlib_data/my_data_1min"
DAILY_QLIB = Path.home() / ".qlib/qlib_data/my_data"
DEFAULT_QLIB_1MIN = DEFAULT_QLIB_DIR


def refuse_if_daily(qlib_dir, daily_dir=None):
    return _load_backend().refuse_if_daily(qlib_dir, daily_dir if daily_dir is not None else DAILY_QLIB)


def daily_calendar_fingerprint(daily_dir=None):
    return _load_backend().daily_calendar_fingerprint(daily_dir if daily_dir is not None else DAILY_QLIB)


def assert_daily_unchanged(before, daily_dir=None):
    return _load_backend().assert_daily_unchanged(before, daily_dir if daily_dir is not None else DAILY_QLIB)


def build_parser():
    return host.parser_with_defaults(
        host.cli.refresh_mydata_1min_parser(), lake_root=None, staging_dir=DEFAULT_STAGING,
        qlib_dir=DEFAULT_QLIB_DIR, daily_dir=DAILY_QLIB,
    )


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    backend = _load_backend()
    args = host.minute_paths(args)
    backend.refuse_if_daily(args.qlib_dir, args.daily_dir)
    backend.refuse_if_daily(args.staging_dir, args.daily_dir)
    full_staging = args.staging_dir.parent / (args.staging_dir.name + "_full_new")
    backend.refuse_if_daily(full_staging, args.daily_dir)
    if args.receipt is not None:
        backend.refuse_if_daily(args.receipt, args.daily_dir)
    return backend.main(host.arguments(parser, args))


def __getattr__(name):
    return host.adapter_attribute(_load_backend, name)


if __name__ == "__main__":
    raise SystemExit(main())
