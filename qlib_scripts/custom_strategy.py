from qlib.strategy.base import BaseStrategy

# 策略实现
class KDJStrategy(BaseStrategy):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def generate_decision(self, execute_result=None, **kwargs):
        # 获取信号
        pred_score = execute_result.prediction

        # 生成决策
        # MAIRU信号为1时买入，否则卖出
        decision = (pred_score["score"] > 0.5).astype(int)

        return decision