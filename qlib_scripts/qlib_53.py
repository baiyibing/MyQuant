import multiprocessing
import qlib
import logging
from qlib.constant import REG_CN    # 中国市场
from qlib.data.cache import DiskExpressionCache  # 导入磁盘缓存类
from qlib.utils import init_instance_by_config

# 完整特征工程实现示例（执行不成功）
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

    # import qlib
    import pandas as pd
    from qlib.data import D
    from qlib.data.dataset import DatasetH
    from qlib.data.dataset.handler import DataHandlerLP
    from qlib.contrib.data.handler import Alpha158
    from qlib.data.dataset.processor import (
        DropnaLabel,
        RobustZScoreNorm,
        CSZScoreNorm,
        TanhProcess,
        Fillna
    )

    # 初始化Qlib (假设数据已准备)
    # qlib.init(provider_uri="~/.qlib/qlib_data/cn_data", region="cn")

    # 定义数据处理器配置 (新版API)
    handler_config = {
        "instruments": "csi300",  # 使用CSI300股票池
        "start_time": "2018-01-01",
        "end_time": "2023-01-01",
        "fit_start_time": "2018-01-01",  # 处理器拟合时间段
        "fit_end_time": "2020-12-31",
        # 新版处理器配置方式 - 分离推断和学习处理器
        "infer_processors": [
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature"}},
            {"class": "Fillna", "kwargs": {}},  # 处理缺失值
        ],
        "learn_processors": [
            {"class": "DropnaLabel"},  # 处理标签缺失值
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "feature"}},
            # {"class": "TanhProcess", "kwargs": {"threshold": 3}}  # 异常值处理
        ],
        "process_type": "append",  # 处理类型: independent 或 append
        "drop_raw": False  # 是否保留原始数据
    }

    # 创建数据处理器 (使用Alpha158因子集)
    handler = Alpha158(**handler_config)

    # 执行数据处理流程
    handler.fit_process_data()  # 新版API: 同时执行fit和transform

    print("可用特征列表:")
    print(handler.get_cols("feature"))  # 获取所有特征列名

    # 创建数据集
    dataset = DatasetH(
        handler=handler,
        segments={
            "train": ("2018-01-01", "2020-12-31"),
            "valid": ("2021-01-01", "2021-12-31"),
            "test": ("2022-01-01", "2023-01-01"),
        }
    )

    # 准备数据 (新版API)
    train_data = dataset.prepare("train", col_set=["feature", "label"])
    valid_data = dataset.prepare("valid", col_set=["feature", "label"])
    test_data = dataset.prepare("test", col_set=["feature", "label"])

    print(f"训练集特征形状: {train_data['feature'].shape}")
    print(f"验证集特征形状: {valid_data['feature'].shape}")
    print(f"测试集特征形状: {test_data['feature'].shape}")


    # 数据质量检查
    def check_data_quality(data, segment_name):
        """检查数据质量"""
        print(f"\n{segment_name} 数据质量检查:")
        print(f"特征缺失值比例: {data['feature'].isnull().mean().mean():.2%}")
        print(f"标签缺失值比例: {data['label'].isnull().mean():.2%}")
        print(f"特征值范围: [{data['feature'].min().min():.2f}, {data['feature'].max().max():.2f}]")


    # check_data_quality(train_data, "train")
    # check_data_quality(valid_data, "valid")
    # check_data_quality(test_data, "test")

    # 可选: 保存处理后的数据
    handler.save("./processed_handler.pkl")  # 保存处理器状态
    print("\n处理器状态已保存到 processed_handler.pkl")

    # 可选: 特征重要性分析 (如果与模型结合)
    try:
        feature_importance = handler.get_feature_importance()  # 如果处理器支持
        print("\n特征重要性预览:")
        print(feature_importance.head(10))
    except AttributeError:
        print("\n当前处理器不支持直接获取特征重要性")


