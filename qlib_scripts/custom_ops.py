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

        values = series.values.astype(np.float64)
        n = len(values)
        sma = np.full(n, np.nan, dtype=np.float64)
        alpha = self.M / self.N
        beta = 1.0 - alpha

        # Find first valid index
        first_valid = None
        for i in range(n):
            if not np.isnan(values[i]):
                sma[i] = values[i]
                first_valid = i
                break

        if first_valid is None:
            return pd.Series(sma, index=series.index)

        # Recursive computation
        for i in range(first_valid + 1, n):
            if np.isnan(values[i]):
                sma[i] = np.nan
            else:
                sma[i] = alpha * values[i] + beta * sma[i - 1]

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