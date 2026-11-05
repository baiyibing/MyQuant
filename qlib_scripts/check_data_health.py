# -*- coding: utf-8 -*-
"""MQ compatibility caller; production implementation lives in myquant-infra."""

if __package__:
    from . import _infra_qlib as host
else:
    import _infra_qlib as host


def _load_backend():
    return host.adapter("check_data_health")


def main(argv=None):
    argv = host.legacy_fire_arguments(argv, "check_data")
    if "--help" in argv or "-h" in argv:
        host.cli.health_parser().parse_args(argv)
    return _load_backend().main(argv)


def __getattr__(name):
    return host.adapter_attribute(_load_backend, name)


if __name__ == "__main__":
    raise SystemExit(main())
