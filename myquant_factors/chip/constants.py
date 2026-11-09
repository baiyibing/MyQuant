# -*- coding: utf-8 -*-
"""TR window constants (RFC-003 §4.6)."""

from __future__ import annotations

from typing import Literal

TRWindow = Literal[80, 1000]
CANONICAL_TR_WINDOW: TRWindow = 1000
