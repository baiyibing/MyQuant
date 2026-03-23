import multiprocessing
import qlib
import logging
from qlib.constant import REG_CN    # 中国市场
from qlib.data.cache import DiskExpressionCache  # 导入磁盘缓存类
from qlib.utils import init_instance_by_config

# 磁盘缓存（执行不成功）
"""
关键改写说明和最佳实践建议：
1.集成化的工作流管理：强烈推荐使用 Qlib 的 R(Recorder) 工作流系统来管理数据处理器等对象。这比直接使用 pickle更加强大和可靠，因为它：
自动处理对象的依赖关系和存储路径。与实验跟踪紧密结合，便于复现和管理不同版本的数据处理器。
提供统一的 API 来保存和加载各种对象（模型、处理器、数据集等）。

2.更完整的处理器配置：在配置中添加了 infer_processors和 learn_processors，这些是 DataHandlerLP的核心组成部分，用于数据预处理和标准化
。这使得缓存的价值更大，因为预处理可能比较耗时。

3.安全的对象序列化：直接使用 Python 的 pickle模块序列化复杂的对象（如 DataHandler）有时可能会遇到问题，特别是当对象包含无法被 pickle 的属性
（如某些计算图、数据库连接、线程锁等）或者 Qlib 内部数据结构发生变化时。通过工作流管理，Qlib 可能会使用更稳定和版本感知的序列化机制。

4.可复现性：通过 recorder.log_params()记录了处理器的配置信息，这对于后期追溯和复现实验至关重要。

5.缓存必要性评估：数据处理器 (DataHandler) 的主要职责是加载数据和应用处理器 (Processors)。
如果您的原始数据没有变化，并且处理器是确定的（例如 ZScoreNorm在 fit_start_time和 fit_end_time内拟合的参数不变），
那么缓存处理器可以节省每次初始化后拟合处理器的时间。如果数据经常更新或处理器配置改变，则需要重新创建和拟合处理器。
"""

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
        # expression_cache=DiskExpressionCache,  # 使用磁盘表达式缓存 加上此句报错
        # dataset_cache=DiskDatasetCache,      # 如需数据集缓存也可配置
        # mem_cache_size=10,                  # 内存缓存大小 (GB)
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

    # 定义任务配置（使用新版配置格式）
    task_config = {
        "model": {
            "class": "LGBModel",
            "module_path": "qlib.contrib.model.gbdt",
            "kwargs": {
                "loss": "mse",
                "colsample_bytree": 0.8879,
                "learning_rate": 0.0421,
                "subsample": 0.8789,
                "lambda_l1": 205.6999,
                "lambda_l2": 580.9768,
                "max_depth": 8,
                "num_leaves": 210,
                "num_threads": 20,
            },
        },
        "dataset": {
            "class": "DatasetH",
            "module_path": "qlib.data.dataset",
            "kwargs": {
                "handler": {
                    "class": "Alpha158",
                    "module_path": "qlib.contrib.data.handler",
                    "kwargs": {
                        "start_time": "2010-01-01",
                        "end_time": "2020-12-31",
                        "fit_start_time": "2010-01-01",
                        "fit_end_time": "2014-12-31",
                        "instruments": "csi300",
                    },
                },
                "segments": {
                    "train": ("2010-01-01", "2014-12-31"),
                    "valid": ("2015-01-01", "2016-12-31"),
                    "test": ("2017-01-01", "2020-12-31"),
                },
            },
        },
    }

    # import qlib
    import pandas as pd
    import numpy as np
    import seaborn as sns
    import matplotlib.pyplot as plt
    from qlib.data import D
    # from qlib.contrib.evaluate import calc_ic
    # from qlib.constant import REG_CN

    # 初始化Qlib（假设已配置数据）
    # qlib.init(provider_uri="~/.qlib/qlib_data/cn_data", region=REG_CN)

    # 定义分析参数
    instruments = "csi300"  # 股票池
    start_time = "2020-01-01"
    end_time = "2020-12-31"

    # 获取Alpha158因子数据（Qlib标准因子库）
    from qlib.contrib.data.handler import Alpha158

    # 创建数据处理器
    handler = Alpha158(
        instruments=instruments,
        start_time=start_time,
        end_time=end_time,
    )

    # 获取特征数据
    features = handler.fetch(col_set="feature")
    print(f"获取到特征数据形状: {features.shape}")

    # 计算特征相关性矩阵
    corr_matrix = features.corr()

    # 绘制完整相关性热图
    plt.figure(figsize=(16, 14))
    sns.heatmap(corr_matrix, cmap='coolwarm', center=0,
                square=True, cbar_kws={"shrink": 0.8})
    plt.title('Alpha158因子相关性矩阵 (全特征)', fontsize=16, pad=20)
    plt.tight_layout()
    plt.savefig('full_feature_correlation.png', dpi=300, bbox_inches='tight')
    plt.show()

    # 绘制前20个特征的相关性热图（更清晰）
    plt.figure(figsize=(14, 12))
    sns.heatmap(corr_matrix.iloc[:20, :20], annot=True, cmap='coolwarm',
                fmt='.2f', center=0, square=True, cbar_kws={"shrink": 0.8})
    plt.title('Alpha158因子相关性矩阵 (前20个特征)', fontsize=16, pad=20)
    plt.tight_layout()
    plt.savefig('top20_feature_correlation.png', dpi=300, bbox_inches='tight')
    plt.show()


