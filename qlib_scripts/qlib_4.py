import multiprocessing
import qlib
import logging
from qlib.constant import REG_CN    # 中国市场

# 特征 API

if __name__ == '__main__':
    multiprocessing.freeze_support() # 添加这一行，特别是在 Windows 上打包时可能有帮助

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

"""
from qlib.data.ops import EMA, RSI

# 计算 12 日和 26 日指数移动平均线
ema12 = EMA($close, 12)
ema26 = EMA($close, 26)

# 计算 RSI 指标
rsi = RSI($close, 14)

QLib 的最新版本中，特征计算通常通过定义表达式字符串并将其集成到数据处理器（DataHandler）或数据集（Dataset）的配置中来实现，而不是直接调用类似 EMA($close, 12)的函数。
"""

# 定义要计算的指标表达式
ema12_exp = "EMA($close, 12)"   # 12日指数移动平均线
ema26_exp = "EMA($close, 26)"   # 26日指数移动平均线
rsi14_exp = "RSI($close, 14)"   # 14日相对强弱指数 [1,5](@ref)

# 将这些表达式集成到您的数据处理器配置或特征列表中
# 例如，在定义 DataHandler 或 Dataset 时使用：
fields = [ema12_exp, ema26_exp, rsi14_exp]
names = ['EMA_12', 'EMA_26', 'RSI_14'] # 为每个特征指定名称