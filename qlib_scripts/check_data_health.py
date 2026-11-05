# -*- coding: utf-8 -*-
"""MQ compatibility caller; production implementation lives in myquant-infra."""

if __package__:
    from . import _infra_qlib as host
else:
    import _infra_qlib as host

_adapter = host.adapter("check_data_health")


def main(argv=None):
    return _adapter.main(host.legacy_fire_arguments(argv, "check_data"))


def __getattr__(name):
    return getattr(_adapter, name)


if __name__ == "__main__":
    raise SystemExit(main())
