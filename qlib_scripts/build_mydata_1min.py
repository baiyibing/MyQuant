# -*- coding: utf-8 -*-
"""MQ compatibility caller; production implementation lives in myquant-infra."""

from pathlib import Path

if __package__:
    from . import _infra_qlib as host
else:
    import _infra_qlib as host


def _load_backend():
    return host.adapter("build_mydata_1min")


DEFAULT_STAGING = Path(r"D:\qlib_data\_staging_1min")
DEFAULT_QLIB_DIR = Path.home() / ".qlib/qlib_data/my_data_1min"
DAILY_QLIB = Path.home() / ".qlib/qlib_data/my_data"


def build_parser():
    return host.parser_with_defaults(
        host.cli.build_mydata_1min_parser(), lake_root=None, staging_dir=DEFAULT_STAGING,
        qlib_dir=DEFAULT_QLIB_DIR, daily_dir=DAILY_QLIB,
    )


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    backend = _load_backend()
    backend.refuse_if_daily(args.qlib_dir, args.daily_dir)
    backend.refuse_if_daily(args.staging_dir, args.daily_dir)
    if args.skip_stage:
        # A prepared staging batch needs no lake configuration.
        backend.require_disjoint([args.qlib_dir, args.staging_dir],
                                 [args.daily_dir, args.lake_root, args.index_lake])
        workers = backend.clamp_workers(args.max_workers)
        backend.dump_all_1min(args.staging_dir, args.qlib_dir.expanduser(), workers)
        print("qlib 1min dir → " + str(args.qlib_dir.expanduser()))
        return 0
    args = host.minute_paths(args)
    return backend.main(host.arguments(parser, args))


def __getattr__(name):
    return host.adapter_attribute(_load_backend, name)


if __name__ == "__main__":
    raise SystemExit(main())
