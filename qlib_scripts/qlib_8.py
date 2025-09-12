import multiprocessing
import qlib
import logging
from qlib.data import D
from qlib.data.dataset.loader import QlibDataLoader
from qlib.data.filter import NameDFilter
from qlib.constant import REG_CN    # 中国市场

# 自定义处理器

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

    # 自定义处理器示例
    from qlib.data.dataset.processor import Processor
    from qlib.data.dataset.handler import DataHandlerLP
    from qlib.data.dataset.processor import (
        RobustZScoreNorm,
        CSZScoreNorm, # 使用CSZScoreNorm(截面标准化)代替普通的ZscoreNorm，更适合横截面金融数据
        Fillna,  # 引入内置的填充处理器
        DropnaLabel,
        TanhProcess # TanhProcess可限制极端值
    )

    # 除了内置的处理器，用户还可以通过继承 Processor 基类来实现自定义的数据处理器。自定义处理器需要实现 fit 和 transform 方法：
    class CustomProcessor(Processor):
        """自定义处理器示例"""

        def __init__(self, threshold=3.0):
            self.threshold = threshold

        def fit(self, df):
            # 计算每个特征的均值和标准差
            self.mean_ = df.mean()
            self.std_ = df.std()
            return self

        def transform(self, df):
            # 应用自定义转换逻辑
            return df.clip(
                lower=self.mean_ - self.threshold * self.std_,
                upper=self.mean_ + self.threshold * self.std_
            )


    # 定义处理器，其中包含 Fillna
    shared_processors = [
        Fillna(fill_value=0),  # 使用 Fillna 处理器统一填充缺失值为0
    ]

    # 表达式引擎创建特征[7](@ref)
    expression_handler = DataHandlerLP(
        instruments='csi300',
        start_time='2010-01-01',
        end_time='2020-12-31',
        data_loader=QlibDataLoader(config={
            "feature": (
                [
                    "($high - $low) / $close",  # 日波动率
                    "EMA($close, 10) / $close",  # 10日均线比率
                    # "If(IsNull($turnover), 0, $turnover)"  # 处理缺失值
                    "$turnover"  # 不再在表达式中处理缺失值，交由后续的Processor处理
                ],
                ["daily_vol", "ma_ratio", "turnover_adj"]
            )
        }),
        shared_processors=shared_processors,  # 添加共享处理器
        infer_processors=[],  # 根据你的需求添加推理处理器
        learn_processors=[]   # 根据你的需求添加学习处理器
    )