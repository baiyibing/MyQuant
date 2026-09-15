import os
import pandas as pd
from qlib.data import D
from qlib.utils import get_pre_trading_date


import multiprocessing
import logging
import os

from timeit import default_timer as timer


from loguru import logger
import pandas as pd  # 导入pandas库进行数据处理
import qlib
from qlib.config import REG_CN
from qlib.contrib.data.handler import Alpha158
from qlib.contrib.evaluate import risk_analysis
from qlib.contrib.model import LGBModel
from qlib.contrib.report.analysis_position import report_graph
from qlib.data.filter import ExpressionDFilter
from qlib.utils import init_instance_by_config, flatten_dict
from qlib.workflow import R
from qlib.data.dataset import DatasetH
from qlib.contrib.strategy import TopkDropoutStrategy
from qlib.workflow.record_temp import SignalRecord, SigAnaRecord, PortAnaRecord
from qlib.contrib.report import analysis_model, analysis_position
from qlib.data import D  # 导入数据模块
from custom_handler import Alpha158CostKDJ
from custom_ops import SMA

import sys
from pathlib import Path as _Path
_my_scripts = str(_Path(__file__).resolve().parent.parent / "my_scripts")
if _my_scripts not in sys.path:
    sys.path.insert(0, _my_scripts)
from handler_frame_cache import resolve_qlib_kernels
import plotly.graph_objects as go

# ====== 2. 创建测试用的简单类（不依赖任何策略） ======
class StockFilter:
    def __init__(self):
        self.max_return_threshold = 0.15  # 15%阈值
        self.lookback_days = 5  # 回溯天数

    def _filter_stocks_by_return_threshold(self, stocks, trade_start_time):
        """核心过滤方法（已修复列名问题）"""
        # 获取过去5个交易日的日期
        prev_dates = [get_pre_trading_date(trade_start_time, i) for i in range(1, self.lookback_days + 1)]

        # ✅ 修复：使用 D.features + $ 前缀获取数据
        close_prices = D.features(
            instruments=stocks,  # 直接传字符串"all"
            fields=["$close"],  # 关键：字段名带$前缀
            start_time=prev_dates[-1],
            end_time=prev_dates[0],
            freq="day"
        )

        # 重置索引，将datetime和instrument作为列
        close_prices = close_prices.reset_index()

        print("datetime column dtype:", close_prices["datetime"].dtype)
        print("Sample datetime values:", close_prices["datetime"].head())
        # close_prices["datetime"] = pd.to_datetime(close_prices["datetime"]).dt.date
        close_prices["datetime"] = close_prices["datetime"].dt.date

        # ✅ 修复：列名必须用"$close"（不是"close"）
        close_prices = close_prices.sort_values(by=["instrument", "datetime"])
        close_prices["close_shift"] = close_prices.groupby("instrument")["$close"].shift(self.lookback_days - 1)

        # 计算涨幅
        close_prices["return"] = (close_prices["$close"] - close_prices["close_shift"]) / close_prices["close_shift"]
        close_prices["return"] = close_prices["return"].fillna(0)

        # 获取最近一天的涨幅
        returns = close_prices.groupby("instrument").last()[["return"]]

        # 过滤股票
        filtered_stocks = []
        for stock in stocks:
            if stock in returns.index:
                if returns.loc[stock, "return"] <= self.max_return_threshold:
                    filtered_stocks.append(stock)
            else:
                filtered_stocks.append(stock)
        return filtered_stocks

if __name__ == '__main__':
    multiprocessing.freeze_support() # 添加这一行，特别是在 Windows 上打包时可能有帮助

    print(qlib.__version__)  # 如果能够打印出版本号，说明安装成功

    start = timer()

    logger.remove(0)
    logger.add("orders.log")

    _kernels = resolve_qlib_kernels()
    print(f"[qlib] kernels={_kernels} (QLIB_KERNELS, default 1)", flush=True)
    qlib.init(
        # 数据存储路径
        provider_uri = "~/.qlib/qlib_data/cn_data",  # target_dir
        # 中国市场
        region=REG_CN,
        kernels=_kernels,
        # QLib 使用 Redis 进行缓存和锁机制,如果 Redis 连接失败，QLib 会自动降级为不使用缓存，这可能会影响性能但不会导致程序错误。
        redis_host='127.0.0.1',
        redis_port=6379,
        redis_password='123456',
        redis_task_db=1,  # Redis 数据库编号
        custom_ops=[SMA],
        # 配置实验管理器，用于跟踪和管理实验结果
        exp_manager={
            "class": "MLflowExpManager",
            "module_path": "qlib.workflow.expm",
            "kwargs": {
                "uri": "mlruns",
                "default_exp_name": "MyExperiment",
            }
        },
        # 设置日志级别，控制输出信息的详细程度：常用的日志级别有 DEBUG、INFO、WARNING、ERROR，级别从低到高，级别越低输出信息越详细。
        # logging_level=logging.DEBUG
        logging_level=logging.INFO
    )

    from qlib.data import D

    df = D.features(["SH600519"], ["$close"], start_time="2023-01-01", end_time="2023-12-31")
    print(df)

    # 测试参数（确保日期是交易日）
    test_stocks = ["SH600519", "SH601318", "SZ000858"]  # 示例股票
    trade_start_time = "2023-01-31"

    # 创建过滤器实例
    filter = StockFilter()

    # 执行过滤
    filtered_stocks = filter._filter_stocks_by_return_threshold(
        stocks=test_stocks,
        trade_start_time=trade_start_time
    )

    # ====== 4. 验证结果 ======
    print("=" * 60)
    print(f"测试日期: {trade_start_time}")
    print(f"输入股票: {test_stocks}")
    print(f"过滤后股票: {filtered_stocks}")
    print("=" * 60)

    # 验证关键逻辑（示例：000001.SZ 应该被保留）
    print("\n验证逻辑（示例）:")
    print(f"SH600519 是否在结果中? {'SH600519' in filtered_stocks}")

    # 打印关键数据（用于调试）
    print("\n关键数据示例（SH600519的收盘价）:")
    close_data = D.features(
        instruments=["SH600519"],
        fields=["$close"],
        start_time="2023-01-17",  # 5个交易日前
        end_time="2023-01-31",
        freq="day"
    )
    print(close_data.head(3))