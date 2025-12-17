from pprint import pprint

from qlib.contrib.strategy import TopkDropoutStrategy
from qlib.data import D
from qlib.utils import get_pre_trading_date, load_dataset
import pandas as pd
import numpy as np
from qlib.backtest.position import Position
from qlib.backtest.signal import Signal
from qlib.backtest.decision import Order, OrderDir, TradeDecisionWO
from qlib.log import get_module_logger
from qlib.utils import copy
from qlib.contrib.strategy.order_generator import OrderGenerator, OrderGenWOInteract
import pandas as pd
from qlib.backtest.decision import Order, OrderDir, TradeDecisionWO
from qlib.data import D
import numpy as np
from qlib.backtest.signal import Signal
from qlib.contrib.strategy import TopkDropoutStrategy
from loguru import logger

class TopkDropoutStrategyWithFilter(TopkDropoutStrategy):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_return_threshold = 0.15  # 15%
        self.lookback_days = 5  # 回溯天数
        self.logger = get_module_logger("TopkDropoutStrategyWithFilter")


    def _filter_stocks_by_return_threshold0(self, stocks, trade_start_time):
        """
        过滤过去回溯天数内涨幅超过阈值的股票

        Args:
            stocks: 待过滤的股票列表
            trade_start_time: 交易开始时间

        Returns:
            过滤后的股票列表
        """
        # 获取过去lookback_days个交易日的日期
        prev_dates = [get_pre_trading_date(trade_start_time, i) for i in range(1, self.lookback_days + 1)]
        # 获取所有股票在这些日期的收盘价
        # ✅ 修复：使用 D.features + $ 前缀获取数据
        close_prices = D.features(
            instruments=stocks,  # 直接传字符串"all"
            fields=["$close"],  # 关键：字段名带$前缀
            start_time=prev_dates[-1],
            end_time=prev_dates[0],
        )
        # 检查是否为空
        if close_prices.empty:
            self.logger.warning("No price data available, returning original stocks")
            return stocks
        # 重置索引，将datetime和instrument作为列
        close_prices = close_prices.reset_index()
        # ✅ 修复：确保datetime列是datetime类型
        if not pd.api.types.is_datetime64_any_dtype(close_prices["datetime"]):
            close_prices["datetime"] = pd.to_datetime(close_prices["datetime"])
        # ✅ 修复：现在可以安全使用.dt.accessor，将datetime转换为日期
        close_prices["datetime"] = close_prices["datetime"].dt.date
        # 按股票分组，计算每个股票的涨幅
        close_prices = close_prices.sort_values(by=["instrument", "datetime"])
        # 计算过去lookback_days的涨幅（需要shift lookback_days-1天）
        close_prices["close_shift"] = close_prices.groupby("instrument")["$close"].shift(self.lookback_days - 1)
        # 计算涨幅
        close_prices["return"] = (close_prices["$close"] - close_prices["close_shift"]) / close_prices["close_shift"]
        # 处理NaN值
        close_prices["return"] = close_prices["return"].fillna(0)
        # 只保留最近一天的数据
        returns = close_prices.groupby("instrument").last()[["return"]]

        # 过滤涨幅超过阈值的股票
        filtered_stocks = []
        for stock in stocks:
            if stock in returns.index:
                if returns.loc[stock, "return"] <= self.max_return_threshold:
                    filtered_stocks.append(stock)
            else:
                # 如果股票不在returns中，假设涨幅为0
                filtered_stocks.append(stock)

        return filtered_stocks

    def _filter_stocks_by_return_threshold(self, stocks, trade_start_time):
        """ 过滤过去回溯天数内涨幅超过阈值的股票，增强稳定性 """
        # 1. 验证输入参数
        if not stocks or self.lookback_days <= 0 or self.max_return_threshold < 0:
            return stocks  # 简单处理无效输入

        # 2. 获取有效交易日，避免无效日期
        prev_dates = []
        for i in range(1, self.lookback_days + 1):
            date = get_pre_trading_date(trade_start_time, i)
            if date is None:
                # 记录警告，但不中断执行
                logger.warning(f"Invalid trading date for {trade_start_time} - {i} days ago")
            else:
                prev_dates.append(date)

        # 3. 确保至少有一个有效日期
        if not prev_dates:
            logger.error("No valid trading dates found for lookback period")
            return stocks

        # 4. 获取数据，添加错误处理
        try:
            close_prices = D.features(
                instruments=stocks,
                fields=["$close"],
                start_time=prev_dates[-1],
                end_time=prev_dates[0],
            )
        except Exception as e:
            logger.error(f"Failed to fetch stock data: {str(e)}")
            return stocks

        # 5. 处理数据缺失
        if close_prices.empty:
            logger.warning("No stock price data returned")
            return stocks

        # 6. 重置索引，将datetime和instrument作为列
        close_prices = close_prices.reset_index()
        logger.info(
            f"6. 重置索引，将datetime和instrument作为列 {close_prices}")

        # 7. 按股票分组，获取每个股票的起始和结束收盘价
        prices = close_prices.groupby('instrument')["$close"].agg(['first', 'last']).reset_index()
        logger.info(
            f"7. 按股票分组，获取每个股票的起始和结束收盘价 {prices}")


        # 8. 计算涨幅，正确处理缺失值
        prices['return'] = (prices['last'] - prices['first']) / prices['first']
        prices['return'] = prices['return'].fillna(float('-inf'))  # 更安全的缺失值处理

        # 9. 创建股票到涨幅的映射字典
        return_dict = {row['instrument']: row['return'] for _, row in prices.iterrows()}
        pprint('创建股票到涨幅的映射字典')
        pprint(return_dict)
        logger.info(
            f"创建股票到涨幅的映射字典 {return_dict}")

        # 10. 过滤股票，添加日志记录
        filtered_stocks = [stock for stock in stocks if
                           return_dict.get(stock, float('-inf')) <= self.max_return_threshold]

        for stock in stocks:
            return_xxx = return_dict.get(stock, float('-inf'))
            if return_dict.get(stock, float('-inf')) <= self.max_return_threshold:
                logger.info(
                    f"Paasssed {stock} {return_xxx} <= {self.max_return_threshold}")
            else:
                logger.info(
                    f"Filtered {stock} {return_xxx} > {self.max_return_threshold}")

        # 11. 记录过滤结果
        logger.info(
            f"Filtered {len(stocks)} stocks to {len(filtered_stocks)} using return threshold {self.max_return_threshold}")

        return filtered_stocks

    def generate_trade_decision(self, execute_result=None):
        # 调用父类方法获取基础交易决策
        trade_step = self.trade_calendar.get_trade_step()
        trade_start_time, trade_end_time = self.trade_calendar.get_step_time(trade_step)
        pred_start_time, pred_end_time = self.trade_calendar.get_step_time(trade_step, shift=1)
        pred_score = self.signal.get_signal(start_time=pred_start_time, end_time=pred_end_time)

        # NOTE: the current version of topk dropout strategy can't handle pd.DataFrame(multiple signal)
        # So it only leverage the first col of signal
        if isinstance(pred_score, pd.DataFrame):
            pred_score = pred_score.iloc[:, 0]
        if pred_score is None:
            return TradeDecisionWO([], self)

        if self.only_tradable:
            # If The strategy only consider tradable stock when make decision
            # It needs following actions to filter stocks
            def get_first_n(li, n, reverse=False):
                cur_n = 0
                res = []
                for si in reversed(li) if reverse else li:
                    if self.trade_exchange.is_stock_tradable(
                            stock_id=si,
                            start_time=trade_start_time,
                            end_time=trade_end_time
                    ):
                        res.append(si)
                        cur_n += 1
                        if cur_n >= n:
                            break
                return res[::-1] if reverse else res

            def get_last_n(li, n):
                return get_first_n(li, n, reverse=True)

            def filter_stock(li):
                return [si for si in li if self.trade_exchange.is_stock_tradable(
                    stock_id=si,
                    start_time=trade_start_time,
                    end_time=trade_end_time
                )]
        else:
            # Otherwise, the stock will make decision without the stock tradable info
            def get_first_n(li, n):
                return list(li)[:n]

            def get_last_n(li, n):
                return list(li)[-n:]

            def filter_stock(li):
                return li

        current_temp: Position = copy.deepcopy(self.trade_position)
        # generate order list for this adjust date
        sell_order_list = []
        buy_order_list = []

        # load score
        cash = current_temp.get_cash()
        current_stock_list = current_temp.get_stock_list()

        # last position (sorted by score)
        last = pred_score.reindex(current_stock_list).sort_values(ascending=False).index

        # The new stocks today want to buy **at most**
        if self.method_buy == "top":
            # 获取候选股票列表（按分数从高到低排序）
            candidate_stocks = pred_score[~pred_score.index.isin(last)].sort_values(ascending=False).index

            # 1. 先获取初始候选股票（按分数排序的前 self.n_drop + self.topk - len(last) 只）
            initial_required_count = self.n_drop + self.topk - len(last)
            initial_today = get_first_n(candidate_stocks, initial_required_count)

            # 2. 应用涨幅过滤
            filtered_today = self._filter_stocks_by_return_threshold(initial_today, trade_start_time)

            # # 3. 检查是否需要补充
            # if len(filtered_today) < initial_required_count:
            #     # 4. 从剩余候选股票中补充（排除已考虑的initial_today）
            #     remaining_candidate = candidate_stocks[~candidate_stocks.isin(initial_today)]
            #     # 5. 从剩余候选中按分数排序取需要的数量
            #     additional_count = initial_required_count - len(filtered_today)
            #     additional_today = get_first_n(remaining_candidate, additional_count)
            #     # 6. 合并过滤后的股票和补充的股票
            #     today = filtered_today + additional_today
            # else:
            #     today = filtered_today

            # 3. 检查是否需要补充
            if len(filtered_today) < initial_required_count:
                # 4. 从剩余候选股票中补充（排除已考虑的initial_today）
                remaining_candidate = candidate_stocks[~candidate_stocks.isin(initial_today)]

                # 5. 对剩余候选股票也进行涨幅过滤
                filtered_remaining = self._filter_stocks_by_return_threshold(remaining_candidate, trade_start_time)

                # 6. 从过滤后的剩余候选中取需要的数量
                additional_count = initial_required_count - len(filtered_today)
                additional_today = get_first_n(filtered_remaining, additional_count)

                # 7. 合并过滤后的股票和补充的股票
                today = filtered_today + additional_today
            else:
                today = filtered_today

        elif self.method_buy == "random":
            topk_candi = get_first_n(pred_score.sort_values(ascending=False).index, self.topk)
            candi = list(filter(lambda x: x not in last, topk_candi))
            n = self.n_drop + self.topk - len(last)
            try:
                today = np.random.choice(candi, n, replace=False)
            except ValueError:
                today = candi
        else:
            raise NotImplementedError(f"This type of input is not supported")

        # combine(new stocks + last stocks), we will drop stocks from this list
        # In case of dropping higher score stock and buying lower score stock.
        comb = pred_score.reindex(last.union(pd.Index(today))).sort_values(ascending=False).index

        # Get the stock list we really want to sell (After filtering the case that we sell high and buy low)
        if self.method_sell == "bottom":
            sell = last[last.isin(get_last_n(comb, self.n_drop))]
        elif self.method_sell == "random":
            candi = filter_stock(last)
            try:
                sell = pd.Index(np.random.choice(candi, self.n_drop, replace=False) if len(last) else [])
            except ValueError:
                # No enough candidates
                sell = candi
        else:
            raise NotImplementedError(f"This type of input is not supported")

        # Get the stock list we really want to buy
        # buy = today[:len(sell) + self.topk - len(last)]
        # 在 today = filtered_today + additional_today 之后
        # 再次过滤 today 中所有股票，确保全部满足条件
        today_verified = self._filter_stocks_by_return_threshold(today, trade_start_time)
        buy = today_verified[:len(sell) + self.topk - len(last)]

        for code in current_stock_list:
            if not self.trade_exchange.is_stock_tradable(
                    stock_id=code,
                    start_time=trade_start_time,
                    end_time=trade_end_time,
                    direction=None if self.forbid_all_trade_at_limit else OrderDir.SELL,
            ):
                continue
            if code in sell:
                # check hold limit
                time_per_step = self.trade_calendar.get_freq()
                if current_temp.get_stock_count(code, bar=time_per_step) < self.hold_thresh:
                    continue
                # sell order
                sell_amount = current_temp.get_stock_amount(code=code)
                sell_order = Order(
                    stock_id=code,
                    amount=sell_amount,
                    start_time=trade_start_time,
                    end_time=trade_end_time,
                    direction=Order.SELL,  # 0 for sell, 1 for buy
                )
                # is order executable
                if self.trade_exchange.check_order(sell_order):
                    sell_order_list.append(sell_order)
                trade_val, trade_cost, trade_price = self.trade_exchange.deal_order(
                    sell_order, position=current_temp
                )
                # update cash
                cash += trade_val - trade_cost

        # buy new stock
        # note the current has been changed
        value = cash * self.risk_degree / len(buy) if len(buy) > 0 else 0

        # set open_cost limit
        for code in buy:
            # check is stock suspended
            if not self.trade_exchange.is_stock_tradable(
                    stock_id=code,
                    start_time=trade_start_time,
                    end_time=trade_end_time,
                    direction=None if self.forbid_all_trade_at_limit else OrderDir.BUY,
            ):
                continue
            # buy order
            buy_price = self.trade_exchange.get_deal_price(
                stock_id=code,
                start_time=trade_start_time,
                end_time=trade_end_time,
                direction=OrderDir.BUY,
            )
            buy_amount = value / buy_price
            factor = self.trade_exchange.get_factor(
                stock_id=code,
                start_time=trade_start_time,
                end_time=trade_end_time,
            )
            buy_amount = self.trade_exchange.round_amount_by_trade_unit(buy_amount, factor)
            buy_order = Order(
                stock_id=code,
                amount=buy_amount,
                start_time=trade_start_time,
                end_time=trade_end_time,
                direction=Order.BUY,  # 1 for buy
            )
            buy_order_list.append(buy_order)

        return TradeDecisionWO(sell_order_list + buy_order_list, self)