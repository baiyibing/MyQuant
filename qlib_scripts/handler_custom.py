# 图表30: 自定义特征代码
import pandas as pd
import numpy as np
from qlib.contrib.data.handler import Alpha158
from qlib.data.ops import EMA, Sub, Div
from tdx_ops import SMA

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

"""
 请使用0.9.7版本qlib实现以下通达信计算：
     L1:=COST(0.01); 
     L2:=COST(99.99); 
     L3:=(C-L1)/(L2-L1)*100; 
     K:SMA(L3,3,1),COLORWHITE; 
     D:SMA(K,3,1),COLORYELLOW; 
     J:3K-2D,COLORFF00FF; 
     MAIRU:=CROSS(J,K) AND J<80;
 将其集成到 Qlib 的 策略回测框架（如 SigAnaRecord 或 PortfolioStrategy），继承Alpha158，MAIRU作为信号因子
"""

class Alpha158CostKDJ(Alpha158):
    """
    扩展 Alpha158，将 L1, L2, L3, K, D, J 全部作为 Alpha 因子，
    并在 get_extended_data 中计算 MAIRU 信号（不用于训练，仅用于回测）。
    """

    def __init__(self, *args, cost_window=250, **kwargs):
        self.cost_window = cost_window
        super().__init__(*args, **kwargs)

    def get_feature_config(self):
        # 获取原始 Alpha158 的特征
        base_features = super().get_feature_config()
        # 添加新因子表达式
        tdx_features = {
            "L1": "Quantile($close, 252, 0.0001)",
            "L2": "Quantile($close, 252, 0.9999)",
            "L3": "Div(Sub($close, L1), Sub(L2, L1) + 1e-6) * 100",  # 需要处理除零
            "K": "SMA(L3, 3, 1)",
            "D": "SMA(K, 3, 1)",
            "J": "Sub(Mul(3, K), Mul(2, D))",
            # "MAIRU": "And(Cross(J, K), Less(J, 80))"
        }
        extended_features = {**base_features, **tdx_features}
        return extended_features

        # # 获取原始 Alpha158 的特征
        # fields, names = super().get_feature_config()
        #
        # N = self.cost_window
        #
        # # === 1. 近似 COST(0.01) 和 COST(99.99) ===
        # L1_expr = f"Ts_Min($low, {N})"          # ≈ COST(0.01)
        # L2_expr = f"Ts_Max($high, {N})"         # ≈ COST(99.99)
        #
        # # === 2. L3: 相对位置 [0, 100] ===
        # L3_expr = f"($close - {L1_expr}) / ({L2_expr} - {L1_expr} + 1e-6) * 100"
        #
        # # === 3. K = SMA(L3, 3, 1) → 使用简单移动平均（Ts_Mean）===
        # K_expr = f"Ts_Mean({L3_expr}, 3)"
        #
        # # === 4. D = SMA(K, 3, 1) ===
        # D_expr = f"Ts_Mean({K_expr}, 3)"
        #
        # # === 5. J = 3*K - 2*D ===
        # J_expr = f"3*({K_expr}) - 2*({D_expr})"
        #
        # # === 添加所有中间变量为 Alpha 因子 ===
        # new_fields = [L1_expr, L2_expr, L3_expr, K_expr, D_expr, J_expr]
        # new_names = ["COST_L1", "COST_L2", "COST_L3", "COST_K", "COST_D", "COST_J"]
        #
        # fields += new_fields
        # names += new_names
        #
        # return fields, names

    def get_extended_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        在数据加载后，基于已计算的 COST_J 和 COST_K 计算 MAIRU 信号。
        注意：为避免未来函数，此处重新计算 K/J 或直接使用已有序列。
        """
        df = super().get_extended_data(df)

        # 从已计算的列中提取
        J = df["COST_J"]
        K = df["COST_K"]

        # CROSS(J, K): J 上穿 K（今日 J > K 且 昨日 J <= K）
        cross = (J > K) & (J.shift(1) <= K.shift(1))
        MAIRU = (cross & (J < 80)).astype(int)

        # 添加信号列（不用于模型训练，仅用于策略回测）
        df["COST_MAIRU"] = MAIRU

        return df