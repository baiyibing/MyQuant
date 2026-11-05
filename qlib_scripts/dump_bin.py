# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
# -*- coding: utf-8 -*-
"""MQ compatibility caller; production implementation lives in myquant-infra."""

if __package__:
    from . import _infra_qlib as host
else:
    import _infra_qlib as host


def _load_backend():
    return host.adapter("dump_bin")


def build_parser():
    return host.cli.dump_parser()


def main(argv=None):
    # Parse before loading the adapter so --help and usage errors are standalone.
    parser = build_parser()
    args = parser.parse_args(argv)
    return _load_backend().main(host.arguments(parser, args))


def __getattr__(name):
    return host.adapter_attribute(_load_backend, name)


if __name__ == "__main__":
    raise SystemExit(main())
