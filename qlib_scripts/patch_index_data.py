# -*- coding: utf-8 -*-
"""MQ compatibility caller; production implementation lives in myquant-infra."""

from pathlib import Path

if __package__:
    from . import _infra_qlib as host
else:
    import _infra_qlib as host

_adapter = host.adapter("patch_index_data")

DEFAULT_QLIB_DIR = Path.home() / ".qlib/qlib_data/my_data"


def build_parser():
    return host.parser_with_defaults(
        _adapter.build_parser(), lake_root="", qlib_dir=str(DEFAULT_QLIB_DIR), staging_dir=None,
    )


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.lake_root = args.lake_root or host.data_roots().resolve_index_1d_none()
    if args.staging_dir is None:
        args.staging_dir = Path(args.qlib_dir).expanduser().parent / "my_data_index_staging"
    return _adapter.main(host.arguments(parser, args))


def __getattr__(name):
    return getattr(_adapter, name)


if __name__ == "__main__":
    raise SystemExit(main())
