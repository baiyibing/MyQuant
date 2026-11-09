# -*- coding: utf-8 -*-
"""Price Bollinger band position."""

from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# 布林带位置（统一实现，供 filter_chip_stocks / chip_factor_analysis 复用）
# ---------------------------------------------------------------------------
def bb_position(close: np.ndarray, period: int = 20, nbdev: float = 2.0) -> float:
    """布林带位置：0=下轨, 0.5=中轨, 1=上轨。"""
    if len(close) < period:
        return 0.5
    ma = np.mean(close[-period:])
    std = np.std(close[-period:])
    upper = ma + nbdev * std
    lower = ma - nbdev * std
    band_width = upper - lower
    if band_width < 1e-8:
        return 0.5
    return float((close[-1] - lower) / band_width)
