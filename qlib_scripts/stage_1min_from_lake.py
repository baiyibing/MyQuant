# -*- coding: utf-8 -*-
"""MQ compatibility caller; production implementation lives in myquant-infra."""

from pathlib import Path

if __package__:
    from . import _infra_qlib as host
else:
    import _infra_qlib as host


def _load_backend():
    return host.adapter("stage_1min_from_lake")


DEFAULT_STAGING = Path(r"D:\qlib_data\_staging_1min")


def build_parser():
    return host.parser_with_defaults(
        host.cli.stage_1min_from_lake_parser(), lake_root=None, staging_dir=DEFAULT_STAGING,
    )


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    backend = _load_backend()
    args = host.minute_paths(args)
    return backend.main(host.arguments(parser, args))


def __getattr__(name):
    return host.adapter_attribute(_load_backend, name)


if __name__ == "__main__":
    raise SystemExit(main())
