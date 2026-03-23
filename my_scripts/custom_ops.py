# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
import numpy as np
import pandas as pd
from datetime import datetime

# from qlib.contrib.online.operator import Operator
from qlib.data.cache import H
from qlib.data.data import Cal
from qlib.data.ops import ElemOperator, PairOperator, Rolling
from qlib.utils.time import time_to_day_index


class SMA(Rolling):
    """Smoothed Moving Average (Tongdaxin SMA)

    SMA(X, N, M) = (M * X + (N - M) * SMA[1]) / N

    Parameters
    ----------
    feature : Expression
        feature instance
    N : int
        smoothing period (denominator), must be > 0
    M : int
        smoothing weight (numerator), must satisfy 0 < M <= N, default is 1

    Returns
    ----------
    Expression
        a feature instance with smoothed moving average
    """

    def __init__(self, feature, N, M=1):
        if N <= 0:
            raise ValueError("SMA period N must be positive")
        if M <= 0 or M > N:
            raise ValueError("SMA weight M must satisfy 0 < M <= N")
        self.M = M
        super(SMA, self).__init__(feature, N, "sma")

    def __str__(self):
        return "{}({},{},{})".format(type(self).__name__, self.feature, self.N, self.M)

    def _load_internal(self, instrument, start_index, end_index, *args):
        series = self.feature.load(instrument, start_index, end_index, *args)
        if series.empty:
            return series
        values = series.values.astype(np.float64, copy=False)
        n = len(values)
        sma = np.full(n, np.nan, dtype=np.float64)

        # Match the original semantics:
        # - Before the first non-NaN, sma is NaN.
        # - After the first NaN appears (after the first valid point), sma becomes NaN forever.
        valid_mask = ~np.isnan(values)
        if not valid_mask.any():
            return pd.Series(sma, index=series.index)

        first_valid = int(valid_mask.argmax())
        if first_valid + 1 < n:
            tail_invalid_mask = ~valid_mask[first_valid + 1 :]
            if tail_invalid_mask.any():
                first_nan_rel = int(tail_invalid_mask.argmax())
                end = first_valid + 1 + first_nan_rel  # exclusive
            else:
                end = n
        else:
            end = first_valid + 1

        v = values[first_valid:end]  # v contains no NaNs
        m = len(v)
        alpha = self.M / self.N
        beta = 1.0 - alpha

        if m == 1:
            sma[first_valid] = v[0]
        elif beta == 0.0:
            # alpha == 1, recurrence collapses to sma[t] = v[t]
            sma[first_valid:end] = v
        else:
            # Closed-form for y[t] = beta*y[t-1] + alpha*v[t] with y[0] = v[0]
            # => y[t] = beta^t * (v0 + sum_{j=1..t} alpha*v[j]*beta^{-j})
            pow_b = beta ** np.arange(m, dtype=np.float64)
            w = np.zeros(m, dtype=np.float64)
            w[1:] = alpha * v[1:]

            # Compute s[t] = sum_{j=0..t} w[j] * beta^{-j} (w[0] = 0)
            inv_pow_b = beta ** (-np.arange(m, dtype=np.float64))
            s = np.cumsum(w * inv_pow_b)
            sma[first_valid:end] = pow_b * (v[0] + s)

        return pd.Series(sma, index=series.index)

    def get_longest_back_rolling(self):
        # SMA is recursive and depends on all prior data; approximate as large window
        # Use same heuristic as EMA for consistency
        if 0 < self.N < 1:
            return int(np.log(1e-6) / np.log(1 - self.N))
        return self.feature.get_longest_back_rolling() + self.N * 10

    def get_extended_window_size(self):
        lft_etd, rght_etd = self.feature.get_extended_window_size()
        if 0 < self.N < 1:
            size = int(np.log(1e-6) / np.log(1 - self.N))
            lft_etd = max(lft_etd + size - 1, lft_etd)
        else:
            lft_etd = max(lft_etd + self.N * 10, lft_etd)
        return lft_etd, rght_etd