import pandas as pd
from qlib.data import D
from qlib.data.filter import BaseDFilter
from qlib.data.filter import NameDFilter, ExpressionDFilter


class ExcludeCSI300Filter(BaseDFilter):
    """
    自定义过滤器：排除CSI300成分股
    继承自BaseDFilter，实现从股票池中排除沪深300指数成分股的功能
    """

    def __init__(self, exclude_current_only=True):
        """
        初始化过滤器

        参数:
        exclude_current_only (bool):
            True: 仅排除当前是CSI300成分股的股票
            False: 排除在指定时间范围内任何时间点是CSI300成分股的股票
        """
        super().__init__()
        self.exclude_current_only = exclude_current_only
        self._csi300_cache = {}  # 缓存CSI300成分股列表

    def _get_csi300_stocks(self, start_time=None, end_time=None):
        """
        获取CSI300成分股列表

        参数:
        start_time (str): 开始时间，格式'YYYY-MM-DD'
        end_time (str): 结束时间，格式'YYYY-MM-DD'

        返回:
        set: CSI300成分股代码集合
        """
        cache_key = f"{start_time}_{end_time}"

        if cache_key not in self._csi300_cache:
            try:
                # 获取CSI300成分股
                csi300_instruments = D.instruments(market='csi300')

                if self.exclude_current_only and start_time is None:
                    # 仅获取当前成分股（使用最近的数据）
                    csi300_stocks = D.list_instruments(
                        instruments=csi300_instruments,
                        as_list=True
                    )
                else:
                    # 获取指定时间范围内的成分股
                    csi300_stocks = D.list_instruments(
                        instruments=csi300_instruments,
                        start_time=start_time or '2020-01-01',
                        end_time=end_time or pd.Timestamp.now().strftime('%Y-%m-%d'),
                        as_list=True
                    )

                self._csi300_cache[cache_key] = set(csi300_stocks)
                print(f"已加载CSI300成分股 {len(csi300_stocks)} 只")

            except Exception as e:
                print(f"获取CSI300成分股失败: {e}")
                self._csi300_cache[cache_key] = set()

        return self._csi300_cache[cache_key]

    def filter(self, code, start_time=None, end_time=None, data=None):
        """
        过滤函数：判断股票是否应该保留

        参数:
        code (str): 股票代码
        start_time (str): 开始时间
        end_time (str): 结束时间
        data: 额外数据（可选）

        返回:
        bool: True表示保留该股票，False表示排除
        """
        # 获取CSI300成分股列表
        csi300_stocks = self._get_csi300_stocks(start_time, end_time)

        # 如果股票在CSI300中，返回False（排除），否则返回True（保留）
        return code not in csi300_stocks

    @staticmethod
    def from_config(config):
        """从配置字典创建过滤器实例"""
        return ExcludeCSI300Filter(
            exclude_current_only=config.get("exclude_current_only", True)
        )

    def to_config(self):
        """将过滤器配置转换为字典"""
        return {
            "filter_type": "ExcludeCSI300Filter",
            "exclude_current_only": self.exclude_current_only
        }


class ExcludeStockListFilter(BaseDFilter):
    """
    更通用的自定义过滤器：排除指定股票列表中的股票
    可以从文件、列表或在线数据源加载要排除的股票列表
    """

    def __init__(self, exclude_stocks=None, exclude_file_path=None):
        """
        初始化过滤器

        参数:
        exclude_stocks (list): 要排除的股票代码列表
        exclude_file_path (str): 包含排除股票列表的文件路径
        """
        super().__init__()
        self.exclude_stocks = set()

        # 从列表加载
        if exclude_stocks:
            self.exclude_stocks.update([s.upper() for s in exclude_stocks])

        # 从文件加载
        if exclude_file_path:
            self._load_from_file(exclude_file_path)

    def _load_from_file(self, file_path):
        """从文件加载排除股票列表"""
        try:
            if file_path.endswith('.txt'):
                # 从文本文件加载（每行一个股票代码）
                with open(file_path, 'r', encoding='utf-8') as f:
                    stocks = [line.strip().upper() for line in f if line.strip()]
                self.exclude_stocks.update(stocks)
            elif file_path.endswith('.csv'):
                # 从CSV文件加载
                df = pd.read_csv(file_path)
                if 'code' in df.columns:
                    stocks = df['code'].astype(str).str.upper().tolist()
                    self.exclude_stocks.update(stocks)
            print(f"从文件加载排除股票 {len(stocks)} 只")
        except Exception as e:
            print(f"加载排除文件失败: {e}")

    def filter(self, code, start_time=None, end_time=None, data=None):
        """过滤函数"""
        return code not in self.exclude_stocks


# 使用示例
def demonstrate_exclude_filters():
    """
    演示如何使用自定义排除过滤器
    """
    # 初始化Qlib（请确保已正确配置）
    import qlib
    from qlib.config import REG_CN
    qlib.init(provider_uri='~/.qlib/qlib_data/cn_data', region=REG_CN)

    print("=" * 60)
    print("Qlib自定义排除过滤器演示")
    print("=" * 60)

    # 示例1：使用自定义CSI300排除过滤器
    print("\n1. 使用CSI300排除过滤器")

    # 创建排除CSI300的过滤器
    csi300_filter = ExcludeCSI300Filter(exclude_current_only=True)

    # 获取全市场股票，但排除CSI300成分股
    try:
        instruments = D.instruments(market='all', filter_pipe=[csi300_filter])
        stock_list = D.list_instruments(
            instruments=instruments,
            start_time='2023-01-01',
            end_time='2023-12-31',
            as_list=True
        )

        print(f"排除CSI300后剩余股票数量: {len(stock_list)}")
        print(f"前10只股票: {stock_list[:10]}")

    except Exception as e:
        print(f"获取股票列表失败: {e}")
        # 使用示例数据继续演示
        stock_list = ['SH600001', 'SH600002', 'SZ000001', 'SZ000002']

    # 示例2：使用通用股票列表排除过滤器
    print("\n2. 使用通用股票列表排除过滤器")

    # 定义要排除的股票列表
    exclude_list = ['SH600036', 'SZ000001', 'SZ000002', 'SH600519']

    custom_filter = ExcludeStockListFilter(exclude_stocks=exclude_list)

    # 测试过滤功能
    test_codes = ['SH600036', 'SH600001', 'SZ000001', 'SH600002']
    for code in test_codes:
        result = custom_filter.filter(code)
        print(f"股票 {code}: {'保留' if result else '排除'}")

    # 示例3：组合使用多个过滤器
    print("\n3. 组合使用多个过滤器")

    # 创建名称过滤器（只保留上海交易所股票）
    name_filter = NameDFilter(name_rule_re='^SH[0-9]{6}')

    # 创建表达式过滤器（收盘价大于5元）
    expression_filter = ExpressionDFilter(rule_expression='$close>5')

    # 组合过滤器：上海交易所 + 价格大于5元 + 排除CSI300
    combined_instruments = D.instruments(
        market='all',
        filter_pipe=[name_filter, expression_filter, csi300_filter]
    )

    try:
        combined_stocks = D.list_instruments(
            instruments=combined_instruments,
            start_time='2023-01-01',
            end_time='2023-12-31',
            as_list=True
        )

        print(f"组合过滤后股票数量: {len(combined_stocks)}")
        if combined_stocks:
            print(f"示例股票: {combined_stocks[:5]}")

    except Exception as e:
        print(f"组合过滤失败: {e}")

    # 示例4：获取特征数据（排除特定股票后）
    print("\n4. 获取排除后的特征数据")

    if stock_list:  # 使用前面获取的股票列表
        try:
            # 获取收盘价和成交量特征
            fields = ['$close', '$volume', 'Ref($close, 1)', '$high-$low']
            features_df = D.features(
                instruments=stock_list[:10],  # 只取前10只避免数据量过大
                fields=fields,
                start_time='2023-01-01',
                end_time='2023-01-10',  # 缩短时间范围
                freq='day'
            )

            print("特征数据形状:", features_df.shape)
            print("特征数据前5行:")
            print(features_df.head())

        except Exception as e:
            print(f"获取特征数据失败: {e}")


# 高级用法：动态排除过滤器
class DynamicExcludeFilter(BaseDFilter):
    """
    动态排除过滤器：可以根据时间动态调整排除规则
    例如，排除过去N日内涨幅过大的股票
    """

    def __init__(self, threshold=0.1, lookback_days=5):
        """
        初始化动态过滤器

        参数:
        threshold (float): 阈值，例如0.1表示排除过去5日内涨幅超过10%的股票
        lookback_days (int): 回溯天数
        """
        super().__init__()
        self.threshold = threshold
        self.lookback_days = lookback_days

    def filter(self, code, start_time=None, end_time=None, data=None):
        """动态过滤逻辑"""
        try:
            # 获取股票的历史价格数据
            price_data = D.features(
                [code],
                ['$close'],
                start_time=start_time,
                end_time=end_time,
                freq='day'
            )

            if price_data.empty:
                return True  # 如果没有数据，保留该股票

            # 计算涨幅
            closes = price_data.xs(code, level=0)['$close']
            if len(closes) < self.lookback_days + 1:
                return True  # 数据不足，保留

            recent_close = closes.iloc[-1]
            past_close = closes.iloc[-self.lookback_days - 1]

            # 计算涨幅
            returns = (recent_close - past_close) / past_close

            # 如果涨幅超过阈值，排除该股票
            return abs(returns) <= self.threshold

        except Exception as e:
            print(f"动态过滤股票 {code} 时出错: {e}")
            return True  # 出错时保留股票


if __name__ == "__main__":
    # 运行演示
    demonstrate_exclude_filters()

    print("\n" + "=" * 60)
    print("使用说明总结")
    print("=" * 60)
    print("1. 确保Qlib已正确初始化")
    print("2. 自定义过滤器可以单独使用或组合使用")
    print("3. 支持静态排除和动态排除两种模式")
    print("4. 可以缓存排除列表以提高性能")
    print("5. 过滤器可以序列化/反序列化用于实验记录")