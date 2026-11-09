"""
Author: hugo2046 shen.lan123@gmail.com
Date: 2023-03-27 15:02:44
LastEditors: hugo2046 shen.lan123@gmail.com
LastEditTime: 2023-03-29 10:50:17
Description: 计算筹码分布
"""
from typing import Any, Optional, Union, cast

import numpy as np
import pandas as pd
from loguru import logger
from numba import jit

from .distribution_of_chips import calc_adj_turnover, calc_triang_pdf, calc_uniform_pdf, make_price_grid

#################### 计算概率分布 ####################


def calc_curpdf(
    close: float,
    high: float,
    low: float,
    vol: float,
    min_p: Optional[float] = None,
    max_p: Optional[float] = None,
    step: float = 0.01,
    method: str = "triang",
) -> np.ndarray:
    """计算当日的curpdf

    Args:
        close (float): 收盘价
        high (float): 最高价
        low (float): 最低价
        vol (float): 成交量
        min_p (float): N日的最低价
        max_p (float): N日的最高价
        step (float): min_p至max_p的步长.Defaults to 0.01.
        method (str, optional): 计算概率分布的方法. Defaults to "triang".
            triang: 三角分布
            uniform: 平均分布

    Returns:
        np.ndarray: 成交量分布
    """
    method_norm = method.lower()

    if method_norm == "triang":

        return calc_triang_pdf(close, high, low, vol, min_p, max_p, step)

    elif method_norm == "uniform":

        return calc_uniform_pdf(close, high, low, vol, min_p, max_p, step)

    else:
        raise ValueError("method must be triang or uniform")


@jit(nopython=True)
def calc_cumpdf(curpdf: np.ndarray, turnover: np.ndarray, A: float = 1.0) -> np.ndarray:
    """计算N日累计的cumpdf

    Args:
        curpdf (np.ndarray): curpdf
        turnover (np.ndarray): 换手率
        A (float, optional): 系数. Defaults to 1.0.

    Returns:
        np.ndarray: 累计的vol (形状为 (N_prices,))
    """
    decay: np.ndarray = turnover * A
    diff: np.ndarray = 1 - decay

    mul_array: np.ndarray = (curpdf.T * decay).T
    size: int = len(turnover)
    cumpdf: np.ndarray = np.empty(size)
    for i in range(size):
        cumpdf = cumpdf * diff[i] + mul_array[i] if i else curpdf[i] * decay[i]

    return cumpdf


def calc_dist_chips(
    arr: Union[pd.DataFrame, np.ndarray], method: str, step: float = 0.01
) -> pd.Series:
    """计算筹码分布
       close也能是avg
    Args:
        arr (pd.DataFrame|np.ndarray): index-date columns - close|avg, high, low, vol, turnover_rate
        method (str): 计算分布的方法
            triang: 三角分布
            uniform: 平均分布
            turn_coeff: 换手率系数
    Returns:
        pd.Series: index-price, value-vol
    """
    if isinstance(arr, pd.DataFrame):
        frame = arr[["close", "high", "low", "vol", "turnover_rate"]]
        values = frame.to_numpy()
    else:
        values = np.asarray(arr)

    method_norm = method.lower()
    cum_vol: pd.Series

    if method_norm in {"triang", "uniform"}:

        # max_p,min_p可能区间为nan
        max_p: float = float(np.nanmax(values[:, 1]))
        min_p: float = float(np.nanmin(values[:, 2]))
        try:
            xs: np.ndarray = make_price_grid(min_p, max_p, step)
        except ValueError as e:
            logger.warning(f"min_p:{min_p}, max_p:{max_p};此段时间可能停牌,请检查")
            raise e

        try:
            curpdf: np.ndarray = np.apply_along_axis(
                lambda x: calc_curpdf(
                    x[0], x[1], x[2], x[3], min_p, max_p, step, method_norm
                ),
                1,
                values,
            )
        except Exception as e:
            print(min_p, max_p)
            raise e
        cum_vol_arr = calc_cumpdf(curpdf, values[:, 4])
        cum_vol = pd.Series(cum_vol_arr, index=xs)

    elif method_norm == "turn_coeff":

        turn_coeff: np.ndarray = calc_adj_turnover(values[:, 4])
        total_vol: float = float(values[:, 3].sum())
        coeff_series = pd.Series(
            data=turn_coeff,
            index=values[:, 1],
        )
        grouped = coeff_series.groupby(level=0).sum()
        cum_vol = pd.Series(grouped.to_numpy() * total_vol, index=grouped.index)

    else:
        raise ValueError(f"unknown method: {method}")

    return cum_vol


#################### 筹码分布因子 ####################


class ChipFactor:
    def __init__(
        self,
        close: float,
        cumpdf: pd.Series,
    ) -> None:

        self.close = close
        self.cumpdf = cumpdf  # 过去N日的成交分布

        self.cumpdf.index.names = ["price"]
        self.cumpdf.name = "cumpdf"

    @staticmethod
    def winsorize(cumpdf: pd.Series, scale: int = 3) -> pd.Series:

        std_val = float(cumpdf.std())
        mean_val = float(cumpdf.mean())

        return cumpdf.clip(mean_val - scale * std_val, mean_val + scale * std_val)

    def get_asr(self, lower: float = 0.9, upper: float = 1.1) -> float:
        """活动筹码

        当前价位上下10%的区间中筹码分布的所占比例
        ------
        该指标值很高时，说明股价处于筹码密集区，反之，当指标值很小时，说明当前股价处于无筹码的真空地带。
        如果近期股价上涨/下跌时该指标值较小，说明上下没有明显的支撑/阻力。
        """
        return self.get_winner(upper * self.close) - self.get_winner(lower * self.close)

    def get_cyqk_c(self) -> float:
        """盈利占比

        当前价位以下的筹码分布占比=getwinner(close)
        ------
        当盈利占比很高时，此时市场中大部分投资者都是处于盈利状态，该股票面临抛售压力。
        当没有大盘支撑和利好的基本面信息的情况下，该股票在市场上是会面临供大于求，根据供需理论，会导致股票价格的下跌。
        当盈利占比很低时，此时股票的价格也是处于历史比较低的价位。股票价格上涨的空间也比较大。
        """
        return self.get_winner(self.close)

    def get_ckdw(self, scale: int = 3) -> float:
        """成本重心

        成本重心CKDW=（平均成本价-最低成本价）/（最高成本价-最低成本价）
        ------
        当成本重心（筹码低位密集指标值）很小，筹码分布会呈现低位密集状态。一般股价放量突破单峰密集，会是一轮上涨行情的开始。

        为了避免极值影响,max/min经过三次正太分布winsorize获得
        """
        winsorize: pd.Series = self.cumpdf

        if scale is not None:
            # 当scale不为None时，对cumpdf进行winsorize
            winsorize: pd.Series = self.winsorize(winsorize, scale)
        # 平均成本
        mean: float = self.get_cost(0.5)
        min_p = float(cast(Any, winsorize.idxmin()))
        max_p = float(cast(Any, winsorize.idxmax()))

        return (mean - min_p) / (max_p - min_p)

    def get_prp(self) -> float:
        """价格相对位置

        价格相对位置PRP=(当前价格-平均成本) / 平均成本
        ------
        当价格相对位置指标值越小，当前所处的价位就越低。
        """

        # 平均成本
        avg: float = self.get_cost(0.5)

        return self.close / avg - 1

    def get_winner(self, price: float) -> float:
        """计算时某一价位的获利比例

        Args:
            price (float): 价格

        Returns:
            float: 获利比例
        """
        tot_cnt: float = self.cumpdf.sum()  # 总筹码数
        # P0-17 FIX: 空/损坏分布返回 NaN，禁止静默返回 0.0 伪装"0%获利盘"
        if tot_cnt <= 0 or len(self.cumpdf) == 0:
            return float("nan")
        # 累计筹码比例
        acc_cum: pd.Series = self.cumpdf / tot_cnt

        return acc_cum[acc_cum.index <= price].sum()

    def get_cost(self, winner_ratio: float) -> float:
        """给定累计获利比率winner_ratio,计算对应的价位,表示在此价位上winner_ratio的筹码处于获利状态

        Args:
            winner_ratio (float): 0~1之间的数值 表示累计获利比率

        Returns:
            float: 获利盘的价位
        """
        if (winner_ratio < 0) or (winner_ratio > 1):
            raise ValueError("winner_ratio must be in [0,1]")

        tot_cnt: float = self.cumpdf.sum()  # 总筹码数
        # P0-17 FIX: 空/损坏分布返回 NaN，避免 pandas 零除 warning + 隐式 NaN 传播
        if tot_cnt <= 0 or len(self.cumpdf) == 0:
            return float("nan")
        # 累计筹码比例
        acc_cum: pd.Series = (self.cumpdf / tot_cnt).cumsum()

        threshold_ser = cast(pd.Series, acc_cum[acc_cum < winner_ratio])
        if threshold_ser.empty:
            return float("nan")
        return float(cast(Any, threshold_ser.index[-1]))
