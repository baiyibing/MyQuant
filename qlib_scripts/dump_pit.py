# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""MQ compatibility caller for myquant-infra's financial PIT dump.

CSV ``date`` (or ``date_column_name``) must be the caller-supplied available
date, never the report end. ``period`` is YYYYQQ (quarterly) or YYYY (annual).
Neither this caller nor infra shifts dates or infers availability.
"""

if __package__:
    from . import _infra_qlib as host
else:
    import _infra_qlib as host


def _load_backend():
    return host.adapter("pit")


def build_parser():
    return host.cli.pit_parser()


def main(argv=None):
    # Keep imports, help, and usage errors independent of the optional package.
    parser = build_parser()
    args = parser.parse_args(argv)
    return _load_backend().main(host.arguments(parser, args))


def __getattr__(name):
    return host.adapter_attribute(_load_backend, name)


if __name__ == "__main__":
    raise SystemExit(main())
