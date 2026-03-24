from qlib.data.filter import ExpressionDFilter


class UnifiedLimitUpFilter(ExpressionDFilter):
    """
    动态涨停过滤器（时序安全版本 - 修正版）

    核心逻辑：
    - T日收盘后，判断T日是否涨停（非T-1日）
    - 剔除T日涨停的股票，确保T+1日不买入

    双模式支持：
    1. 字段模式：使用 $zhangting（当日涨停标记，0/1）
    2. 价格模式：使用 $close / Ref($close, 1) 计算当日涨幅
    """

    def __init__(self,
                 rule_expression: str = None,  # 允许完全自定义
                 limit_pct: float = 0.095,  # 默认9.5%，与回测一致
                 use_field: str = "$zhangting",  # 优先使用预计算字段
                 fstart_time=None,
                 fend_time=None,
                 keep: bool = False):  # False=剔除涨停股

        if rule_expression is not None:
            # 完全自定义模式
            rule = rule_expression
        elif use_field and use_field.startswith("$"):
            # 字段模式：判断T日是否涨停（当日数据，非Ref）
            # 假设 $zhangting=1 表示涨停，0表示非涨停
            # keep=False 时，我们保留 $zhangting==0 的股票
            if keep:
                rule = f"{use_field} == 1"  # 保留涨停股
            else:
                rule = f"{use_field} == 0"  # 保留非涨停股（剔除涨停）
        else:
            # 价格模式：判断T日收盘 >= T-1日收盘 * (1+limit_pct)
            # 注意：这是当日判断（$close vs Ref($close,1)）
            if keep:
                # 保留涨停股
                rule = f"($close >= Ref($close, 1) * {1 + limit_pct}) & (~IsNaN(Ref($close, 1)))"
            else:
                # 剔除涨停股（保留未涨停）
                rule = f"($close < Ref($close, 1) * {1 + limit_pct}) | IsNaN(Ref($close, 1))"

        super().__init__(
            rule_expression=rule,
            fstart_time=fstart_time,
            fend_time=fend_time,
            keep=keep
        )

    def _getFilterSeries(self, instruments, fstart, fend):
        series = super()._getFilterSeries(instruments, fstart, fend)
        # 处理NaN：新股上市首日（Ref($close,1)为NaN）默认保留（True）
        # 注意：fillna(True) 表示NaN时保留该股票
        return series.fillna(True)