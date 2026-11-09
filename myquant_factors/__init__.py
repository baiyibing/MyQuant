# pyright: reportUnusedImport=false
# re-export hub — imports consumed by external callers; pyright cannot trace cross-module re-export
"""myquant_factors — 筹码分布纯算法包。

核心算法仅依赖 numpy/pandas/numba，无可视化/外部依赖。
用法::

    from myquant_factors import ChipFactor, calc_dist_chips, calc_cumpdf, calc_curpdf
    from myquant_factors import calc_distribution_of_chips, calc_rc, calc_roll_cyq
"""

from .cyq import ChipFactor, calc_curpdf, calc_cumpdf, calc_dist_chips
from .distribution_of_chips import calc_adj_turnover, calc_triang_pdf, calc_uniform_pdf
from .turnover_coefficient_ops import (
    calc_distribution_of_chips,
    calc_rc,
    calc_roll_cyq,
)
from .utils import rolling_frame, rolling_windows

from .chip.bands import classify_tr_bb_signal, compute_tr_bb_columns
from .chip.core import adapt_columns, compute_crossday_turnover_resistance
from .price_bb import bb_position
from .weekly_macd_divergence import DivergenceSignal, detect_weekly_macd_divergence
