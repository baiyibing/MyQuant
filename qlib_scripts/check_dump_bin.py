# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
# -*- coding: utf-8 -*-
"""MQ compatibility caller; production implementation lives in myquant-infra."""

if __package__:
    from . import _infra_qlib as host
else:
    import _infra_qlib as host

_adapter = host.adapter("check_dump_bin")


def main(argv=None):
    return _adapter.main(host.legacy_fire_arguments(argv, "check"))


def __getattr__(name):
    return getattr(_adapter, name)


if __name__ == "__main__":
    raise SystemExit(main())
