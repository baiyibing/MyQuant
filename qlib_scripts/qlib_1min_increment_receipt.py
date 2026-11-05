# -*- coding: utf-8 -*-
"""MQ compatibility caller; production implementation lives in myquant-infra."""

if __package__:
    from . import _infra_qlib as host
else:
    import _infra_qlib as host


def _load_backend():
    return host.adapter("qlib_1min_increment_receipt")


def __getattr__(name):
    return host.adapter_attribute(_load_backend, name)
