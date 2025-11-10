# 图表30: 自定义特征代码
import pandas as pd
import numpy as np
from qlib.contrib.data.handler import Alpha158
from qlib.data.dataset import DataHandlerLP
from qlib.data.ops import EMA, Sub, Div, If
from qlib.strategy.base import BaseStrategy

from qlib.data import D


# from custom_ops import SMA,TDX_SMA

# 先将AlphaSimpleCustom类保存在以下路径:
#     C:/Users/Kang/anaconda3/Library/site-packages/pyqlib-0.6.1.dev0-py3.7-win-amd64.egg/
#     qlib/contrib/data/handler_custom.py
# 再通过参数dataset下的参数handler调用:
#     "handler": {
#         "class": "AlphaSimpleCustom",
#         "module_path": "qlib.contrib.data.handler_custom",
#         "kwargs": data_handler_config,
#     },

class AlphaSimpleCustom(Alpha158):

    def get_feature_config(self):
        # 6个因子: 5/10/20/30/60日均线与当前收盘价比值，macd
        conf = {
            "ma": {"windows": [5, 10, 20, 30, 60]},
            "macd": {},
        }
        return self.parse_config_to_fields(conf)

    @staticmethod
    def parse_config_to_fields(config):
        """create factors from config"""
        fields = []
        names = []

        if "ma" in config:
            windows = config["ma"].get("windows")
            fields += ["Mean($close, %d)/$close" % d for d in windows]
            names += ["MA%d" % d for d in windows]

        if "macd" in config:
            MACD_EXP = ' (EMA($close, 12) - EMA($close, 26))/$close - EMA((EMA($close, 12) - EMA($close, 26))/$close, 9)/$close'
            fields += [MACD_EXP]
            names += ["MACD"]

        return fields, names


# 图表32：通过修改因子库源码自定义标签代码

# 方法二：
# 参考qlib.contrib.data.handler
# 自定义data.dataset.handler.DataHandlerLP类的get_label_config方法

# Alpha158vwap继承Alpha158类，仅更改标签计算方式
class Alpha158vwap(Alpha158):
    def get_label_config(self):
        return (["Ref($vwap, -2)/Ref($vwap, -1) - 1"], ["LABEL0"])

# 若t日收盘生成因子，t+1日开盘买入，t+6日开盘卖出
class AlphaSimpleOpen(Alpha158):
    def get_label_config(self):
        return (["Ref($open, -6)/Ref($open, -1) - 1"], ["LABEL0"])


# （如 SigAnaRecord 或 PortfolioStrategy）
class Alpha158CostKDJ(Alpha158):
    """
    扩展 Alpha158，将 L1, L2, L3, K, D, J 全部作为 Alpha 因子，
    并在 get_extended_data 中计算 MAIRU 信号（不用于训练，仅用于回测）。
    """

    def __init__(self, *args, cost_window=250, include_alpha158=False, include_signal=False, include_lz=False, **kwargs):
        self.cost_window = cost_window
        self.include_alpha158 = include_alpha158
        self.include_signal = include_signal
        self.include_lz = include_lz
        super().__init__(*args, **kwargs)

    def get_feature_config(self):
        # 获取原始 Alpha158 的特征
        fields, names = super().get_feature_config()
        # COST_J 作为 Alpha 因子，可用于模型排序（值越大越看涨）
        # MAIRU_SIGNAL 作为 信号列，仅用于回测策略，不参与模型训练（避免过拟合）

        # 获取原始 Alpha158 的特征
        fields, names = super().get_feature_config()

        N = self.cost_window

        # === 1. 近似 COST(0.01) 和 COST(99.99) ===
        L1_expr = f"Quantile($low, {N}, 0.0001)"          # ≈ COST(0.01)
        L2_expr = f"Quantile($high, {N}, 0.9999)"         # ≈ COST(99.99)

        # === 2. L3: 相对位置 [0, 100] ===
        L3_expr = f"($close - {L1_expr}) / ({L2_expr} - {L1_expr} + 1e-6) * 100"

        # === 3. K = SMA(L3, 3, 1) → 使用简单移动平均（Ts_Mean）===
        # K_expr = f"SMA({L3_expr}, 3, 1)"
        # 使用QLib内置函数替代自定义SMA[5]使用EMA近似SMA(3,1)，性能更好
        # K_expr = f"EMA({L3_expr}, 3)"
        K_expr = f"SMA({L3_expr}, 3, 1)"

        # === 4. D = SMA(K, 3, 1) ===
        # D_expr = f"SMA({K_expr}, 3, 1)"
        # 使用QLib内置函数替代自定义SMA[5]使用EMA近似SMA(3,1)，性能更好
        # D_expr = f"EMA({K_expr}, 3)"
        D_expr = f"SMA({K_expr}, 3, 1)"

        # === 5. J = 3*K - 2*D ===
        J_expr = f"3*({K_expr}) - 2*({D_expr})"

        new_fields = None
        new_names = None
        if self.include_signal:
            # 股票价格同时站上20日线和20周线的qlib表达式
            # Qlib 默认使用日频数据，没有“周线”概念，因此通常将5周均线近似为 25日均线。如果你有真正的周线数据，需先聚合，但一般实盘/回测中用25日均线代替5周均线是行业惯例。
            K20_expr = "($close > Mean($close, 20)) & ($close > Mean($close, 100))"

            MAIRU_expr = f"If(({J_expr} > {K_expr}) & (Ref({J_expr}, 1) <= Ref({K_expr}, 1)) & ({J_expr} < 80) & {K20_expr}, 2, 0)"

            # === 添加所有中间变量为 Alpha 因子 ===
            new_fields = [K_expr, D_expr, J_expr, MAIRU_expr]
            new_names = ["COST_K", "COST_D", "COST_J", "MAIRU_SIGNAL"]
        else:
            new_fields = [K_expr, D_expr, J_expr]
            new_names = ["COST_K", "COST_D", "COST_J"]

        if self.include_lz:
            # ============ 滚动窗口技术指标因子 ============
            windows = [10, 20, 30]  # 定义多个滚动窗口（5日至60日）

            new_fields += ["($volddx-Mean($volddx, %d))/(Std($volddx, %d)+1e-12)" % (d, d) for d in windows]
            new_names += ["VOLDDX_TX%d" % d for d in windows]

            new_fields += ["($bigddx-Mean($bigddx, %d))/(Std($bigddx, %d)+1e-12)" % (d, d) for d in windows]
            new_names += ["BIGDDX_TX%d" % d for d in windows]

            # 3. 价格波动率因子（Standard Deviation, STD）
            new_fields += ["Std($volddx, %d)/(Abs($volddx)+1e-12)" % d for d in windows] # d期volddx标准差与当前volddx的比例
            new_names += ["VOLDDX_STD%d" % d for d in windows]  # 名称如：VOLDDX_STD5, VOLDDX_STD10, ...

            new_fields += ["Std($bigddx, %d)/(Abs($bigddx)+1e-12)" % d for d in windows] # d期bigddx标准差与当前bigddx的比例
            new_names += ["BIGDDX_STD%d" % d for d in windows]  # 名称如：BIGDDX_STD5, BIGDDX_STD10, ...

            # 3. 对流通盘拉动作用1日、3日、5日累计
            windows_s = [1, 3, 5]  # 定义多个滚动窗口（1日至5日）
            new_fields += ["Sum($volddx,%d)/($adfadfbasiccurhold+1e-12)" % d for d in windows_s]
            new_names += ["VOLDDX_R%d" % d for d in windows_s]

            new_fields += ["Sum($bigddx,%d)/($adfadfbasiccurhold+1e-12)" % d for d in windows_s]
            new_names += ["BIGDDX_R%d" % d for d in windows_s]

            # 创建涨停跌停三态因子
            limit_status_expr = f"$zhangting"

            new_fields += [limit_status_expr]
            new_names += ["LIMIT_STATUS"]

            # # 3. 对流通盘拉动作用20日方差
            # new_fields += ["Std($volddx/($csfree+1e-12), %d)" % d for d in windows]
            # new_names += ["VOLDDX_RSTD%d" % d for d in windows]
            #
            # new_fields += ["Std($bigddx/($csfree+1e-12), %d)" % d for d in windows]
            # new_names += ["BIGDDX_RSTD%d" % d for d in windows]

        else:
            pass


        if self.include_alpha158:
            fields.extend(new_fields)
            names.extend(new_names)
        else:
            fields=new_fields
            names=new_names

        return fields, names


class CostKDJSignalHandler(DataHandlerLP):
    """
    自定义 Handler：
      - 包含 Alpha158 所有原始因子（可选，若仅需信号可省略）
      - 新增 COST_L3, COST_K, COST_D, COST_J 作为中间表达式（用于计算 MAIRU）
      - 在后处理中计算 MAIRU 信号（0/1）
    """

    def __init__(self, *args, cost_window=250, include_alpha158=True, **kwargs):
        self.cost_window = cost_window
        self.include_alpha158 = include_alpha158
        super().__init__(*args, **kwargs)

    def get_feature_config(self):
        fields = []
        names = []

        # 可选：包含 Alpha158 原始因子
        if self.include_alpha158:
            alpha158 = Alpha158()
            base_fields, base_names = alpha158.get_feature_config()
            fields.extend(base_fields)
            names.extend(base_names)

        # 添加 COST-KDJ 所需的表达式（即使不输出，也需计算 K/J）
        N = self.cost_window
        L1 = f"Quantile($low, {N}, 0.0001)"          # ≈ COST(0.01)
        L2 = f"Quantile($high, {N}, 0.9999)"         # ≈ COST(99.99)
        L3 = f"($close - {L1}) / ({L2} - {L1} + 1e-6) * 100"
        K = f"SMA({L3}, 3, 1)"
        D = f"SMA({K}, 3, 1)"
        J = f"3*({K}) - 2*({D})"

        # 将 K, D, J 加入特征（用于后续计算 MAIRU）
        fields.extend([K, D, J])
        names.extend(["COST_K", "COST_D", "COST_J"])

        return fields, names

    def get_label_config(self):
        # 复用 Alpha158 的标签（如 Ref($close, -2) / $close - 1）
        alpha158 = Alpha158()
        return alpha158.get_label_config()

    def get_extended_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Qlib v0.9.7 中，DataHandlerLP 支持此方法用于后处理（需在 Dataset 中设置 process_type="append"）
        """
        # 提取已计算的 K 和 J
        K = df["COST_K"]
        J = df["COST_J"]

        # 计算 CROSS(J, K): J 上穿 K
        cross = (J > K) & (J.shift(1) <= K.shift(1))
        MAIRU = (cross & (J < 80)).astype(int)

        # 添加信号列
        df["MAIRU"] = MAIRU
        return df


