# -*- coding: utf-8 -*-
"""MQ compatibility caller; production implementation lives in myquant-infra."""

from pathlib import Path

if __package__:
    from . import _infra_qlib as host
else:
    import _infra_qlib as host

_adapter = host.adapter("stage_etf_daily_from_lake")

DEFAULT_STAGING = Path(r"D:\qlib_data\_staging_etf_1d")
resolve_etf_front_root = host.etf_front_root


def build_parser():
    return host.parser_with_defaults(
        _adapter.build_parser(), lake_root=None, staging_dir=DEFAULT_STAGING,
    )


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.lake_root = resolve_etf_front_root(args.lake_root)
    return _adapter.main(host.arguments(parser, args))


def __getattr__(name):
    return getattr(_adapter, name)


if __name__ == "__main__":
    raise SystemExit(main())
