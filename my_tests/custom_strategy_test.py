from qlib.strategy.base import BaseStrategy
import qlib
from qlib.contrib.strategy import TopkDropoutStrategy
from qlib.data import D
from qlib.backtest.decision import Order, OrderDir, TradeDecisionWO
import pandas as pd
import numpy as np

import pandas as pd
from qlib.data import D
from qlib.workflow import R
from qlib.utils import init_instance_by_config


class AvoidLimitUpStrategy(BaseStrategy):
    def __init__(self, model, limit_up_threshold=0.099, **kwargs):
        super().__init__(**kwargs)
        self.model = model
        self.limit_up_threshold = limit_up_threshold

    def generate_trade_decision(self, execute_result=None):
        trade_decision = super().generate_trade_decision(execute_result)

        if not trade_decision or not trade_decision.order_list:
            return trade_decision

        # 获取当前日期
        trade_step = self.trade_calendar.get_trade_step()
        current_date = self.trade_calendar.get_step_time(trade_step)[0]

        # 获取所有需要检查的股票
        instruments = list(set([order.stock_id for order in trade_decision.order_list]))

        try:
            # 获取交易日历，找到前一交易日
            trade_dates = D.calendar(start_time=current_date - pd.Timedelta(days=10),
                                     end_time=current_date)
            if len(trade_dates) < 2:
                return trade_decision  # 没有足够交易日数据，返回原始决策

            prev_date = trade_dates[-2]  # 前一交易日

            # 分别获取前一日和当日的收盘价
            prev_close_data = D.features(instruments, ['close'],
                                         start_time=prev_date, end_time=prev_date)
            current_close_data = D.features(instruments, ['close'],
                                            start_time=current_date, end_time=current_date)

            if not prev_close_data.empty and not current_close_data.empty:
                # 重塑数据格式
                prev_close = prev_close_data['close'].unstack(level='instrument').iloc[0]
                current_close = current_close_data['close'].unstack(level='instrument').iloc[0]

                # 确保股票代码对齐
                common_stocks = set(prev_close.index) & set(current_close.index)
                prev_close = prev_close[common_stocks]
                current_close = current_close[common_stocks]

                # 计算涨跌幅
                pct_change = (current_close - prev_close) / prev_close

                # 处理可能的NaN值
                pct_change = pct_change.dropna()

                # 识别涨停股
                limit_up_stocks = pct_change[pct_change >= self.limit_up_threshold].index.tolist()

                # 过滤订单
                filtered_orders = []
                for order in trade_decision.order_list:
                    if order.stock_id in limit_up_stocks and order.direction == Order.BUY:
                        continue  # 跳过买入涨停股的订单
                    filtered_orders.append(order)

                trade_decision.order_list = filtered_orders

        except Exception as e:
            print(f"Error in AvoidLimitUpStrategy: {e}")
            # 记录更详细的错误信息
            import traceback
            traceback.print_exc()

        return trade_decision


class KDJStrategy(BaseStrategy):
    def __init__(self, position_ratio=0.1, **kwargs):
        super().__init__(**kwargs)
        self.position_ratio = position_ratio  # 每只股票仓位比例

    def generate_trade_decision(self, execute_result=None):
        """
        生成KDJ策略的交易决策
        """
        if execute_result is None or not hasattr(execute_result, 'prediction'):
            return TradeDecisionWO([], self)

        pred_score = execute_result.prediction

        # 确保pred_score是DataFrame格式
        if isinstance(pred_score, pd.Series):
            pred_score = pred_score.to_frame(name='score')

        # 生成决策：信号为1时买入，否则不操作
        buy_signals = pred_score["score"] > 0.5

        # 如果没有买入信号，返回空决策
        if not buy_signals.any():
            return TradeDecisionWO([], self)

        # 生成订单
        orders = []
        trade_step = self.trade_calendar.get_trade_step()
        trade_start_time, trade_end_time = self.trade_calendar.get_step_time(trade_step)

        try:
            # 获取当前可用资金
            current_position = self.trade_exchange.get_current_position()
            available_cash = current_position.get_cash()

            # 计算每只股票的分配金额
            num_stocks_to_buy = buy_signals.sum()
            amount_per_stock = available_cash * self.position_ratio / num_stocks_to_buy

            # 获取所有需要买入的股票
            buy_stocks = buy_signals[buy_signals].index.tolist()

            # 批量获取价格数据，提高效率
            price_data = D.features(buy_stocks, ['close'],
                                    start_time=trade_start_time,
                                    end_time=trade_end_time)

            if not price_data.empty:
                price_data = price_data['close'].unstack(level='instrument').iloc[0]

                for stock_id in buy_stocks:
                    if stock_id in price_data.index and not pd.isna(price_data[stock_id]):
                        price = price_data[stock_id]
                        if price > 0:  # 确保价格有效
                            amount = amount_per_stock / price

                            orders.append(Order(
                                stock_id=stock_id,
                                amount=amount,
                                start_time=trade_start_time,
                                end_time=trade_end_time,
                                direction=Order.BUY
                            ))
        except Exception as e:
            print(f"Error processing stocks in KDJStrategy: {e}")
            import traceback
            traceback.print_exc()

        return TradeDecisionWO(orders, self)


class FilteredTopkDropoutStrategyOld(TopkDropoutStrategy):
    def __init__(self, *args, **kwargs):
        """ 初始化策略 """
        super().__init__(*args, **kwargs)

    def generate_trade_decision(self, execute_result=None):
        """ 专为Qlib 0.9.6优化的交易决策生成
        过滤掉过去5个交易日内上涨>15%的股票 """
        # 1. 调用父类生成决策
        raw_decision = super().generate_trade_decision(execute_result)
        if not raw_decision or not raw_decision.order_list:
            return raw_decision

        # 2. 获取当前日期
        trade_step = self.trade_calendar.get_trade_step()
        current_date = self.trade_calendar.get_step_time(trade_step)[0]

        # 3. 获取所有需要检查的股票
        instruments = list(set([order.stock_id for order in raw_decision.order_list]))

        # 4. 计算过去5日涨幅
        try:
            # 获取交易日历，找到5个交易日前的日期
            trade_dates = D.calendar(start_time=current_date - pd.Timedelta(days=20), end_time=current_date)
            if len(trade_dates) < 6:  # 需要至少6个交易日来计算5日涨幅（t-5到t-1）
                return raw_decision
            start_date = trade_dates[-6]  # 5个交易日前的日期 (t-5)
            prev_date = trade_dates[-2]  # 前一日的日期 (t-1)

            # 获取收盘价数据，到前一日
            close_data = D.features(instruments, ['close'], start_time=start_date, end_time=prev_date)
            if not close_data.empty:
                # 重塑数据格式
                close_series = close_data['close'].unstack(level='instrument')

                # 确保有足够的数据点
                if len(close_series) < 6:
                    return raw_decision

                # 计算5日涨幅：(t-1收盘价 - t-5收盘价) / t-5收盘价
                # 使用shift(1)获取前一日收盘价，shift(5)获取5日前收盘价
                ret_5d = (close_series.shift(1) - close_series.shift(5)) / close_series.shift(5)

                # 获取最新一日的涨幅数据
                if not ret_5d.empty:
                    latest_ret = ret_5d.iloc[-1]

                    # 处理NaN值
                    latest_ret = latest_ret.dropna()

                    # 创建过滤掩码 (过去5日涨幅 > 15%)
                    high_ret_stocks = latest_ret[latest_ret > 0.15].index.tolist()

                    # 5. 过滤订单
                    filtered_orders = []
                    for order in raw_decision.order_list:
                        if (order.direction == Order.BUY and order.stock_id in high_ret_stocks):
                            continue  # 跳过过去5日涨幅超过15%的买入订单
                        filtered_orders.append(order)
                    return TradeDecisionWO(filtered_orders, self)
        except Exception as e:
            print(f"Error in FilteredTopkDropoutStrategy: {e}")
            import traceback
            traceback.print_exc()
            # 如果出错，返回原始决策
            return raw_decision
        return raw_decision


class FilteredTopkDropoutStrategy(TopkDropoutStrategy):
    """过滤过去5日涨幅超过阈值的股票策略（参数化+性能优化版）"""

    def __init__(self, topk, n_drop, high_return_threshold=0.15, *args, **kwargs):
        """
        初始化策略参数（必须提供topk和n_drop）

        :param topk: 选择前topk只股票
        :param n_drop: 从topk中丢弃n_drop只股票
        :param high_return_threshold: 阈值（默认15%），超过此涨幅的股票将被过滤
        :param args: 策略基础参数
        :param kwargs: 策略基础参数
        """
        # 必须传递topk和n_drop给父类
        super().__init__(topk=topk, n_drop=n_drop, *args, **kwargs)
        self.high_return_threshold = high_return_threshold
        self.logger = R.get_logger()
        self.logger.info(f"策略初始化: 阈值={self.high_return_threshold:.2%}, topk={topk}, n_drop={n_drop}")

    def generate_trade_decision(self, execute_result=None):
        """生成交易决策（已修复日期索引错误并优化性能）"""
        # 1. 调用父类生成决策（获取topk股票）
        raw_decision = super().generate_trade_decision(execute_result)
        if not raw_decision or not raw_decision.order_list:
            return raw_decision

        # 2. 获取当前日期
        trade_step = self.trade_calendar.get_trade_step()
        current_date = self.trade_calendar.get_step_time(trade_step)[0]

        # 3. 获取需要处理的股票列表
        instruments = list(set([order.stock_id for order in raw_decision.order_list]))
        if not instruments:
            return raw_decision

        # 4. 获取交易日历（仅需5个交易日，安全范围20天）
        trade_dates = D.calendar(
            start_time=current_date - pd.Timedelta(days=20),
            end_time=current_date
        )
        if len(trade_dates) < 5:
            self.logger.warning(
                f"交易日不足5天 (当前={len(trade_dates)}), 无法计算5日涨幅. 当前日期: {current_date}"
            )
            return raw_decision

        # 5. 优化：只查询需要处理的股票（仅当前决策股票）
        try:
            # 获取收盘价数据（仅限当前决策股票）
            close_data = D.features(
                instruments=instruments,
                fields=['close'],
                start_time=trade_dates[-5],  # t-5
                end_time=trade_dates[-1]  # t-1
            )

            if close_data.empty:
                self.logger.warning("收盘价数据为空，跳过过滤")
                return raw_decision

            # 6. 数据验证与计算
            close_series = close_data['close'].unstack(level='instrument')
            if len(close_series) < 5:
                self.logger.warning(f"数据点不足（需5点，实际={len(close_series)}）")
                return raw_decision

            # 计算5日涨幅: (t-1收盘 - t-5收盘) / t-5收盘
            ret_5d = (close_series.iloc[-1] - close_series.iloc[0]) / close_series.iloc[0]

            # 7. 过滤股票（仅保留涨幅 <= 阈值的股票）
            valid_stocks = ret_5d[ret_5d <= self.high_return_threshold].index.tolist()

            # 8. 生成过滤后的订单
            filtered_orders = [
                order for order in raw_decision.order_list
                if (order.direction == Order.BUY and order.stock_id in valid_stocks) or
                   (order.direction != Order.BUY)  # 卖出订单不过滤
            ]

            # 9. 日志输出过滤结果
            self.logger.info(
                f"过滤策略应用: 原订单={len(raw_decision.order_list)}, "
                f"过滤后={len(filtered_orders)}, "
                f"过滤率={1 - len(filtered_orders) / len(raw_decision.order_list):.1%}"
            )

            return TradeDecisionWO(filtered_orders, self)

        except Exception as e:
            self.logger.error(f"过滤策略执行失败: {str(e)}", exc_info=True)
            return raw_decision


# =============== 测试验证代码 ===============
if __name__ == "__main__":
    """测试用例：验证5日涨幅计算和过滤逻辑"""


    # 模拟测试数据（真实场景中应使用Qlib数据）
    def mock_data():
        # 模拟5个交易日的收盘价（t-5, t-4, t-3, t-2, t-1）
        data = {
            'stockA': [10.0, 10.5, 11.0, 11.5, 12.0],  # 20%涨幅
            'stockB': [10.0, 10.2, 10.4, 10.6, 10.8],  # 8%涨幅
            'stockC': [10.0, 10.0, 10.0, 10.0, 10.0]  # 0%涨幅
        }
        return pd.DataFrame(data, index=pd.date_range(start='2023-01-01', periods=5, freq='B'))


    # 测试策略
    strategy = FilteredTopkDropoutStrategy(
        topk=10,  # 必须提供
        n_drop=2,  # 必须提供
        high_return_threshold=0.15
    )


    # 模拟交易决策（包含3只股票）
    class MockOrder:
        def __init__(self, stock_id, direction=Order.BUY):
            self.stock_id = stock_id
            self.direction = direction


    mock_decision = TradeDecisionWO(
        order_list=[
            MockOrder('stockA'),
            MockOrder('stockB'),
            MockOrder('stockC')
        ],
        strategy=strategy
    )


    # 重写D.features方法用于测试
    def mock_features(instruments, fields, start_time, end_time):
        return mock_data()


    # 临时替换D.features
    D.features = mock_features

    # 执行过滤
    filtered_decision = strategy.generate_trade_decision(mock_decision)

    # 验证结果
    valid_stocks = [order.stock_id for order in filtered_decision.order_list]
    expected_valid = ['stockB', 'stockC']  # stockA涨幅20%>15%被过滤

    print("测试结果:")
    print(f"预期有效股票: {expected_valid}")
    print(f"实际有效股票: {valid_stocks}")
    print(f"过滤是否正确: {sorted(valid_stocks) == sorted(expected_valid)}")

    # 输出测试日志
    print("\n策略日志:")
    strategy.logger.info("测试完成")