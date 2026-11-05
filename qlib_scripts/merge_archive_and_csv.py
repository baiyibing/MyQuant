# -*- coding: utf-8 -*-
"""MQ compatibility caller; production implementation lives in myquant-infra."""

if __package__:
    from . import _infra_qlib as host
else:
    import _infra_qlib as host


def _load_backend():
    return host.adapter("merge_archive_and_csv")


def build_parser():
    return host.parser_with_defaults(host.cli.merge_archive_and_csv_parser(), csv_dir="")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    backend = _load_backend()
    args.csv_dir = host.data_roots().resolve_qlib_csv_dir(explicit_root=args.csv_dir or None)
    return backend.main(host.arguments(parser, args))


def __getattr__(name):
    return host.adapter_attribute(_load_backend, name)


if __name__ == "__main__":
    raise SystemExit(main())
