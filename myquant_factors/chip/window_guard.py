# -*- coding: utf-8 -*-
"""TR window validation helpers (RFC-003 §4.6)."""

from __future__ import annotations

import warnings

from myquant_factors.chip.constants import CANONICAL_TR_WINDOW, TRWindow


def assert_tr_window_consistent(window: int, *, expected: TRWindow = CANONICAL_TR_WINDOW) -> None:
    if window != expected:
        raise ValueError(f"TR window mismatch: got {window}, expected {expected}")


def validate_tr_window_rule(window: int, rule: str) -> None:
    """Legacy/research guard: window=80 rules must include _80 in name."""
    if window == 80 and "_80" not in rule and "_tr80" not in rule.lower():
        raise ValueError(f"rule {rule!r} must include _80 when window=80")


def warn_non_canonical_tr_window(window: int) -> None:
    if window != CANONICAL_TR_WINDOW:
        warnings.warn(
            f"non-canonical TR window {window} (canonical={CANONICAL_TR_WINDOW})",
            stacklevel=2,
        )
