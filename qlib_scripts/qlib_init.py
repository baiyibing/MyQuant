# https://www.wuzao.com/qlib/tutorial/introduction
import qlib
print(qlib.__version__)  # 如果能够打印出版本号，说明安装成功

import logging
from qlib.data import D
from qlib.data.filter import NameDFilter
from qlib.constant import REG_CN    # 中国市场
import logging
# python scripts/get_data.py qlib_data --target_dir ~/.qlib/qlib_data/cn_data --region cn
# 下载会报错，元宝建议从https://github.com/chenditc/investment_data/releases/latest/download/qlib_bin.tar.gz下载解压到~/.qlib/qlib_data/cn_data

# qlib.init(provider_uri='~/.qlib/qlib_data/cn_data', region=REG_CN)    ~ 表示当前用户的“home”目录

# qlib.init(provider_uri='./.qlib/qlib_data/cn_data', region=REG_CN)
qlib.init(
    # 数据存储路径,自定义数据存储路径
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

# 初始化完成后，可以通过以下方式验证是否成功：如果能够成功输出交易日历和股票列表，说明初始化成功。

# 获取交易日历
calendar = D.calendar()
print(f"交易日历长度: {len(calendar)}")
print(f"最近5个交易日: {calendar[-5:]}")

# 获取股票列表
instruments = D.instruments(market='csi300')
stock_list = D.list_instruments(instruments=instruments, as_list=True)
print(f"CSI300成分股数量: {len(stock_list)}")
print(f"部分成分股: {stock_list[:5]}")


# 数据健康检查
# 为确保数据质量，QLib 提供了数据健康检查工具，可以检查数据是否存在缺失、异常波动等问题：
# 检查日线数据
# python scripts/check_data_health.py check_data --qlib_dir ~/.qlib/qlib_data/cn_data   ~ 表示linux当前用户的“home”目录
# python scripts/check_data_health.py check_data --qlib_dir ./.qlib/qlib_data/cn_data
# python scripts/check_data_health.py check_data --qlib_dir E:/PycharmProjects/MyQuant/.qlib/qlib_data/cn_data
# 检查1分钟线数据
# python scripts/check_data_health.py check_data --qlib_dir ~/.qlib/qlib_data/cn_data_1min --freq 1min
# 可以通过参数调整检查阈值：
# python scripts/check_data_health.py check_data --qlib_dir ~/.qlib/qlib_data/cn_data --missing_data_num 300 --large_step_threshold_price 20
# --missing_data_num：允许的最大缺失数据量
# --large_step_threshold_price：价格最大允许波动阈值
# --large_step_threshold_volume：成交量最大允许波动阈值

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