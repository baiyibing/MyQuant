import qlib
from qlib.constant import REG_CN    # 中国市场
import logging

print(qlib.__version__)  # 如果能够打印出版本号，说明安装成功

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

from qlib.data import D
from qlib.data.ops import Feature, ExpressionOps

# 使用表达式构造特征
f1 = Feature('high') / Feature('close')  # 最高价/收盘价
f2 = Feature('open') / Feature('close')  # 开盘价/收盘价
f3 = f1 + f2  # (最高价+开盘价)/收盘价
f4 = f3 * f3 / f3  # 简化为f3

# 加载自定义特征
data = D.features(["SH600519"], [f4], start_time="2020-01-01", end_time="2020-01-10")
print(data.head())