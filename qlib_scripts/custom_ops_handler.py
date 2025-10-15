from qlib.contrib.data.handler import Alpha158
from qlib.contrib.online.operator import Operator
from qlib.data import D


class TsQuantile(Operator):
    """
    Time-series rolling quantile.
    Usage: TsQuantile($close, q=0.5, window=60)
    """
    def __init__(self, feature, q, window):
        self.q = q
        self.window = window
        super().__init__(feature)

    def _load_internal(self, instrument, start_index, end_index, freq):
        # Load the underlying feature series
        series = self.feature.load(instrument, start_index, end_index, freq)
        if series.empty:
            return pd.Series(dtype=float)
        # Rolling quantile
        result = series.rolling(window=self.window, min_periods=1).quantile(self.q)
        return result


# adjust=False：确保使用递归形式 y[t] = (1 - α) * y[t-1] + α * x[t]
# 这与通达信 SMA 完全一致
# 通达信中 SMA(X, N, M) 的定义为：
# SMA_t = (M * X_t + (N - M) * SMA_{t-1}) / N
# 这是一个递归指数加权平均，不能用简单 rolling().mean() 替代。
# 我们用 pandas 的 ewm 或 手动递归 实现。但注意：ewm 的 alpha 与 SMA 参数关系为：
# alpha = M / N
# SMA_t = alpha * X_t + (1 - alpha) * SMA_{t-1}
# 这与通达信定义一致！
#
# ✅ 因此可用 ewm 精确实现。
# 自定义 SMA Operator（精确版）
class TDX_SMA(Operator):
    """
    Smoothed Moving Average as in TongdaXin.
    SMA(X, N, M) = M/N * X + (N-M)/N * SMA_prev
    Equivalent to EWM with alpha = M / N.
    """
    def __init__(self, feature, n, m):
        if n <= 0 or m <= 0 or m > n:
            raise ValueError("SMA: n > 0, m > 0, and m <= n required.")
        self.n = n
        self.m = m
        self.alpha = m / n
        super().__init__(feature)

    def _load_internal(self, instrument, start_index, end_index, freq):
        series = self.feature.load(instrument, start_index, end_index, freq)
        if series.empty:
            return pd.Series(dtype=float)
        # Use EWM with adjust=False to match recursive definition
        result = series.ewm(alpha=self.alpha, adjust=False).mean()
        return result


class AlphaJIndicator(Alpha158):
    def get_feature_config(self):
        feature_config = super().get_feature_config()

        close = D.feature("CLOSE")
        window = 60

        # 精确实现 COST 近似
        L1 = TsQuantile(close, q=0.01, window=window)
        L2 = TsQuantile(close, q=0.9999, window=window)

        # 安全计算 L3
        from qlib.data.ops import If, Greater
        L3 = If(
            Greater(L2 - L1, 1e-8),
            (close - L1) / (L2 - L1) * 100,
            50.0
        )

        # 精确 SMA
        K = TDX_SMA(L3, n=3, m=1)      # SMA(L3, 3, 1)
        D_val = TDX_SMA(K, n=3, m=1)   # SMA(K, 3, 1)
        J = 3 * K - 2 * D_val

        feature_config["J"] = J
        return feature_config