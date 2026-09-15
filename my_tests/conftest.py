# -*- coding: utf-8 -*-
"""Keep my_scripts ahead of qlib_scripts on sys.path.

Both trees ship a ``custom_handler.py``; DropLimitUpLearn / the current
Alpha158CostKDJ live only under my_scripts. Collection order can let a
qlib_scripts-first insert (e.g. test_csv_float_scan) shadow my_scripts for
later modules that only insert when absent. Pinning here at conftest load
covers the common case; tests that bare-import custom_handler also force
re-pin before import.
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
_QLIB_SCRIPTS = os.path.join(_ROOT, "qlib_scripts")


def _pin_my_scripts_first() -> None:
    for p in (_MY_SCRIPTS, _QLIB_SCRIPTS):
        while p in sys.path:
            sys.path.remove(p)
    # qlib_scripts still available, but after my_scripts so custom_handler wins.
    sys.path.insert(0, _QLIB_SCRIPTS)
    sys.path.insert(0, _MY_SCRIPTS)


_pin_my_scripts_first()
