"""build_winner_ratio 内核：三角归一化、衰减递推、获利占比。"""

from __future__ import annotations

import os
import sys

import numpy as np

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from build_winner_ratio import _stock_winner_ratio_impl, _triang_into  # noqa: E402


def _tri():
    return getattr(_triang_into, "py_func", None) or _triang_into


def _impl():
    return getattr(_stock_winner_ratio_impl, "py_func", None) or _stock_winner_ratio_impl


def test_triang_normalized_sums_to_vol():
    step = 0.01
    grid = 9.0 + np.arange(int((11.0 - 9.0) / step) + 1) * step
    out = np.zeros(grid.shape[0])
    _tri()(grid, 9.5, 10.5, 10.0, 1000.0, step, out)
    assert abs(out.sum() - 1000.0) < 1e-6
    peak = int(np.argmax(out))
    assert abs(grid[peak] - 10.0) < step + 1e-9


def test_triang_limit_up_point_mass():
    step = 0.01
    grid = 10.0 + np.arange(5) * step
    out = np.zeros(grid.shape[0])
    _tri()(grid, 10.0, 10.0, 10.0, 50.0, step, out)
    assert abs(out.sum() - 50.0) < 1e-9
    assert abs(out[0] - 50.0) < 1e-9


def test_winner_all_chips_at_close_is_one():
    n = 30
    close = np.full(n, 10.0)
    high = np.full(n, 10.0)
    low = np.full(n, 10.0)
    shares = np.full(n, 1e6)
    turnover = np.full(n, 0.05)
    date_pos = np.arange(n, dtype=np.int64)
    capture_flag = np.zeros(n, dtype=np.int8)
    capture_flag[-1] = 1
    capture_slot = np.zeros(n, dtype=np.int64)
    wr = _impl()(close, high, low, shares, turnover, date_pos, capture_flag, capture_slot, 0.01)
    assert wr.shape == (1,)
    assert wr[0] == 1.0


def test_winner_close_below_all_chips_is_zero():
    n = 30
    close = np.full(n, 20.0)
    high = np.full(n, 20.0)
    low = np.full(n, 20.0)
    # 最后一天跌到 10：新筹码在 10，但旧筹码仍在 20；收盘 10 以下应接近 0（仅当日换手）
    close = close.copy()
    high = high.copy()
    low = low.copy()
    close[-1] = 10.0
    high[-1] = 10.0
    low[-1] = 10.0
    shares = np.full(n, 1e6)
    turnover = np.full(n, 0.02)
    date_pos = np.arange(n, dtype=np.int64)
    capture_flag = np.zeros(n, dtype=np.int8)
    capture_flag[-1] = 1
    capture_slot = np.zeros(n, dtype=np.int64)
    wr = _impl()(close, high, low, shares, turnover, date_pos, capture_flag, capture_slot, 0.01)
    # 当日换手 2% 进入 10 元，旧筹码在 20：winner ≈ 当日权重 / 总
    assert wr[0] < 0.05


def test_decay_first_day_uses_turnover():
    n = 12
    close = np.full(n, 10.0)
    high = np.full(n, 10.2)
    low = np.full(n, 9.8)
    shares = np.full(n, 1e6)
    turnover = np.full(n, 0.10)
    date_pos = np.arange(n, dtype=np.int64)
    capture_flag = np.ones(n, dtype=np.int8)
    capture_slot = np.arange(n, dtype=np.int64)
    wr = _impl()(close, high, low, shares, turnover, date_pos, capture_flag, capture_slot, 0.01)
    assert wr.shape == (n,)
    assert np.all(np.isfinite(wr))
    assert np.all((wr >= 0.0) & (wr <= 1.0))
    # 价格围绕 10 对称，获利占比应在中位附近
    assert 0.2 < wr[-1] < 0.8


def test_wide_price_span_does_not_drop_stock():
    """后复权跨度超过网格上限时放宽步长，仍产出有效 winner。"""
    import build_winner_ratio as m

    old = m._MAX_GRID
    m._MAX_GRID = 80
    try:
        n = 12
        close = np.linspace(10.0, 50.0, n)
        high = close + 0.5
        low = close - 0.5
        shares = np.full(n, 1e6)
        turnover = np.full(n, 0.05)
        date_pos = np.arange(n, dtype=np.int64)
        capture_flag = np.zeros(n, dtype=np.int8)
        capture_flag[-1] = 1
        capture_slot = np.zeros(n, dtype=np.int64)
        wr = _impl()(close, high, low, shares, turnover, date_pos, capture_flag, capture_slot, 0.01)
    finally:
        m._MAX_GRID = old
    assert wr.shape == (1,)
    assert np.isfinite(wr[0])
    assert 0.0 <= wr[0] <= 1.0
