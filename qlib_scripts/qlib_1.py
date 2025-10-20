import multiprocessing
import logging

from timeit import default_timer as timer
from loguru import logger
import pandas as pd  # 导入pandas库进行数据处理
import qlib
from qlib.config import REG_CN
from qlib.contrib.data.handler import Alpha158
from qlib.contrib.evaluate import risk_analysis
from qlib.contrib.model import LGBModel
from qlib.contrib.report.analysis_position import report_graph
from qlib.utils import init_instance_by_config, flatten_dict
from qlib.workflow import R
from qlib.data.dataset import DatasetH
from qlib.contrib.strategy import TopkDropoutStrategy
from qlib.workflow.record_temp import SignalRecord, SigAnaRecord, PortAnaRecord
from qlib.contrib.report import analysis_model, analysis_position
from qlib.data import D  # 导入数据模块
from custom_handler import Alpha158CostKDJ
from custom_ops import SMA
import pandas as pd


from pprint import pprint
from custom_utils import pprint_position_report, analyze_position_by_date, generate_position_report, \
    pprint_risk_analysis


if __name__ == '__main__':
    multiprocessing.freeze_support() # 添加这一行，特别是在 Windows 上打包时可能有帮助

    print(qlib.__version__)  # 如果能够打印出版本号，说明安装成功

    start = timer()

    logger.remove(0)
    logger.add("ht.log")

    qlib.init(
        # 数据存储路径
        provider_uri = "~/.qlib/qlib_data/cn_data",  # target_dir
        # 中国市场
        region=REG_CN,
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
    from qlib.data.ops import Feature, ExpressionOps

    # # 使用表达式构造特征
    # f1 = Feature('high') / Feature('close')  # 最高价/收盘价
    # f2 = Feature('open') / Feature('close')  # 开盘价/收盘价
    # f3 = f1 + f2  # (最高价+开盘价)/收盘价
    # f4 = f3 * f3 / f3  # 简化为f3
    #
    # # 加载自定义特征
    # data = D.features(["SZ300408"], [f4], start_time="2020-01-01", end_time="2020-01-10")
    # print(data.head())

    # from qlib.data import D

    # 显示所有行
    pd.set_option('display.max_rows', None)
    # 显示所有列
    pd.set_option('display.max_columns', None)
    # 设置列宽，确保长文本完整显示
    pd.set_option('display.max_colwidth', None)
    # 设置显示宽度，防止自动换行
    pd.set_option('display.width', None)

    # 查询SZ300408在2025-10-日的OHLC数据
    data = D.features(
        instruments=["SZ300408"],  # 股票代码
        fields=["$open", "$high", "$low", "$close", "$adjclose", "$vwap", "$factor", "$change"],  # 字段：开盘、最高、最低、收盘价
        start_time="2025-09-04",  # 查询开始日期
        end_time="2025-09-05"     # 查询结束日期（与开始日期相同即可查询单日）
    )

    print(data)



    data = D.features(["SH688399"], ["$open", "$high", "$low", "$close", "$adjclose", "$vwap", "$factor", "$change"], "2025-06-10", "2025-06-13")
    print(data)

