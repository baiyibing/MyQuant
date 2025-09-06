import qlib
print(qlib.__version__)  # 如果能够打印出版本号，说明安装成功
from qlib.data import D
from qlib.data.ops import Feature, ExpressionOps

from qlib.constant import REG_CN    # 中国市场
import logging
from qlib.data.filter import NameDFilter
qlib.init(
    # 数据存储路径
    provider_uri='E:/PycharmProjects/MyQuant/.qlib/qlib_data/cn_data',
    # 中国市场
    region=REG_CN,
    # QLib 使用 Redis 进行缓存和锁机制,如果 Redis 连接失败，QLib 会自动降级为不使用缓存，这可能会影响性能但不会导致程序错误。
    redis_host='127.0.0.1',
    redis_port=6379,
    redis_password='123456',
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
    logging_level=logging.INFO
    # redis={
    #     "host": "localhost",  # 若Redis在远程服务器，请填写服务器IP
    #     "port": 6379,
    #     "password": "123456",  # 请替换为你的实际密码
    #     "db": 1
    # }
)

# 获取默认时间段的日线日历
calendar = D.calendar()
print(f"总交易日数: {len(calendar)}")
print(f"日期范围: {calendar[0]} 至 {calendar[-1]}")

# 获取指定时间段的日历
custom_calendar = D.calendar(start_time='2020-01-01', end_time='2020-12-31')
print(f"2020年交易日数: {len(custom_calendar)}")

# 获取所有股票
all_instruments = D.instruments(market='all')
all_stocks = D.list_instruments(instruments=all_instruments, as_list=True)
print(f"所有股票数量: {len(all_stocks)}")

# 获取CSI300成分股
csi300_instruments = D.instruments(market='csi300')
csi300_stocks = D.list_instruments(instruments=csi300_instruments, as_list=True)
print(f"CSI300成分股数量: {len(csi300_stocks)}")

# 按股票代码筛选
name_filter = NameDFilter(name_rule_re='SH[0-9]{4}55')  # 筛选代码以SH开头且后四位为数字，第五位为5的股票
filtered_instruments = D.instruments(market='csi300', filter_pipe=[name_filter])
filtered_stocks = D.list_instruments(instruments=filtered_instruments, as_list=True)
print(f"筛选后的股票: {filtered_stocks}")