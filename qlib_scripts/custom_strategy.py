from pprint import pprint                                           # 导入美观打印模块，用于格式化输出数据结构

from qlib.contrib.strategy import TopkDropoutStrategy               # 导入基础策略类
from qlib.data import D                                             # 导入QLib数据接口
from qlib.utils import get_pre_trading_date, load_dataset,get_date_by_shift # 导入QLib工具函数
import pandas as pd                                                 # 导入pandas数据处理库
import numpy as np                                                  # 导入numpy数值计算库
from qlib.backtest.position import Position                         # 导入仓位管理类
from qlib.backtest.signal import Signal                             # 导入信号类
from qlib.backtest.decision import Order, OrderDir, TradeDecisionWO # 导入交易决策相关类
from qlib.log import get_module_logger                              # 导入日志记录器
from qlib.utils import copy                                         # 导入复制工具
from qlib.contrib.strategy.order_generator import OrderGenerator, OrderGenWOInteract    # 导入订单生成器

from loguru import logger   # 导入日志库

class TopkDropoutStrategyWithFilter(TopkDropoutStrategy):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)   # 调用父类构造函数
        self.max_return_threshold = 0.15    # 设置最大收益阈值（15%），超过此阈值的股票将被过滤
        self.lookback_days = 5              # 设置回溯天数（5天），用于计算历史收益
        self.logger = get_module_logger("TopkDropoutStrategyWithFilter")    # 获取模块专用的日志记录器


    def _filter_stocks_by_return_threshold_old(self, stocks, trade_start_time,initial_required_count):
        """ 过滤过去回溯天数内涨幅超过阈值的股票，增强稳定性 """
        # 1. 验证输入参数
        if self.lookback_days <= 0 or self.max_return_threshold < 0:
            return stocks  # 简单处理无效输入

        # ValueError: The truth value of a Index is ambiguous. Use a.empty, a.bool(), a.item(), a.any() or a.all().
        # 2. 检查股票列表是否为空
        if stocks is None or len(stocks) == 0:
            return stocks
        else:
            pass
            # 记录警告日志，显示当前检查的股票列表
            logger.warning(f"本次 {trade_start_time} 检查的股票列表 {stocks}")

        # 3. 获取有效起始日期
        prev_dates_first = get_date_by_shift(trade_start_time, -1 ,future=False)
        if prev_dates_first is None:
            # 记录警告，但不中断执行
            logger.warning(f"prev_dates_first无效交易日 for ：{trade_start_time} - 1 days ago")
        else:
            logger.warning(f"prev_dates_first有效交易日 for ：{trade_start_time} - 1 days ago")

        # 4. 获取有效结束日期
        prev_dates_last = get_date_by_shift(trade_start_time, -(self.lookback_days+1) ,future=False)
        if prev_dates_last is None:
            # 记录警告，但不中断执行
            logger.warning(f"prev_dates_last无效交易日 for {trade_start_time} - {(self.lookback_days+1)} days ago")
        else:
            logger.warning(f"prev_dates_last有效交易日 for {trade_start_time} - {(self.lookback_days+1)} days ago")

        logger.info(f"确保有效日期从 {prev_dates_first} 至 {prev_dates_last}")

        # 5. 获取数据，添加错误处理
        try:
            close_prices = D.features(
                instruments=stocks,
                fields=["$close"],
                start_time=prev_dates_last,
                end_time=prev_dates_first,
            )
        except Exception as e:
            logger.error(f"Failed to fetch stock data: {str(e)}")
            return stocks

        # 6. 处理数据缺失
        if close_prices.empty:
            logger.warning("No stock price data returned")
            return stocks

        # 7. 重置索引，将datetime和instrument作为列
        close_prices = close_prices.reset_index()
        logger.info(
            f"重置索引，将datetime和instrument作为列 {close_prices}")

        # 8. 按股票分组，获取每个股票的起始和结束收盘价
        prices = close_prices.groupby('instrument')["$close"].agg(['first', 'last']).reset_index()
        logger.info(
            f"10. 按股票分组，获取每个股票的起始和结束收盘价 {prices}")

        # 9. 计算涨幅，正确处理缺失值
        prices['return'] = (prices['last'] - prices['first']) / prices['first']
        prices['return'] = prices['return'].fillna(float('-inf'))  # 用负无穷填充缺失值,更安全的缺失值处理

        # 10. 创建股票到涨幅的映射字典
        return_dict = {row['instrument']: row['return'] for _, row in prices.iterrows()}
        pprint('创建股票到涨幅的映射字典')
        pprint(return_dict)
        logger.info(
            f"创建股票到涨幅的映射字典 {return_dict}")

        # 11. 过滤股票，添加日志记录
        filtered_stocks = [stock for stock in stocks if
                           return_dict.get(stock, float('-inf')) <= self.max_return_threshold]

        # 12. 记录每只股票的过滤结果
        for stock in stocks:
            return_xxx = return_dict.get(stock, float('-inf'))
            if return_dict.get(stock, float('-inf')) <= self.max_return_threshold:
                logger.info(
                    f"Paasssed {stock} {return_xxx} <= {self.max_return_threshold}")
            else:
                logger.info(
                    f"Filtered {stock} {return_xxx} > {self.max_return_threshold}")

        # 13. 记录总体过滤结果
        logger.info(
            f"Filtered {len(stocks)} stocks to {len(filtered_stocks)} using return threshold {self.max_return_threshold}")

        return filtered_stocks

    def _filter_stocks_by_return_threshold(self, stocks, trade_start_time,initial_required_count):
        """
        用极致性能方案过滤涨幅超过阈值的股票（仅查询首尾两天数据，无中间历史数据）

        参数:
        stocks: 股票代码列表
        trade_start_time: 结束日期（交易日，如'2025-04-01'）

        返回:
        涨幅不超过阈值的股票列表
        """
        # 1. 验证输入参数
        if self.lookback_days <= 0 or self.max_return_threshold < 0:
            return stocks  # 简单处理无效输入

        # ValueError: The truth value of a Index is ambiguous. Use a.empty, a.bool(), a.item(), a.any() or a.all().
        # 2. 检查股票列表是否为空
        if stocks is None or len(stocks) == 0:
            return stocks
        else:
            pass
            # 记录警告日志，显示当前检查的股票列表
            logger.warning(f"本次 {trade_start_time} 检查的股票列表 {stocks}")

        # 3. 获取有效起始日期
        prev_dates_first = get_date_by_shift(trade_start_time, -1 ,future=False)
        if prev_dates_first is None:
            # 记录警告，但不中断执行
            logger.warning(f"prev_dates_first无效交易日 for ：{trade_start_time} - 1 days ago")
            return stocks
        else:
            logger.warning(f"prev_dates_first有效交易日 for ：{trade_start_time} - 1 days ago")

        # 4. 获取有效结束日期
        prev_dates_last = get_date_by_shift(trade_start_time, -(self.lookback_days+1) ,future=False)
        if prev_dates_last is None:
            # 记录警告，但不中断执行
            logger.warning(f"prev_dates_last无效交易日 for {trade_start_time} - {(self.lookback_days+1)} days ago")
            return stocks
        else:
            logger.warning(f"prev_dates_last有效交易日 for {trade_start_time} - {(self.lookback_days+1)} days ago")


        # 5. 直接获取首尾两天收盘价（仅查询2天数据！）
        try:
            # 获取起始日收盘价（只查1天）
            start_price = D.features(
                instruments=stocks,
                fields=["$close"],
                start_time=prev_dates_last,
                end_time=prev_dates_last,  # 精确到单日
            )

            # 获取结束日收盘价（只查1天）
            end_price = D.features(
                instruments=stocks,
                fields=["$close"],
                start_time=prev_dates_first,
                end_time=prev_dates_first,  # 精确到单日
            )
        except Exception as e:
            logger.error(f"Data fetch failed: {str(e)}")
            return stocks

        # 6. 处理空数据情况
        if start_price.empty or end_price.empty:
            logger.warning("Empty price data for start/end dates")
            return stocks

        # 7. 直接计算涨幅（避免数据重置和合并）
        # 将start_price和end_price转换为Series，使用股票代码作为索引
        start_series = start_price['$close']
        end_series = end_price['$close']

        # 仅保留同时存在于start_series和end_series中的股票
        common_stocks = start_series.index.intersection(end_series.index)
        start_series = start_series.loc[common_stocks]
        end_series = end_series.loc[common_stocks]

        # 计算涨幅
        returns = (end_series - start_series) / start_series

        # 处理无穷大和NaN值
        returns = returns.replace([float('inf'), float('-inf')], float('-inf'))

        # 创建股票涨幅映射
        return_dict = returns.to_dict()

        # 8. 过滤股票（使用循环，允许提前终止）
        filtered_stocks = []
        for stock in stocks:
            return_val = return_dict.get(stock, float('-inf'))
            if return_val <= self.max_return_threshold:
                filtered_stocks.append(stock)
                if len(filtered_stocks) >= initial_required_count:
                    break

        # 9. 记录过滤结果
        logger.info(
            f"Filtered {len(stocks)} stocks to {len(filtered_stocks)} using threshold {self.max_return_threshold:.2%}")

        return filtered_stocks

    # 方法 generate_trade_decision Qlib 策略基类 BaseStrategy中定义的抽象方法，所有自定义策略都必须实现它。它在回测的每个时间步（由执行器频率决定，默认为每天）都会被回测引擎调用，是策略逻辑的核心入口
    # 参数 execute_result：它包含了上一个交易决策的执行结果（例如，哪些订单成交了，成交价格多少）。在策略开始运行时或没有待处理订单时，它可能是 None。策略可以根据这些信息来调整当前的决策
    def generate_trade_decision(self, execute_result=None):
        # 调用父类方法获取基础交易决策
        trade_step = self.trade_calendar.get_trade_step()
        # 从 trade_calendar（交易日历管理器）中获取当前回测进行到的步骤索引
        # Qlib 的回测过程由 TradeCalendarManager管理，它将整个回测时间范围划分为多个时间步（trade step）。
        # trade_step是一个从 0 开始的整数，随着回测进行而递增。这个方法返回的就是当前的步数，用于定位在时间轴上的位置
        trade_start_time, trade_end_time = self.trade_calendar.get_step_time(trade_step)
        logger.info(
            f"获取当前这个交易决策步骤所对应的实际交易时间范围 {trade_start_time} 到 {trade_end_time} 标明了“今天”这个交易日的时间区间（通常是同一天的开始和结束时刻）")
        pred_start_time, pred_end_time = self.trade_calendar.get_step_time(trade_step, shift=1)
        # 注意参数 shift=1。这表示将时间窗口向前（过去）移动了一个周期。
        # 这样设计的目的是确保在 trade_step这个时间点做决策时，所使用的预测信号是基于在此之前已经发生的历史数据计算得出的，严格符合回测的因果关系。
        # 例如，在回测到第5天（trade_step=4）时，这里获取的是第4天及之前的数据来生成信号，用于第5天的交易。
        logger.info(
            f"获取用于计算预测信号（pred_score）的时间范围 {pred_start_time} 到 {pred_end_time} 标明了“今天”这个交易日的时间区间（通常是同一天的开始和结束时刻）")
        pred_score = self.signal.get_signal(start_time=pred_start_time, end_time=pred_end_time)
        # 调用信号对象的方法，获取在指定的预测时间范围内所有股票的预测分数
        # pred_score通常是一个 Pandas Series 或 DataFrame，索引为日期和股票代码，包含一列名为 score的预测值。这个分数是排序和选择股票的依据——通常认为分数越高的股票未来表现越好

        # NOTE: the current version of topk dropout strategy can't handle pd.DataFrame(multiple signal)
        # So it only leverage the first col of signal
        # 注意：当前版本的 topk dropout 策略无法处理 pandas DataFrame（多信号数据），因此它只能利用信号的第一列。
        if isinstance(pred_score, pd.DataFrame):    # 处理信号数据类型：如果为DataFrame则取第一列
            pred_score = pred_score.iloc[:, 0]
        if pred_score is None:
            return TradeDecisionWO([], self)

        # 根据是否只考虑可交易股票设置不同的过滤函数
        if self.only_tradable:
            # If The strategy only consider tradable stock when make decision
            # It needs following actions to filter stocks
            # 如果策略在做出决策时只考虑可交易的股票,则需要执行以下操作来筛选股票
            # 如果希望策略在执行时自动过滤掉无法交易的股票（例如停牌、涨跌停或不在交易时间的股票），就需要在代码中实现相应的过滤逻辑
            def get_first_n(li, n, reverse=False):
                """获取前n个可交易股票"""
                cur_n = 0
                res = []
                for si in reversed(li) if reverse else li:
                    # 检查股票是否可交易
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
                """获取最后n个可交易股票"""
                return get_first_n(li, n, reverse=True)

            def filter_stock(li):
                """过滤可交易股票"""
                return [si for si in li if self.trade_exchange.is_stock_tradable(
                    stock_id=si,
                    start_time=trade_start_time,
                    end_time=trade_end_time
                )]
        else:
            # Otherwise, the stock will make decision without the stock tradable info
            # 否则，系统将在不考虑该股票是否可交易的情况下，对其做出决策。
            def get_first_n(li, n):
                return list(li)[:n]

            def get_last_n(li, n):
                return list(li)[-n:]

            def filter_stock(li):
                return li

        # 深拷贝当前仓位状态
        current_temp: Position = copy.deepcopy(self.trade_position)
        # generate order list for this adjust date 为这个调整日期生成订单列表
        sell_order_list = []    # 卖出订单列表
        buy_order_list = []     # 买入订单列表

        # 获取当前现金和股票列表
        cash = current_temp.get_cash()
        current_stock_list = current_temp.get_stock_list()

        # 获取上一期持仓股票（按分数排序）
        last = pred_score.reindex(current_stock_list).sort_values(ascending=False).index

        # The new stocks today want to buy **at most**
        # 生成今日候选买入股票列表
        if self.method_buy == "top":
            # 获取候选股票列表（按分数从高到低排序），排除掉上一期持仓股票
            candidate_stocks = pred_score[~pred_score.index.isin(last)].sort_values(ascending=False).index

            # 1. 先获取初始候选股票（按分数排序的前 self.n_drop + self.topk - len(last) 只）
            # self.n_drop   计划卖出数量
            # self.topk     目标持仓数量
            # len(last)     当前持仓数量
            # 需要买入的新股票数量 = 目标持仓数量 - (当前持仓数量 - 计划卖出数量)
            initial_required_count = self.n_drop + self.topk - len(last)
            # initial_today = filter_stock(candidate_stocks)
            # 取排名前200的股票，全部股票太多了
            initial_today = get_first_n(candidate_stocks, 200)

            # logger.info(
            #     f"{pred_start_time} 到 {pred_end_time} 预测信号（pred_score）的 {pred_score.head(30)}")

            # 2. 应用涨幅过滤
            filtered_today = self._filter_stocks_by_return_threshold(initial_today, trade_start_time,initial_required_count)
            filtered_today = filtered_today[:initial_required_count]

            # 3. 检查是否需要补充
            if len(filtered_today) < initial_required_count:
                logger.info(
                    f"过滤了 {len(filtered_today)} 需要补足到  {initial_required_count}，要2次过滤了 ")
                # 4. 从剩余候选股票中补充（排除已考虑的initial_today）
                remaining_candidate = candidate_stocks[~candidate_stocks.isin(initial_today)]

                # 优化点：仅处理前5倍所需数量的股票
                max_process = (initial_required_count - len(filtered_today)) * 5
                processed_remaining = remaining_candidate[:max_process]

                # 5. 对部分候选股票也进行涨幅过滤
                filtered_remaining = self._filter_stocks_by_return_threshold(processed_remaining, trade_start_time,initial_required_count)

                # 6. 从过滤后的剩余候选中取需要的数量
                additional_count = initial_required_count - len(filtered_today)
                additional_today = get_first_n(filtered_remaining, additional_count)

                # 7. 合并过滤后的股票和补充的股票
                today = filtered_today + additional_today
            else:
                today = filtered_today

        elif self.method_buy == "random":
            # 随机选择买入股票的方法
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
        # 合并新旧股票列表，并排序
        comb = pred_score.reindex(last.union(pd.Index(today))).sort_values(ascending=False).index

        # Get the stock list we really want to sell (After filtering the case that we sell high and buy low)
        # 生成卖出股票列表
        if self.method_sell == "bottom":
            sell = last[last.isin(get_last_n(comb, self.n_drop))]
        elif self.method_sell == "random":
            # 随机卖出股票
            candi = filter_stock(last)
            try:
                sell = pd.Index(np.random.choice(candi, self.n_drop, replace=False) if len(last) else [])
            except ValueError:
                # No enough candidates
                sell = candi
        else:
            raise NotImplementedError(f"This type of input is not supported")

        # Get the stock list we really want to buy
        # 生成买入股票列表
        buy = today[:len(sell) + self.topk - len(last)]

        # 生成卖出订单
        for code in current_stock_list:
            # 检查股票是否可交易
            if not self.trade_exchange.is_stock_tradable(
                    stock_id=code,
                    start_time=trade_start_time,
                    end_time=trade_end_time,
                    direction=None if self.forbid_all_trade_at_limit else OrderDir.SELL,
            ):
                continue
            if code in sell:
                # check hold limit
                # 检查持仓限制
                time_per_step = self.trade_calendar.get_freq()
                if current_temp.get_stock_count(code, bar=time_per_step) < self.hold_thresh:
                    continue
                # sell order
                # 创建卖出订单
                sell_amount = current_temp.get_stock_amount(code=code)
                sell_order = Order(
                    stock_id=code,
                    amount=sell_amount,
                    start_time=trade_start_time,
                    end_time=trade_end_time,
                    direction=Order.SELL,  # 0 for sell, 1 for buy
                )
                # is order executable
                # 检查订单是否可执行
                if self.trade_exchange.check_order(sell_order):
                    sell_order_list.append(sell_order)
                # 处理订单并更新现金
                trade_val, trade_cost, trade_price = self.trade_exchange.deal_order(
                    sell_order, position=current_temp
                )
                # update cash
                cash += trade_val - trade_cost

        # buy new stock
        # note the current has been changed
        # 生成买入订单
        value = cash * self.risk_degree / len(buy) if len(buy) > 0 else 0

        # set open_cost limit
        # 设置买入成本限制
        for code in buy:
            # check is stock suspended
            # 检查股票是否可交易
            if not self.trade_exchange.is_stock_tradable(
                    stock_id=code,
                    start_time=trade_start_time,
                    end_time=trade_end_time,
                    direction=None if self.forbid_all_trade_at_limit else OrderDir.BUY,
            ):
                continue
            # buy order
            # 创建买入订单
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
        # 返回交易决策（包含所有买卖订单）
        return TradeDecisionWO(sell_order_list + buy_order_list, self)